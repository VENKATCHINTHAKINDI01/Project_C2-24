"""GraphRepository on Spanner Graph (plan §3.6, §5.2; ADR-0048).

The plan's graph store, behind the same interface as the in-memory reference and Cloud SQL
(ADR-0023), so agents, the ladder and the temporal engine do not change. Schema:
`data/schemas/spanner/0001_graph.ddl` (the same two tables, plus a property graph over them).

Scope: the walk is breadth-first, ONE HOP AT A TIME, in fixed parameterised SQL templates, and
`scope.admits` is applied to every node in the application BEFORE it is returned or expanded —
the same rule, in the same code shape, as the reference: a node outside the scope is never
visited, returned or passed through. No GQL path query does the walk: the access rule would have
to be written a second time in the query language, and two copies of an access rule drift.
Each hop is two queries for the whole frontier (its edges, then its neighbours' tags), not two per
node. Any Spanner error propagates (callers fail closed).

The client is reached through a small port (`SpannerPort`) so the adapter is tested here without
Spanner; `CloudSpannerPort` wraps google-cloud-spanner on GCP.
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

from app.auth.models import DocumentAccessTags, Scope
from app.graph.postgres import graph_from_rows
from app.graph.repository import (
    Direction,
    EdgeKind,
    GraphEdge,
    GraphError,
    GraphHit,
    GraphNode,
    GraphWalkResult,
)
from app.graph.sync import SyncPlan, check, plan

_NODE = (
    "SELECT canonical_id, department, section, classification, file_no, doc_id "
    "FROM graph_nodes WHERE canonical_id IN UNNEST(@ids)"
)
_EDGE = "SELECT source, kind, target, confirmed FROM graph_edges"
_EDGES = {
    "all": _EDGE + " ORDER BY source, kind, target",
    "from": _EDGE + " WHERE source IN UNNEST(@ids) ORDER BY source, kind, target",
    "to": _EDGE + " WHERE target IN UNNEST(@ids) ORDER BY target, kind, source",
}
_IDS = "SELECT canonical_id FROM graph_nodes ORDER BY canonical_id"
_COUNTS = "SELECT (SELECT COUNT(*) FROM graph_nodes), (SELECT COUNT(*) FROM graph_edges)"
_TAGS = ("canonical_id", "department", "section", "classification", "file_no", "doc_id")
_PROPS = ("doc_type", "hierarchy_level", "issue_date", "effective_from", "valid_until", "subject")
_DATES = {"issue_date", "effective_from", "valid_until"}
_BATCH = 500  # rows per mutation batch (well under Spanner's per-commit mutation limit)


class SpannerPort(Protocol):
    """What the adapter needs from Spanner: read-only queries with bound parameters (a string
    list binds as ARRAY<STRING>), and insert-or-update of whole rows."""

    def query(self, sql: str, params: Mapping[str, Any] | None = None) -> list[tuple[Any, ...]]: ...

    def upsert(self, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> None: ...

    def delete(self, table: str, keys: Sequence[Sequence[Any]]) -> None: ...


class CloudSpannerPort:
    """google-cloud-spanner, with the service's own identity (no keys)."""

    def __init__(self, project: str, instance: str, database: str) -> None:
        from google.cloud import spanner

        self._types: Any = spanner.param_types
        # the client's own telemetry export is off: it needs Monitoring write access we do not
        # grant, and failed exports only add noise to the logs (seen on the first load, 18 Nov)
        client: Any = spanner.Client(project=project, disable_builtin_metrics=True)
        self._db: Any = client.instance(instance).database(database)

    def query(self, sql: str, params: Mapping[str, Any] | None = None) -> list[tuple[Any, ...]]:
        p = dict(params or {})
        types = {
            k: self._types.Array(self._types.STRING) if isinstance(v, list) else self._types.STRING
            for k, v in p.items()
        }
        with self._db.snapshot() as snap:
            return [
                tuple(r) for r in snap.execute_sql(sql, params=p or None, param_types=types or None)
            ]

    def upsert(self, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
        with self._db.batch() as batch:
            batch.insert_or_update(
                table=table, columns=tuple(columns), values=[list(r) for r in rows]
            )

    def delete(self, table: str, keys: Sequence[Sequence[Any]]) -> None:
        from google.cloud import spanner

        keyset: Any = spanner.KeySet  # untyped library class
        with self._db.batch() as batch:
            batch.delete(table, keyset(keys=[list(k) for k in keys]))


def _date(v: Any) -> dt.date | None:
    return dt.date.fromisoformat(v) if isinstance(v, str) and v else v


class SpannerGraphRepository:
    def __init__(self, port: SpannerPort) -> None:
        self._db = port

    # ---- writes ---------------------------------------------------------------------------

    def upsert_node(self, node: GraphNode, props: Mapping[str, Any] | None = None) -> None:
        """`props` (optional, descriptive only, never used for access): a property not given
        keeps its stored value, as on Cloud SQL."""
        self._upsert_nodes([(node, props or {})])

    def _upsert_nodes(self, items: Sequence[tuple[GraphNode, Mapping[str, Any]]]) -> None:
        # rows are grouped by which properties they carry, so a missing one is never overwritten
        groups: dict[tuple[str, ...], list[list[Any]]] = {}
        for node, p in items:
            t = node.tags
            have = tuple(k for k in _PROPS if p.get(k) is not None)
            row: list[Any] = [
                node.canonical_id,
                t.department,
                t.section,
                t.classification,
                t.file_no,
                t.doc_id,
            ]
            row += [_date(p[k]) if k in _DATES else p[k] for k in have]
            groups.setdefault(have, []).append(row)
        for have, rows in groups.items():
            for i in range(0, len(rows), _BATCH):
                self._db.upsert("graph_nodes", (*_TAGS, *have), rows[i : i + _BATCH])

    def upsert_edge(self, edge: GraphEdge) -> None:
        self._upsert_edges([edge])

    def _upsert_edges(self, edges: Sequence[GraphEdge]) -> None:
        ends = {x for e in edges for x in (e.source, e.target)}
        if len(self._nodes(ends)) != len(ends):  # the schema's foreign keys refuse it too
            raise GraphError("edge endpoints must be known nodes")
        rows = [[e.source, e.kind.value, e.target, e.confirmed] for e in edges]
        for i in range(0, len(rows), _BATCH):
            self._db.upsert(
                "graph_edges", ("source", "kind", "target", "confirmed"), rows[i : i + _BATCH]
            )

    # ---- reads ----------------------------------------------------------------------------

    def _nodes(self, ids: Iterable[str]) -> dict[str, GraphNode]:
        wanted = list(dict.fromkeys(ids))
        out: dict[str, GraphNode] = {}
        for i in range(0, len(wanted), _BATCH):
            for r in self._db.query(_NODE, {"ids": wanted[i : i + _BATCH]}):
                out[r[0]] = GraphNode(
                    canonical_id=r[0],
                    tags=DocumentAccessTags(
                        doc_id=r[5],
                        department=r[1],
                        section=r[2],
                        classification=r[3],
                        file_no=r[4],
                    ),
                )
        return out

    def node(self, cid: str) -> GraphNode | None:
        return self._nodes([cid]).get(cid)

    def node_ids(self) -> tuple[str, ...]:
        return tuple(r[0] for r in self._db.query(_IDS))

    def _edges(self, which: str, ids: Sequence[str] = ()) -> list[GraphEdge]:
        rows: list[tuple[Any, ...]] = []
        if which == "all":
            rows = self._db.query(_EDGES["all"])
        else:
            for i in range(0, len(ids), _BATCH):
                rows += self._db.query(_EDGES[which], {"ids": list(ids[i : i + _BATCH])})
        return [
            GraphEdge(source=r[0], kind=EdgeKind(r[1]), target=r[2], confirmed=bool(r[3]))
            for r in rows
        ]

    def edges(self) -> list[GraphEdge]:
        return self._edges("all")

    def edges_to(self, cid: str) -> tuple[GraphEdge, ...]:
        return tuple(sorted(self._edges("to", [cid]), key=lambda e: (e.kind, e.source)))

    def edges_from(self, cid: str) -> tuple[GraphEdge, ...]:
        return tuple(sorted(self._edges("from", [cid]), key=lambda e: (e.kind, e.target)))

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
        """Scope-constrained breadth-first walk; same order and results as the reference.

        Hop by hop: the whole frontier's edges in one read, its neighbours' tags in another, then
        the frontier is taken in queue order exactly as the reference takes it one node at a time
        (out-edges by (kind, target), then in-edges by (kind, source))."""
        if max_hops < 1:
            raise ValueError("max_hops must be >= 1")
        ordered = list(dict.fromkeys(seeds))
        known = self._nodes(ordered)
        start = [s for s in ordered if s in known and scope.admits(known[s].tags)]
        seen = set(start)
        frontier: deque[tuple[str, tuple[str, ...]]] = deque((s, (s,)) for s in start)
        hits: list[GraphHit] = []
        truncated = False
        truncation_reason: str | None = None
        edges_traversed = 0

        while frontier:
            layer = [x for x in frontier if len(x[1]) - 1 < max_hops]
            frontier = deque()
            if not layer:
                break
            ids = [cid for cid, _ in layer]
            out: dict[str, list[GraphEdge]] = {}
            into: dict[str, list[GraphEdge]] = {}
            if direction in (Direction.OUT, Direction.BOTH):
                for e in self._edges("from", ids):
                    out.setdefault(e.source, []).append(e)
            if direction in (Direction.IN, Direction.BOTH):
                for e in self._edges("to", ids):
                    into.setdefault(e.target, []).append(e)

            def steps(
                cid: str,
                out: dict[str, list[GraphEdge]] = out,
                into: dict[str, list[GraphEdge]] = into,
            ) -> list[tuple[GraphEdge, str]]:
                s = [
                    (e, e.target)
                    for e in sorted(out.get(cid, ()), key=lambda e: (e.kind, e.target))
                ]
                s += [
                    (e, e.source)
                    for e in sorted(into.get(cid, ()), key=lambda e: (e.kind, e.source))
                ]
                return [
                    (e, n) for e, n in s if e.kind in kinds and (e.confirmed or include_unconfirmed)
                ]

            per = {cid: steps(cid) for cid in ids}
            tags = self._nodes(n for st in per.values() for _, n in st)
            for cid, path in layer:
                for edge, nxt in per[cid]:
                    edges_traversed += 1
                    if max_edges is not None and edges_traversed > max_edges:
                        truncated = True
                        truncation_reason = f"max_edges_exceeded ({max_edges})"
                        break
                    if nxt in seen or nxt not in tags or not scope.admits(tags[nxt].tags):
                        continue  # never visit, return or pass through a node outside the scope
                    if max_nodes is not None and len(hits) >= max_nodes:
                        truncated = True
                        truncation_reason = f"max_nodes_exceeded ({max_nodes})"
                        break
                    seen.add(nxt)
                    hits.append(
                        GraphHit(canonical_id=nxt, hops=len(path), via=edge.kind, path=(*path, nxt))
                    )
                    frontier.append((nxt, (*path, nxt)))
                if truncated:
                    break
            if truncated:
                break
        return GraphWalkResult(
            hits,
            truncated=truncated,
            total_found=len(hits),
            truncation_reason=truncation_reason,
        )

    # ---- batch load (from the graph build job's files) ---------------------------------------

    def load(
        self,
        nodes: Iterable[GraphNode],
        edges: Iterable[GraphEdge],
        props: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> tuple[int, int]:
        """Copy a built graph in, nodes first. Safe to run again: rows are upserted, nothing is
        deleted."""
        ns = list(nodes)
        es = list(edges)
        self._upsert_nodes([(n, (props or {}).get(n.canonical_id) or {}) for n in ns])
        if es:
            self._upsert_edges(es)
        return len(ns), len(es)

    def load_rows(
        self, nodes: Iterable[Mapping[str, Any]], edges: Iterable[Mapping[str, Any]]
    ) -> tuple[int, int]:
        rows = list(nodes)
        built, links = graph_from_rows(rows, edges)
        return self.load(built, links, {str(r["id"]): r for r in rows})

    def sync_rows(
        self,
        nodes: Iterable[Mapping[str, Any]],
        edges: Iterable[Mapping[str, Any]],
        *,
        max_delete_share: float = 0.2,
        allow_large_delete: bool = False,
        dry_run: bool = False,
    ) -> SyncPlan:
        """Make Spanner equal the build (ADR-0055). Guarded as on Cloud SQL. Upserts go first and
        deletions last, in batches: between them a reader may still see a stale link (as it did
        before), never a missing one."""
        rows = list(nodes)
        built, links = graph_from_rows(rows, edges)
        held_nodes = [r[0] for r in self._db.query(_IDS)]
        held_edges = {(r[0], r[1], r[2]): bool(r[3]) for r in self._db.query(_EDGES["all"])}
        p = plan(held_nodes, held_edges, built, links)
        check(p, len(built), max_delete_share=max_delete_share,
              allow_large_delete=allow_large_delete)  # fmt: skip
        if dry_run:
            return p
        self.load(built, links, {str(r["id"]): r for r in rows})
        gone = sorted(p.delete_edges)
        for i in range(0, len(gone), _BATCH):
            self._db.delete("graph_edges", gone[i : i + _BATCH])
        drop = sorted(p.delete_nodes)
        for i in range(0, len(drop), _BATCH):
            self._db.delete("graph_nodes", [[c] for c in drop[i : i + _BATCH]])
        return p

    def counts(self) -> tuple[int, int]:
        row = self._db.query(_COUNTS)[0]
        return int(row[0]), int(row[1])
