"""GraphRepository on PostgreSQL / Cloud SQL (plan §3.6; ADR-0023).

The plan's store-agnostic relation schema (`data/schemas/postgres/0002_graph.sql`) behind the same
interface as the in-memory reference, so agents and the temporal engine do not change. Spanner
Graph stays the planned store; this adapter is the plan's allowed alternative while no Spanner
instance exists.

Scope: `walk` reads one hop at a time and applies `scope.admits` to every node BEFORE it is
returned or expanded, exactly like the reference: a node outside the scope is never visited,
returned or passed through. Any database error propagates (callers fail closed).
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from collections.abc import Iterable, Mapping
from typing import Any

from app.auth.models import DocumentAccessTags, Scope
from app.graph.repository import (
    Direction,
    EdgeKind,
    GraphEdge,
    GraphError,
    GraphHit,
    GraphNode,
    GraphWalkResult,
    StepOrder,
    statutory_first,
)
from app.graph.sync import SyncPlan, check, plan
from app.pg import Pg
from app.retrieval.request_memo import count_query

_NODE_COLS = "canonical_id, department, section, classification, file_no, doc_id"
_PROPS = ("doc_type", "hierarchy_level", "issue_date", "effective_from", "valid_until", "subject")
_DATES = {"issue_date", "effective_from", "valid_until"}


_UPSERT_NODE = (
    "INSERT INTO graph_nodes (canonical_id, department, section, classification, file_no, doc_id, "
    "doc_type, hierarchy_level, issue_date, effective_from, valid_until, subject) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (canonical_id) DO UPDATE SET department = excluded.department, "
    "section = excluded.section, classification = excluded.classification, "
    "file_no = excluded.file_no, doc_id = excluded.doc_id, "
    "doc_type = COALESCE(excluded.doc_type, graph_nodes.doc_type), "
    "hierarchy_level = COALESCE(excluded.hierarchy_level, graph_nodes.hierarchy_level), "
    "issue_date = COALESCE(excluded.issue_date, graph_nodes.issue_date), "
    "effective_from = COALESCE(excluded.effective_from, graph_nodes.effective_from), "
    "valid_until = COALESCE(excluded.valid_until, graph_nodes.valid_until), "
    "subject = COALESCE(excluded.subject, graph_nodes.subject)"
)
_ENDS = "SELECT count(*) FROM graph_nodes WHERE canonical_id IN (%s, %s)"
_UPSERT_EDGE = (
    "INSERT INTO graph_edges (source, kind, target, confirmed) VALUES (%s, %s, %s, %s) "
    "ON CONFLICT (source, kind, target) DO UPDATE SET confirmed = excluded.confirmed"
)
_EDGE = "SELECT source, kind, target, confirmed FROM graph_edges"
_EDGES = {
    "all": _EDGE + " ORDER BY source, kind, target",
    "to": _EDGE + " WHERE target = %s ORDER BY source, kind, target",
    "from": _EDGE + " WHERE source = %s ORDER BY source, kind, target",
}


def _marks(n: int) -> str:
    return ", ".join(["%s"] * n)


def _date(v: Any) -> dt.date | None:
    return dt.date.fromisoformat(v) if isinstance(v, str) and v else v


class PostgresGraphRepository:
    def __init__(self, pg: Pg) -> None:
        self._pg = pg

    # ---- writes ---------------------------------------------------------------------------

    def upsert_node(self, node: GraphNode, props: Mapping[str, Any] | None = None) -> None:
        """`props` (optional): doc_type, hierarchy_level, issue_date, effective_from,
        valid_until, subject — descriptive only, never used for access."""
        p = props or {}
        vals = [_date(p.get(k)) if k in _DATES else p.get(k) for k in _PROPS]
        t = node.tags
        with self._pg.tx() as cur:
            cur.execute(
                _UPSERT_NODE,
                (
                    node.canonical_id,
                    t.department,
                    t.section,
                    t.classification,
                    t.file_no,
                    t.doc_id,
                    *vals,
                ),
            )

    def upsert_edge(self, edge: GraphEdge) -> None:
        with self._pg.tx() as cur:
            cur.execute(_ENDS, (edge.source, edge.target))
            if cur.fetchone()[0] != len({edge.source, edge.target}):
                raise GraphError("edge endpoints must be known nodes")
            cur.execute(_UPSERT_EDGE, (edge.source, edge.kind.value, edge.target, edge.confirmed))

    # ---- reads ----------------------------------------------------------------------------

    def _nodes(self, ids: Iterable[str]) -> dict[str, GraphNode]:
        wanted = list(dict.fromkeys(ids))
        if not wanted:
            return {}
        count_query("cloudsql-graph")
        with self._pg.tx() as cur:
            cur.execute(  # placeholders only; values are bound
                f"SELECT {_NODE_COLS} FROM graph_nodes WHERE canonical_id IN "  # noqa: S608
                f"({_marks(len(wanted))})",
                tuple(wanted),
            )
            rows = cur.fetchall()
        return {
            r[0]: GraphNode(
                canonical_id=r[0],
                tags=DocumentAccessTags(
                    doc_id=r[5], department=r[1], section=r[2], classification=r[3], file_no=r[4]
                ),
            )
            for r in rows
        }

    def node(self, cid: str) -> GraphNode | None:
        return self._nodes([cid]).get(cid)

    def node_ids(self) -> tuple[str, ...]:
        with self._pg.tx() as cur:
            cur.execute("SELECT canonical_id FROM graph_nodes ORDER BY canonical_id")
            return tuple(r[0] for r in cur.fetchall())

    def _edges(self, which: str, params: tuple[Any, ...] = ()) -> list[GraphEdge]:
        count_query("cloudsql-graph")
        with self._pg.tx() as cur:
            cur.execute(_EDGES[which], params)
            rows = cur.fetchall()
        return [
            GraphEdge(source=r[0], kind=EdgeKind(r[1]), target=r[2], confirmed=bool(r[3]))
            for r in rows
        ]

    def edges(self) -> list[GraphEdge]:
        return self._edges("all")

    def edges_to(self, cid: str) -> tuple[GraphEdge, ...]:
        return tuple(sorted(self._edges("to", (cid,)), key=lambda e: (e.kind, e.source)))

    def edges_from(self, cid: str) -> tuple[GraphEdge, ...]:
        return tuple(sorted(self._edges("from", (cid,)), key=lambda e: (e.kind, e.target)))

    def _steps(self, cid: str, direction: Direction) -> list[tuple[GraphEdge, str]]:
        out: list[tuple[GraphEdge, str]] = []
        if direction in (Direction.OUT, Direction.BOTH):
            out += [(e, e.target) for e in self.edges_from(cid)]
        if direction in (Direction.IN, Direction.BOTH):
            out += [(e, e.source) for e in self.edges_to(cid)]
        return out

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
        """Scope-constrained breadth-first walk; same order and results as the reference."""
        if max_hops < 1:
            raise ValueError("max_hops must be >= 1")
        ordered = list(dict.fromkeys(seeds))
        known = self._nodes(ordered)
        start = [s for s in ordered if s in known and scope.admits(known[s].tags)]
        seen = set(start)
        queue: deque[tuple[str, tuple[str, ...]]] = deque((s, (s,)) for s in start)
        hits: list[GraphHit] = []
        truncated = False
        truncation_reason: str | None = None
        edges_traversed = 0

        while queue:
            cid, path = queue.popleft()
            if len(path) - 1 >= max_hops:
                continue
            steps = order(
                (e, nxt)
                for e, nxt in self._steps(cid, direction)
                if e.kind in kinds and (e.confirmed or include_unconfirmed)
            )
            tags = self._nodes(nxt for _, nxt in steps)
            for edge, nxt in steps:
                if nxt not in tags or not scope.admits(tags[nxt].tags):
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

    # ---- batch load (the graph build job) ---------------------------------------------------

    def load(
        self,
        nodes: Iterable[GraphNode],
        edges: Iterable[GraphEdge],
        props: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> tuple[int, int]:
        """Copy a built graph in. Safe to run again: rows are upserted, nothing is deleted."""
        n = e = 0
        for node in nodes:
            self.upsert_node(node, (props or {}).get(node.canonical_id))
            n += 1
        for edge in edges:
            self.upsert_edge(edge)
            e += 1
        return n, e

    def load_rows(
        self, nodes: Iterable[Mapping[str, Any]], edges: Iterable[Mapping[str, Any]]
    ) -> tuple[int, int]:
        """Load the build job's files (nodes.jsonl / edges.jsonl rows). A node row without its
        access tags is refused: a node must never enter the store untagged."""
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
        """Make the tables equal the build (ADR-0055), in ONE transaction: links and nodes the
        build no longer produces are deleted, the rest upserted. Guarded (app.graph.sync); a dry
        run changes nothing. Any error rolls everything back."""
        rows = list(nodes)
        built, links = graph_from_rows(rows, edges)
        props = {str(r["id"]): r for r in rows}
        with self._pg.tx() as cur:
            cur.execute("SELECT canonical_id FROM graph_nodes")
            held_nodes = [r[0] for r in cur.fetchall()]
            cur.execute("SELECT source, kind, target, confirmed FROM graph_edges")
            held_edges = {(r[0], r[1], r[2]): bool(r[3]) for r in cur.fetchall()}
            p = plan(held_nodes, held_edges, built, links)
            check(p, len(built), max_delete_share=max_delete_share,
                  allow_large_delete=allow_large_delete)  # fmt: skip
            if dry_run:
                return p
            for s, k, t in sorted(p.delete_edges):
                cur.execute(
                    "DELETE FROM graph_edges WHERE source = %s AND kind = %s AND target = %s",
                    (s, k, t),
                )
            for node in built:
                pr = props.get(node.canonical_id) or {}
                vals = [_date(pr.get(k)) if k in _DATES else pr.get(k) for k in _PROPS]
                tg = node.tags
                cur.execute(
                    _UPSERT_NODE,
                    (node.canonical_id, tg.department, tg.section, tg.classification,
                     tg.file_no, tg.doc_id, *vals),
                )  # fmt: skip
            for e in links:
                cur.execute(_UPSERT_EDGE, (e.source, e.kind.value, e.target, e.confirmed))
            for cid in sorted(p.delete_nodes):  # their links are gone: none of them is built
                cur.execute("DELETE FROM graph_nodes WHERE canonical_id = %s", (cid,))
        return p

    def counts(self) -> tuple[int, int]:
        with self._pg.tx() as cur:
            cur.execute(
                "SELECT (SELECT count(*) FROM graph_nodes), (SELECT count(*) FROM graph_edges)"
            )
            row = cur.fetchone()
        return int(row[0]), int(row[1])


def graph_from_rows(
    nodes: Iterable[Mapping[str, Any]], edges: Iterable[Mapping[str, Any]]
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """The build job's rows as graph objects, for any store. A node without its access tags is
    refused: a node must never enter a store untagged."""
    built = []
    for r in nodes:
        if not (r.get("department") and r.get("classification")):
            raise GraphError(f"node {r.get('id')!r} has no access tags")
        built.append(
            GraphNode(
                canonical_id=r["id"],
                tags=DocumentAccessTags(
                    doc_id=r["id"],
                    department=r["department"],
                    section=r.get("section") or None,
                    classification=r["classification"],
                    file_no=r.get("file_no") or None,
                ),
            )
        )
    links = [
        GraphEdge(
            source=e["from"],
            kind=EdgeKind(e["relation"]),
            target=e["to"],
            confirmed=bool(e["confirmed"]),
        )
        for e in edges
    ]
    return built, links
