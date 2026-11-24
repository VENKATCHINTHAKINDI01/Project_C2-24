"""Cloud reads in batches (24 Nov 2026): a draft on the live service waited ~5.5 min on dozens of
one-ID round trips. Batched reads only warm the per-request memo; every result is unchanged."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from app.graph.repository import Direction, EdgeKind, GraphEdge, InMemoryGraphRepository
from app.graph.spanner import SpannerGraphRepository
from app.retrieval.composite import CompositeGraph
from app.retrieval.request_memo import MemoGraph, MemoScopedIndex, queries, request_memo
from tests.unit.test_graph_bounds import _postgres
from tests.unit.test_graph_postgres import node, scope
from tests.unit.test_graph_spanner import SqlitePort

ALL = frozenset(EdgeKind)


def _chain(g: Any, n: int) -> None:
    """O0 ← O1 ← … (each amends the one before), plus a SECRET order citing O0."""
    for i in range(n):
        g.upsert_node(node(f"O{i}"))
    g.upsert_node(node("S", cls="SECRET"))
    for i in range(1, n):
        g.upsert_edge(GraphEdge(source=f"O{i}", kind=EdgeKind.AMENDS, target=f"O{i - 1}"))
    g.upsert_edge(GraphEdge(source="S", kind=EdgeKind.CITES, target="O0"))


def _walk(g: Any, rank: int = 1) -> list[tuple[str, int, str]]:
    hits = g.walk(["O0"], scope("FIN", rank=rank), kinds=ALL, direction=Direction.BOTH, max_hops=3)
    return [(h.canonical_id, h.hops, h.via.value) for h in hits]


@pytest.mark.parametrize("store", ["spanner", "postgres"])
def test_batched_edges_keep_each_stores_order(store: str) -> None:
    sp: Any = SpannerGraphRepository(SqlitePort()) if store == "spanner" else _postgres()
    _chain(sp, 4)
    out, into = sp.edges_many(["O0", "O1", "missing"])
    assert out["O1"] == sp.edges_from("O1") and into["O0"] == sp.edges_to("O0")
    assert out["missing"] == () and into["missing"] == ()
    assert sp.nodes_many(["O0", "missing"]).keys() == {"O0"}


def test_a_walk_reads_level_by_level_and_returns_the_same() -> None:
    port = SqlitePort()
    sp = SpannerGraphRepository(port)
    _chain(sp, 6)
    reference = InMemoryGraphRepository()
    _chain(reference, 6)
    graph = CompositeGraph((InMemoryGraphRepository(), MemoGraph(sp)))
    for rank in (1, 2):  # the SECRET neighbour: hidden for rank 1, seen for rank 2
        with request_memo():
            port.reads.clear()
            got = _walk(graph, rank)
            batched = len(port.reads)
        port.reads.clear()
        unbatched = _walk(CompositeGraph((InMemoryGraphRepository(), sp)), rank)
        assert got == unbatched == _walk(reference, rank)
        assert batched <= 8 < len(port.reads)  # a few queries per level, not three per order


def test_a_record_not_found_in_a_batch_is_not_read_again() -> None:
    calls: list[str] = []

    class Index:
        def exact(self, cid: str, sc: Any) -> list[Any]:
            calls.append(cid)
            return []

        def exact_many(self, cids: list[str], sc: Any) -> dict[str, list[Any]]:
            calls.append("many")
            return {}

        def filter(self, c: Any, sc: Any) -> list[Any]:
            return []

    idx = MemoScopedIndex(Index())
    sc = scope("FIN")
    with request_memo():
        idx.prefetch(["A", "B"], sc)
        assert idx.exact("A", sc) == [] and idx.exact("B", sc) == []
    assert calls == ["many"]


def test_the_per_request_query_line_reaches_the_log_with_times() -> None:
    from app.main import app_logging
    from app.retrieval.request_memo import QUERIES, SECONDS, timed_query

    app_logging()
    assert logging.getLogger("app.retrieval.request_memo").isEnabledFor(logging.INFO)
    with request_memo() as memo:
        with timed_query("bigquery"):
            pass
        with timed_query("bigquery"):
            pass
        assert memo[QUERIES] == {"bigquery": 2} == queries()
        assert set(memo[SECONDS]) == {"bigquery"} and memo[SECONDS]["bigquery"] >= 0


def test_profiler_logs_listed_paths_only_and_only_code_locations(caplog: Any) -> None:
    import asyncio

    from app.tracking.profiler import ProfileMiddleware

    async def route(scope: Any, receive: Any, send: Any) -> None:
        await asyncio.sleep(0.12)

    mw = ProfileMiddleware(route, frozenset({"/assist/draft/prepare"}))
    with caplog.at_level(logging.INFO, logger="app.tracking.profiler"):
        asyncio.run(mw({"type": "http", "path": "/assist/ask"}, None, None))
        assert "profile" not in caplog.text
        asyncio.run(mw({"type": "http", "path": "/assist/draft/prepare"}, None, None))
    assert "profile /assist/draft/prepare" in caplog.text
    assert "by step" in caplog.text and "where it waited" in caplog.text


def test_profiler_is_off_unless_configured() -> None:
    from app.tracking.profiler import ProfileMiddleware
    from tests.unit.test_sandbox_api import APP

    assert not any(m.cls is ProfileMiddleware for m in APP.user_middleware)
