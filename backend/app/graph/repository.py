"""GraphRepository: relationship graph with scope-constrained traversal (plan §3.2 L3,
§3.6, §5.2, CLAUDE.md §2.1, §4.2).

The walk is constrained by the officer's `Scope` at every step: a node outside the scope is never
visited, never returned and never used as a stepping stone, so not even the existence of a path
through a restricted document can leak. Unconfirmed edges are skipped unless asked for (review).
The in-memory repository is the reference implementation and test double; Spanner Graph
implements the same Protocol later (CLAUDE.md §2.3: not Neo4j).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.auth.models import DocumentAccessTags, Scope


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EdgeKind(StrEnum):
    SUPERSEDES = "SUPERSEDES"
    AMENDS = "AMENDS"
    CLARIFIES = "CLARIFIES"
    REPEALS = "REPEALS"
    REFERENCES = "REFERENCES"
    CITES = "CITES"
    SAME_FILE = "SAME_FILE"
    CONFLICTS_WITH = "CONFLICTS_WITH"


class Direction(StrEnum):
    OUT = "out"  # source → target  (e.g. what does X supersede / cite)
    IN = "in"  # target ← source   (e.g. what supersedes / cites X)
    BOTH = "both"


class GraphNode(_Frozen):
    canonical_id: str
    tags: DocumentAccessTags  # location tags only; access is decided by the Scope


class GraphEdge(_Frozen):
    source: str
    kind: EdgeKind
    target: str
    confirmed: bool = True  # explicit in text or confirmed by an officer (plan §7.3)


class GraphHit(_Frozen):
    canonical_id: str
    hops: int = Field(ge=1)
    via: EdgeKind
    path: tuple[str, ...]  # seed → … → this node; every element is inside the scope


class GraphError(Exception):
    """Inconsistent graph (edge to an unknown node). Callers treat it as 'no expansion'."""


@runtime_checkable
class GraphRepository(Protocol):
    def upsert_node(self, node: GraphNode) -> None: ...

    def upsert_edge(self, edge: GraphEdge) -> None: ...

    def walk(
        self,
        seeds: Iterable[str],
        scope: Scope,
        *,
        kinds: frozenset[EdgeKind],
        direction: Direction,
        max_hops: int,
        include_unconfirmed: bool = False,
    ) -> list[GraphHit]:
        """Scope-constrained breadth-first walk. Seeds outside the scope are ignored."""
        ...


@runtime_checkable
class WalkableGraph(Protocol):
    """What the ladder's L3 rung needs: node tags (for the re-check) and the scoped walk."""

    def node(self, cid: str) -> GraphNode | None: ...

    def walk(
        self,
        seeds: Iterable[str],
        scope: Scope,
        *,
        kinds: frozenset[EdgeKind],
        direction: Direction,
        max_hops: int,
        include_unconfirmed: bool = False,
    ) -> list[GraphHit]: ...


class InMemoryGraphRepository:
    """Reference GraphRepository (mock / tests)."""

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._out: dict[str, set[GraphEdge]] = {}
        self._in: dict[str, set[GraphEdge]] = {}

    def upsert_node(self, node: GraphNode) -> None:
        self._nodes[node.canonical_id] = node

    def upsert_edge(self, edge: GraphEdge) -> None:
        if edge.source not in self._nodes or edge.target not in self._nodes:
            raise GraphError("edge endpoints must be known nodes")
        for bucket, key in ((self._out, edge.source), (self._in, edge.target)):
            # an edge is identified by (source, kind, target); confirming replaces it
            bucket.setdefault(key, set())
            bucket[key] = {
                e
                for e in bucket[key]
                if (e.source, e.kind, e.target) != (edge.source, edge.kind, edge.target)
            } | {edge}

    def edges(self) -> list[GraphEdge]:
        """Every edge, in a stable order (export / batch load; no scope: not a retrieval path)."""
        return sorted(
            {e for bucket in self._out.values() for e in bucket},
            key=lambda e: (e.source, e.kind.value, e.target),
        )

    def _visible(self, cid: str, scope: Scope) -> bool:
        node = self._nodes.get(cid)
        return node is not None and scope.admits(node.tags)

    def _steps(self, cid: str, direction: Direction) -> Iterable[tuple[GraphEdge, str]]:
        if direction in (Direction.OUT, Direction.BOTH):
            for e in sorted(self._out.get(cid, ()), key=lambda e: (e.kind, e.target)):
                yield e, e.target
        if direction in (Direction.IN, Direction.BOTH):
            for e in sorted(self._in.get(cid, ()), key=lambda e: (e.kind, e.source)):
                yield e, e.source

    def walk(
        self,
        seeds: Iterable[str],
        scope: Scope,
        *,
        kinds: frozenset[EdgeKind],
        direction: Direction,
        max_hops: int,
        include_unconfirmed: bool = False,
    ) -> list[GraphHit]:
        if max_hops < 1:
            raise ValueError("max_hops must be >= 1")
        start = [s for s in dict.fromkeys(seeds) if self._visible(s, scope)]
        seen = set(start)
        queue: deque[tuple[str, tuple[str, ...]]] = deque((s, (s,)) for s in start)
        hits: list[GraphHit] = []
        while queue:
            cid, path = queue.popleft()
            if len(path) - 1 >= max_hops:
                continue
            for edge, nxt in self._steps(cid, direction):
                if edge.kind not in kinds or (not edge.confirmed and not include_unconfirmed):
                    continue
                if nxt in seen or not self._visible(nxt, scope):
                    continue  # never visit, return or pass through a node outside the scope
                seen.add(nxt)
                hits.append(
                    GraphHit(canonical_id=nxt, hops=len(path), via=edge.kind, path=(*path, nxt))
                )
                queue.append((nxt, (*path, nxt)))
        return hits

    def node(self, cid: str) -> GraphNode | None:
        return self._nodes.get(cid)

    def node_ids(self) -> tuple[str, ...]:
        return tuple(self._nodes)

    def edges_to(self, cid: str) -> tuple[GraphEdge, ...]:
        return tuple(sorted(self._in.get(cid, ()), key=lambda e: (e.kind, e.source)))

    def edges_from(self, cid: str) -> tuple[GraphEdge, ...]:
        return tuple(sorted(self._out.get(cid, ()), key=lambda e: (e.kind, e.target)))
