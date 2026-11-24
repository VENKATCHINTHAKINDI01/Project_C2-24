"""Graph walk limits never depend on records the officer cannot see (ADR-0063 addendum,
24 Nov 2026; CLAUDE.md §4.7). The edge limit counts in-scope steps only, in every store: an
officer whose order has many hidden neighbours gets exactly the walk, and the same "limit
reached" answer, as if those neighbours did not exist."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.graph.postgres import PostgresGraphRepository
from app.graph.repository import Direction, EdgeKind, GraphEdge, InMemoryGraphRepository
from app.graph.spanner import SpannerGraphRepository
from app.pg import Pg
from app.retrieval.composite import CompositeGraph
from tests.unit.test_graph_postgres import _Conn, node, scope
from tests.unit.test_graph_spanner import SqlitePort

ALL = frozenset(EdgeKind)


def _in_memory() -> Any:
    return InMemoryGraphRepository()


def _postgres() -> Any:
    conn = _Conn()
    return PostgresGraphRepository(Pg(lambda: conn))


def _spanner() -> Any:
    return SpannerGraphRepository(SqlitePort())


STORES: dict[str, Callable[[], Any]] = {
    "memory": _in_memory,
    "postgres": _postgres,
    "spanner": _spanner,
}


def _load(g: Any, hidden: int) -> None:
    """Seed A amends B (public); A also cites `hidden` SECRET orders."""
    g.upsert_node(node("A"))
    g.upsert_node(node("B"))
    g.upsert_edge(GraphEdge(source="B", kind=EdgeKind.AMENDS, target="A"))
    for i in range(hidden):
        g.upsert_node(node(f"S{i}", cls="SECRET"))
        g.upsert_edge(GraphEdge(source=f"S{i}", kind=EdgeKind.CITES, target="A"))


def _walk(g: Any, rank: int, max_edges: int) -> Any:
    return g.walk(
        ["A"], scope("FIN", rank=rank), kinds=ALL, direction=Direction.IN, max_hops=2,
        max_edges=max_edges,
    )  # fmt: skip


@pytest.mark.parametrize("store", sorted(STORES))
@pytest.mark.parametrize("composite", [False, True])
def test_hidden_neighbours_never_trigger_or_shape_a_limit(store: str, composite: bool) -> None:
    with_hidden, without = STORES[store](), STORES[store]()
    _load(with_hidden, hidden=7)
    _load(without, hidden=0)
    if composite:
        with_hidden, without = CompositeGraph((with_hidden,)), CompositeGraph((without,))
    a = _walk(with_hidden, rank=1, max_edges=2)  # cannot see SECRET
    b = _walk(without, rank=1, max_edges=2)
    assert [h.canonical_id for h in a] == [h.canonical_id for h in b] == ["B"]
    assert (a.truncated, a.truncation_reason) == (b.truncated, b.truncation_reason) == (False, None)
    # an officer who can see them is told the limit was reached (non-silent)
    top = _walk(with_hidden, rank=2, max_edges=2)
    assert top.truncated and top.truncation_reason == "max_edges_exceeded (2)"
    assert len(top) == 2


def test_a_walk_cut_by_its_limit_is_told_to_the_officer(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-0063 promised a notice; it now reaches the answer (it did not before 24 Nov)."""
    from fastapi.testclient import TestClient

    import app.agents.answer as answer
    from tests.unit.test_sandbox_api import APP, _h

    real = answer.search_authorized_documents  # type: ignore[attr-defined]

    def cut(ctx: Any, slots: Any) -> Any:
        return real(ctx, slots).model_copy(
            update={"truncated": True, "truncation_reason": "max_nodes_exceeded (50)"}
        )

    q = {"question": "What are the transfer guidelines for spouse cases?"}
    with TestClient(APP) as c:
        plain = c.post("/assist/ask", json=q, headers=_h("U01")).json()
        monkeypatch.setattr(answer, "search_authorized_documents", cut)
        told = c.post("/assist/ask", json=q, headers=_h("U01")).json()
    assert answer.DEGRADED["L3-limit"] not in plain.get("notices", [])
    assert answer.DEGRADED["L3-limit"] in told["notices"]
