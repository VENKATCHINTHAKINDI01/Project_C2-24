"""PostgresGraphRepository (ADR-0023): same answers as the in-memory reference, and the scope is
applied to every node of a walk.

The SQL runs here against SQLite through a thin `%s` → `?` shim (the statements are portable), and
against a real PostgreSQL when `C2_TEST_PG_DSN` points at a throwaway database.
"""

from __future__ import annotations

import datetime as dt
import os
import random
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.auth.models import DocumentAccessTags, Scope
from app.graph.postgres import PostgresGraphRepository
from app.graph.repository import (
    Direction,
    EdgeKind,
    GraphEdge,
    GraphError,
    GraphNode,
    GraphRepository,
    InMemoryGraphRepository,
)
from app.pg import Pg

SCHEMA = Path(__file__).parents[3] / "data" / "schemas" / "postgres" / "0002_graph.sql"
DSN = os.environ.get("C2_TEST_PG_DSN")


class _Cur:
    def __init__(self, cur: sqlite3.Cursor) -> None:
        self._cur = cur

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        vals = tuple(p.isoformat() if isinstance(p, dt.date) else p for p in params)
        self._cur.execute(sql.replace("%s", "?"), vals)

    def fetchone(self) -> Any:
        return self._cur.fetchone()

    def fetchall(self) -> Any:
        return self._cur.fetchall()

    def close(self) -> None:
        self._cur.close()


class _Conn:
    def __init__(self) -> None:
        self._db = sqlite3.connect(":memory:", check_same_thread=False)
        self._db.executescript(
            "CREATE TABLE schema_migrations (version TEXT PRIMARY KEY);" + SCHEMA.read_text("utf-8")
        )

    def cursor(self) -> _Cur:
        return _Cur(self._db.cursor())

    def commit(self) -> None:
        self._db.commit()

    def rollback(self) -> None:
        self._db.rollback()

    def close(self) -> None:
        self._db.close()


@pytest.fixture
def repo() -> PostgresGraphRepository:
    conn = _Conn()
    return PostgresGraphRepository(Pg(lambda: conn))


def node(cid: str, dept: str = "FIN", *, cls: str = "UNCLASSIFIED", file_no: str | None = None):
    return GraphNode(
        canonical_id=cid,
        tags=DocumentAccessTags(
            doc_id=cid, department=dept, section="A", classification=cls, file_no=file_no
        ),
    )


def scope(dept: str, *, wide: bool = True, rank: int = 1, files: tuple[str, ...] = ()) -> Scope:
    return Scope(
        user_id="u",
        policy_version="test",
        classification_ranks={"UNCLASSIFIED": 0, "RESTRICTED": 1, "SECRET": 2},
        public_rank=0,
        department=dept,
        max_rank=rank,
        department_wide=wide,
        sections=frozenset({"A"}),
        file_nos=frozenset(files),
    )


ALL = frozenset(EdgeKind)


def test_is_a_graph_repository(repo: PostgresGraphRepository) -> None:
    assert isinstance(repo, GraphRepository)


def test_edge_needs_known_ends_and_confirming_replaces(repo: PostgresGraphRepository) -> None:
    repo.upsert_node(node("A"))
    with pytest.raises(GraphError):
        repo.upsert_edge(GraphEdge(source="A", kind=EdgeKind.AMENDS, target="B"))
    repo.upsert_node(node("B"))
    repo.upsert_edge(GraphEdge(source="A", kind=EdgeKind.AMENDS, target="B", confirmed=False))
    repo.upsert_edge(GraphEdge(source="A", kind=EdgeKind.AMENDS, target="B", confirmed=True))
    assert repo.edges() == [GraphEdge(source="A", kind=EdgeKind.AMENDS, target="B")]
    assert repo.counts() == (2, 1)


def test_walk_never_passes_through_a_node_outside_the_scope(repo: PostgresGraphRepository) -> None:
    # A (FIN) → X (GAD restricted: outside) → C (FIN): C is reachable only through X
    for n in (node("A"), node("X", "GAD", cls="RESTRICTED"), node("C")):
        repo.upsert_node(n)
    repo.upsert_edge(GraphEdge(source="A", kind=EdgeKind.REFERENCES, target="X"))
    repo.upsert_edge(GraphEdge(source="X", kind=EdgeKind.REFERENCES, target="C"))
    hits = repo.walk(["A"], scope("FIN"), kinds=ALL, direction=Direction.OUT, max_hops=3)
    assert hits == []
    back = repo.walk(["C"], scope("GAD"), kinds=ALL, direction=Direction.IN, max_hops=3)
    assert [h.canonical_id for h in back] == ["X", "A"]  # GAD sees its own paper and public A
    # a seed outside the scope is ignored
    assert repo.walk(["X"], scope("FIN"), kinds=ALL, direction=Direction.BOTH, max_hops=2) == []


def test_unconfirmed_edges_are_skipped_unless_asked(repo: PostgresGraphRepository) -> None:
    repo.upsert_node(node("A"))
    repo.upsert_node(node("B"))
    repo.upsert_edge(GraphEdge(source="A", kind=EdgeKind.SUPERSEDES, target="B", confirmed=False))
    kw: dict[str, Any] = {"kinds": ALL, "direction": Direction.OUT, "max_hops": 1}
    assert repo.walk(["A"], scope("FIN"), **kw) == []
    assert len(repo.walk(["A"], scope("FIN"), include_unconfirmed=True, **kw)) == 1


def test_properties_are_kept_and_not_wiped_by_a_bare_upsert(repo: PostgresGraphRepository) -> None:
    repo.upsert_node(
        node("A"), {"doc_type": "GO_MS", "hierarchy_level": 3, "issue_date": "2024-05-01"}
    )
    repo.upsert_node(node("A", "GAD"))
    with repo._pg.tx() as cur:  # noqa: SLF001
        cur.execute("SELECT department, doc_type, hierarchy_level, issue_date FROM graph_nodes")
        row = cur.fetchone()
    assert (row[0], row[1], row[2], str(row[3])) == ("GAD", "GO_MS", 3, "2024-05-01")


def _random_graph(seed: int) -> tuple[list[GraphNode], list[GraphEdge]]:
    rng = random.Random(seed)  # noqa: S311 — test data
    nodes = [
        node(
            f"N{i:02d}",
            rng.choice(["FIN", "GAD", "ESE"]),
            cls=rng.choice(["UNCLASSIFIED", "RESTRICTED", "SECRET"]),
            file_no=rng.choice([None, None, "F-1", "F-2"]),
        )
        for i in range(30)
    ]
    edges = {
        (a.canonical_id, k, b.canonical_id): GraphEdge(
            source=a.canonical_id, kind=k, target=b.canonical_id, confirmed=rng.random() > 0.2
        )
        for a, k, b in (
            (rng.choice(nodes), rng.choice(list(EdgeKind)), rng.choice(nodes)) for _ in range(90)
        )
    }
    return nodes, list(edges.values())


@pytest.mark.parametrize("seed", range(8))
def test_same_answers_as_the_reference(repo: PostgresGraphRepository, seed: int) -> None:
    nodes, edges = _random_graph(seed)
    ref = InMemoryGraphRepository()
    for n in nodes:
        ref.upsert_node(n)
    for e in edges:
        ref.upsert_edge(e)
    assert repo.load(nodes, edges) == (len(nodes), len(edges))
    assert repo.load(nodes, edges) == (len(nodes), len(edges))  # again: nothing doubles
    assert repo.counts() == (len(nodes), len(edges))
    assert repo.edges() == ref.edges()
    assert set(repo.node_ids()) == set(ref.node_ids())
    rng = random.Random(seed + 100)  # noqa: S311
    for sc in (scope("FIN"), scope("GAD", wide=False, files=("F-1",)), scope("ESE", rank=2)):
        for _ in range(12):
            seeds = [rng.choice(nodes).canonical_id for _ in range(3)]
            kw: dict[str, Any] = {
                "kinds": frozenset(rng.sample(list(EdgeKind), 4)),
                "direction": rng.choice(list(Direction)),
                "max_hops": rng.randint(1, 3),
                "include_unconfirmed": rng.random() > 0.5,
            }
            got = repo.walk(seeds, sc, **kw)
            assert got == ref.walk(seeds, sc, **kw)
            assert all(sc.admits(n.tags) for h in got for c in h.path if (n := ref.node(c)))
    cid = nodes[3].canonical_id
    assert repo.edges_to(cid) == ref.edges_to(cid)
    assert repo.edges_from(cid) == ref.edges_from(cid)
    assert repo.node(cid) == ref.node(cid)


@pytest.mark.skipif(DSN is None, reason="C2_TEST_PG_DSN not set (local Postgres 16)")
def test_on_real_postgres() -> None:
    import psycopg

    conn = psycopg.connect(DSN)
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS c2_graph_test CASCADE; CREATE SCHEMA c2_graph_test")
        cur.execute("SET search_path TO c2_graph_test")
        cur.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)")
        cur.execute(SCHEMA.read_text("utf-8"))
    conn.commit()
    try:
        repo = PostgresGraphRepository(Pg(lambda: conn))
        nodes, edges = _random_graph(1)
        ref = InMemoryGraphRepository()
        for n in nodes:
            ref.upsert_node(n)
        for e in edges:
            ref.upsert_edge(e)
        repo.load(nodes, edges, {nodes[0].canonical_id: {"issue_date": "2024-05-01"}})
        kw: dict[str, Any] = {"kinds": ALL, "direction": Direction.BOTH, "max_hops": 3}
        seeds = [n.canonical_id for n in nodes[:5]]
        assert repo.walk(seeds, scope("GAD"), **kw) == ref.walk(seeds, scope("GAD"), **kw)
        assert repo.edges() == ref.edges()
    finally:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA c2_graph_test CASCADE")
        conn.commit()
        conn.close()


def test_job_files_load_and_an_untagged_node_is_refused(repo: PostgresGraphRepository) -> None:
    nodes = [
        {"id": "A", "department": "FIN", "section": None, "classification": "UNCLASSIFIED",
         "file_no": None, "doc_type": "GO_MS", "issue_date": "2020-01-02"},
        {"id": "B", "department": "FIN", "classification": "UNCLASSIFIED"},
    ]  # fmt: skip
    edges = [{"from": "A", "relation": "AMENDS", "to": "B", "confirmed": True}]
    assert repo.load_rows(nodes, edges) == (2, 1)
    assert repo.node("A") == node("A").model_copy(
        update={"tags": node("A").tags.model_copy(update={"section": None})}
    )
    with pytest.raises(GraphError):
        repo.load_rows([{"id": "C", "department": "FIN", "classification": None}], [])
    assert repo.counts() == (2, 1)
