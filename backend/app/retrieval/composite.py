"""Two stores behind one rung (plan §3.2; ADR-0028).

In the deployed sandbox the officer's e-Office papers (synthetic, ingested at start) live in
memory, and the public order corpus lives in the cloud stores (BigQuery L0-L2, Cloud SQL L3).
These wrappers let the ladder ask both through the same interfaces. Each part applies the
officer's scope itself; the wrapper only merges, so no part can widen what another part allows.
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from collections.abc import Iterable
from typing import Protocol

from app.auth.models import Scope
from app.graph.repository import (
    Direction,
    EdgeKind,
    GraphEdge,
    GraphHit,
    GraphNode,
    GraphWalkResult,
    StepOrder,
    statutory_first,
)
from app.retrieval.ladder import HybridRetriever, ScoredDocument
from app.retrieval.scoped import IndexedDocument, L1Criteria, ScopedRetriever


class CompositeScopedIndex:
    """L0 / L1 over several stores. Exact: the first store with a hit wins (a document held in
    two stores has the same ID and tags in both). Filter: union, newest first, as each part."""

    def __init__(self, parts: Iterable[ScopedRetriever]) -> None:
        self._parts = tuple(parts)

    def exact(self, canonical_id: str, scope: Scope) -> list[IndexedDocument]:
        for p in self._parts:
            if hits := p.exact(canonical_id, scope):
                return hits
        return []

    def prefetch(self, canonical_ids: Iterable[str], scope: Scope) -> None:
        """Ask the later stores, in one batch each, about the records the earlier ones do not
        hold (request memo, `request_memo.MemoScopedIndex`); `exact` then reads the memo."""
        todo = list(dict.fromkeys(canonical_ids))
        for p in self._parts:
            fetch = getattr(p, "prefetch", None)
            if fetch is not None and todo:
                fetch(todo, scope)
            todo = [c for c in todo if not p.exact(c, scope)]

    def filter(self, criteria: L1Criteria, scope: Scope) -> list[IndexedDocument]:
        seen: dict[str, IndexedDocument] = {}
        for p in self._parts:
            for d in p.filter(criteria, scope):
                seen.setdefault(d.canonical_id, d)
        return sorted(
            seen.values(), key=lambda d: (d.issue_date or dt.date.min, d.canonical_id), reverse=True
        )


class CompositeHybrid:
    """L2 over stores whose scores are on different scales (BM25 keyword vs 0-1 hybrid).
    Each part's score is divided by that part's OWN evidence threshold and multiplied by the
    ladder's threshold, so a hit passes the ladder's test exactly when it passes its own store's.
    A part with no calibrated threshold (`None`) is kept just below the ladder's threshold: its
    hits are listed but can never by themselves end the ladder at L2."""

    def __init__(self, parts: Iterable[tuple[HybridRetriever, float | None]], ladder_min: float):
        self._parts = tuple(parts)
        self._min = ladder_min

    def search(self, query: str, scope: Scope, top_k: int) -> list[ScoredDocument]:
        best: dict[str, ScoredDocument] = {}
        for part, own_min in self._parts:
            for s in part.search(query, scope, top_k):
                if own_min:
                    score = s.score / own_min * self._min
                else:
                    score = min(s.score, 1.0) * self._min * 0.99
                hit = ScoredDocument(doc=s.doc, score=round(score, 6))
                if s.doc.canonical_id not in best or best[s.doc.canonical_id].score < hit.score:
                    best[s.doc.canonical_id] = hit
        out = sorted(best.values(), key=lambda s: (-s.score, s.doc.canonical_id))
        return out[:top_k]


class GraphReader(Protocol):
    """A graph store as a walk reads it."""

    def node(self, cid: str) -> GraphNode | None: ...

    def edges_from(self, cid: str) -> tuple[GraphEdge, ...]: ...

    def edges_to(self, cid: str) -> tuple[GraphEdge, ...]: ...


class CompositeGraph:
    """L3 over several graph stores as ONE graph: a walk may step from an e-Office paper (memory)
    to a public order and on to the order that replaced it (Cloud SQL). Same breadth-first walk
    as the reference (`InMemoryGraphRepository.walk`); the scope is applied to every node before
    it is returned or expanded."""

    def __init__(self, parts: Iterable[GraphReader]) -> None:
        self._parts = tuple(parts)

    def node(self, cid: str) -> GraphNode | None:
        return next((n for p in self._parts if (n := p.node(cid)) is not None), None)

    def prefetch(self, ids: Iterable[str]) -> None:
        """Warm the stores that can read in batches (cloud, per request); results unchanged."""
        wanted = list(dict.fromkeys(ids))
        for p in self._parts:
            if wanted and (warm := getattr(p, "prefetch", None)) is not None:
                warm(wanted)

    def _steps(self, cid: str, direction: Direction) -> list[tuple[GraphEdge, str]]:
        """Out-edges by (kind, target), then in-edges by (kind, source), as the reference;
        an edge held in two stores counts once."""
        outs: dict[tuple[str, str], GraphEdge] = {}
        ins: dict[tuple[str, str], GraphEdge] = {}
        for p in self._parts:
            if direction in (Direction.OUT, Direction.BOTH):
                for e in p.edges_from(cid):
                    outs.setdefault((e.kind.value, e.target), e)
            if direction in (Direction.IN, Direction.BOTH):
                for e in p.edges_to(cid):
                    ins.setdefault((e.kind.value, e.source), e)
        return [(outs[k], outs[k].target) for k in sorted(outs)] + [
            (ins[k], ins[k].source) for k in sorted(ins)
        ]

    def walk(
        self,
        seeds: Iterable[str],
        scope: Scope,
        *,
        kinds: frozenset[EdgeKind],
        direction: Direction,
        max_hops: int,
        include_unconfirmed: bool = False,
        max_nodes: int | None = None,
        max_edges: int | None = None,
    ) -> GraphWalkResult:
        """The store's own order first; only when a limit cuts the walk is it walked again with
        legally binding relations first (ADR-0063 addendum), so an uncut walk is unchanged."""
        start = tuple(seeds)
        first = self._walk(start, scope, kinds=kinds, direction=direction, max_hops=max_hops,
                           include_unconfirmed=include_unconfirmed, max_nodes=max_nodes,
                           max_edges=max_edges)  # fmt: skip
        if not getattr(first, "truncated", False):
            return first
        return self._walk(start, scope, kinds=kinds, direction=direction, max_hops=max_hops,
                          include_unconfirmed=include_unconfirmed, max_nodes=max_nodes,
                          max_edges=max_edges, order=statutory_first)  # fmt: skip

    def _walk(
        self,
        seeds: Iterable[str],
        scope: Scope,
        *,
        kinds: frozenset[EdgeKind],
        direction: Direction,
        max_hops: int,
        include_unconfirmed: bool = False,
        max_nodes: int | None = None,
        max_edges: int | None = None,
        order: StepOrder = list,
    ) -> GraphWalkResult:
        if max_hops < 1:
            raise ValueError("max_hops must be >= 1")

        def visible(cid: str) -> bool:
            n = self.node(cid)
            return n is not None and scope.admits(n.tags)

        self.prefetch(seeds)
        start = [s for s in dict.fromkeys(seeds) if visible(s)]
        seen = set(start)
        queue: deque[tuple[str, tuple[str, ...]]] = deque((s, (s,)) for s in start)
        warm: set[str] = set(start)
        hits: list[GraphHit] = []
        truncated = False
        truncation_reason: str | None = None
        edges_traversed = 0

        while queue:
            cid, path = queue.popleft()
            if len(path) - 1 >= max_hops:
                continue
            if cid not in warm:  # the next breadth-first level, read in one go
                level = [c for c, p in queue if len(p) - 1 < max_hops and c not in warm]
                self.prefetch([cid, *level])
                warm.update([cid, *level])
            for edge, nxt in order(self._steps(cid, direction)):
                if edge.kind not in kinds or (not edge.confirmed and not include_unconfirmed):
                    continue
                if not visible(nxt):
                    continue  # out of scope: never visited, returned or counted
                edges_traversed += 1  # in scope only: no hidden-record signal
                if max_edges is not None and edges_traversed > max_edges:
                    truncated = True
                    truncation_reason = f"max_edges_exceeded ({max_edges})"
                    break
                if nxt in seen:
                    continue
                if max_nodes is not None and len(hits) >= max_nodes:
                    truncated = True
                    truncation_reason = f"max_nodes_exceeded ({max_nodes})"
                    break
                seen.add(nxt)
                hits.append(
                    GraphHit(canonical_id=nxt, hops=len(path), via=edge.kind, path=(*path, nxt))
                )
                queue.append((nxt, (*path, nxt)))
            if truncated:
                break
        return GraphWalkResult(
            hits,
            truncated=truncated,
            total_found=len(hits),
            truncation_reason=truncation_reason,
        )
