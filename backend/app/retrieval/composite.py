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
from app.graph.repository import Direction, EdgeKind, GraphEdge, GraphHit, GraphNode
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
    ) -> list[GraphHit]:
        if max_hops < 1:
            raise ValueError("max_hops must be >= 1")

        def visible(cid: str) -> bool:
            n = self.node(cid)
            return n is not None and scope.admits(n.tags)

        start = [s for s in dict.fromkeys(seeds) if visible(s)]
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
                if nxt in seen or not visible(nxt):
                    continue  # never visit, return or pass through a node outside the scope
                seen.add(nxt)
                hits.append(
                    GraphHit(canonical_id=nxt, hops=len(path), via=edge.kind, path=(*path, nxt))
                )
                queue.append((nxt, (*path, nxt)))
        return hits
