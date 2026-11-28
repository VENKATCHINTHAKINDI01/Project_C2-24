"""SpannerGraphRepository (ADR-0048): the same answers as the in-memory reference, the scope applied
to every node of a walk, and two reads per hop rather than two per node.

There is no Spanner here (the emulator cannot be fetched in this workspace): the adapter's own SQL
runs against SQLite through a thin port that binds `IN UNNEST(@ids)` as a list and `@name` as a
value — the two GoogleSQL forms the adapter uses. On GCP, `27_spanner_graph.py check` compares
the real Spanner graph with the Cloud SQL one, walk by walk.
"""

from __future__ import annotations

import random
import re
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from app.graph.repository import (
    Direction,
    EdgeKind,
    GraphEdge,
    GraphError,
    GraphRepository,
    InMemoryGraphRepository,
)
from app.graph.spanner import SpannerGraphRepository
from tests.unit.test_graph_postgres import ALL, _random_graph, node, scope

ROOT = Path(__file__).parents[3]
PG = ROOT / "data" / "schemas" / "postgres" / "0002_graph.sql"
PG_EDGE_STATE = ROOT / "data" / "schemas" / "postgres" / "0009_graph_edge_state.sql"
DDL = ROOT / "data" / "schemas" / "spanner" / "0001_graph.ddl"
_KEYS = {"graph_nodes": ("canonical_id",), "graph_edges": ("source", "kind", "target")}


class SqlitePort:
    """Executes the adapter's GoogleSQL on SQLite (same tables as Cloud SQL) and counts reads."""

    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.executescript(
            "CREATE TABLE schema_migrations (version TEXT PRIMARY KEY);"
            + PG.read_text("utf-8")
            + PG_EDGE_STATE.read_text("utf-8").replace("ADD COLUMN IF NOT EXISTS ", "ADD COLUMN ")
        )
        self.reads: list[str] = []

    def query(self, sql: str, params: Mapping[str, Any] | None = None) -> list[tuple[Any, ...]]:
        self.reads.append(sql)
        p = dict(params or {})
        args: list[Any] = []

        def unnest(m: re.Match[str]) -> str:
            vals = list(p[m.group(1)])
            args.extend(vals)
            return "IN (" + ", ".join("?" * len(vals)) + ")" if vals else "IN (NULL)"

        q = re.sub(r"IN UNNEST\(@(\w+)\)", unnest, sql)
        assert "@" not in q, q  # every parameter is bound, none is spliced into the text
        return [tuple(r) for r in self.db.execute(q, args).fetchall()]

    def upsert(self, table: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
        keys = _KEYS[table]
        sets = ", ".join(f"{c} = excluded.{c}" for c in columns if c not in keys)
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))}) "
            f"ON CONFLICT ({', '.join(keys)}) DO UPDATE SET {sets}"
        )
        self.db.executemany(
            sql, [[str(v) if hasattr(v, "isoformat") else v for v in r] for r in rows]
        )

    def delete(self, table: str, keys: Sequence[Sequence[Any]]) -> None:
        cols = _KEYS[table]
        where = " AND ".join(f"{c} = ?" for c in cols)
        self.db.executemany(f"DELETE FROM {table} WHERE {where}", [list(k) for k in keys])


@pytest.fixture
def port() -> SqlitePort:
    return SqlitePort()


@pytest.fixture
def repo(port: SqlitePort) -> SpannerGraphRepository:
    return SpannerGraphRepository(port)


def test_is_a_graph_repository(repo: SpannerGraphRepository) -> None:
    assert isinstance(repo, GraphRepository)


def test_edge_needs_known_ends_and_confirming_replaces(repo: SpannerGraphRepository) -> None:
    repo.upsert_node(node("A"))
    with pytest.raises(GraphError):
        repo.upsert_edge(GraphEdge(source="A", kind=EdgeKind.AMENDS, target="B"))
    repo.upsert_node(node("B"))
    repo.upsert_edge(GraphEdge(source="A", kind=EdgeKind.AMENDS, target="B", confirmed=False))
    repo.upsert_edge(GraphEdge(source="A", kind=EdgeKind.AMENDS, target="B", confirmed=True))
    assert repo.edges() == [GraphEdge(source="A", kind=EdgeKind.AMENDS, target="B")]
    assert repo.counts() == (2, 1)


def test_walk_never_passes_through_a_node_outside_the_scope(repo: SpannerGraphRepository) -> None:
    for n in (node("A"), node("X", "GAD", cls="RESTRICTED"), node("C")):
        repo.upsert_node(n)
    repo.upsert_edge(GraphEdge(source="A", kind=EdgeKind.REFERENCES, target="X"))
    repo.upsert_edge(GraphEdge(source="X", kind=EdgeKind.REFERENCES, target="C"))
    assert repo.walk(["A"], scope("FIN"), kinds=ALL, direction=Direction.OUT, max_hops=3) == []
    back = repo.walk(["C"], scope("GAD"), kinds=ALL, direction=Direction.IN, max_hops=3)
    assert [h.canonical_id for h in back] == ["X", "A"]
    assert repo.walk(["X"], scope("FIN"), kinds=ALL, direction=Direction.BOTH, max_hops=2) == []


def test_properties_are_kept_and_not_wiped_by_a_bare_upsert(
    repo: SpannerGraphRepository, port: SqlitePort
) -> None:
    repo.upsert_node(
        node("A"), {"doc_type": "GO_MS", "hierarchy_level": 3, "issue_date": "2024-05-01"}
    )
    repo.upsert_node(node("A", "GAD"))
    row = port.db.execute(
        "SELECT department, doc_type, hierarchy_level, issue_date FROM graph_nodes"
    ).fetchone()
    assert (row[0], row[1], row[2], str(row[3])) == ("GAD", "GO_MS", 3, "2024-05-01")


@pytest.mark.parametrize("seed", range(8))
def test_same_answers_as_the_reference(repo: SpannerGraphRepository, seed: int) -> None:
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
            assert all(sc.admits(gn.tags) for h in got for c in h.path if (gn := ref.node(c)))
    cid = nodes[3].canonical_id
    assert repo.edges_to(cid) == ref.edges_to(cid)
    assert repo.edges_from(cid) == ref.edges_from(cid)
    assert repo.node(cid) == ref.node(cid)


def test_a_walk_reads_per_hop_not_per_node(repo: SpannerGraphRepository, port: SqlitePort) -> None:
    # a star: 40 neighbours of A, each with its own neighbour — two hops
    repo.upsert_node(node("A"))
    for i in range(40):
        repo.upsert_node(node(f"B{i}"))
        repo.upsert_node(node(f"C{i}"))
    for i in range(40):
        repo.upsert_edge(GraphEdge(source="A", kind=EdgeKind.REFERENCES, target=f"B{i}"))
        repo.upsert_edge(GraphEdge(source=f"B{i}", kind=EdgeKind.REFERENCES, target=f"C{i}"))
    port.reads.clear()
    hits = repo.walk(["A"], scope("FIN"), kinds=ALL, direction=Direction.OUT, max_hops=2)
    assert len(hits) == 80
    assert len(port.reads) <= 1 + 2 * 2  # the seeds, then two reads per hop


def test_job_files_load_and_an_untagged_node_is_refused(repo: SpannerGraphRepository) -> None:
    nodes: list[dict[str, Any]] = [
        {"id": "A", "department": "FIN", "section": None, "classification": "UNCLASSIFIED",
         "file_no": None, "doc_type": "GO_MS", "issue_date": "2020-01-02"},
        {"id": "B", "department": "FIN", "classification": "UNCLASSIFIED"},
    ]  # fmt: skip
    edges = [{"from": "A", "relation": "AMENDS", "to": "B", "confirmed": True}]
    assert repo.load_rows(nodes, edges) == (2, 1)
    with pytest.raises(GraphError):
        repo.load_rows([{"id": "C", "department": "FIN", "classification": None}], [])
    assert repo.counts() == (2, 1)


def test_the_spanner_schema_matches_the_cloud_sql_one() -> None:
    """Same tables and columns in both stores (one shape, plan §3.6), plus the property graph."""
    ddl, pg = DDL.read_text("utf-8"), PG.read_text("utf-8")

    def cols(text: str, table: str) -> list[str]:
        body = re.search(rf"CREATE TABLE (?:IF NOT EXISTS )?{table} \((.*?)\n\)", text, re.S)
        assert body, table
        return [
            ln.split()[0]
            for ln in body.group(1).splitlines()
            if ln.strip() and not ln.strip().startswith(("--", "CONSTRAINT", "PRIMARY"))
        ]

    for t in ("graph_nodes", "graph_edges"):
        assert cols(ddl, t) == cols(pg, t)
    assert "CREATE PROPERTY GRAPH c2_graph" in ddl
    assert "graph_edges_by_target" in ddl


def test_the_cloud_port_binds_lists_as_string_arrays_and_writes_in_one_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CloudSpannerPort against a stand-in for google-cloud-spanner: parameters are bound with
    types (never spliced), a read is a snapshot, a write is one batch."""
    import sys
    import types

    seen: dict[str, Any] = {}

    class Snap:
        def __enter__(self) -> Snap:
            return self

        def __exit__(self, *a: object) -> None:
            pass

        def execute_sql(self, sql: str, params: Any = None, param_types: Any = None) -> list[Any]:
            seen["query"] = (sql, params, param_types)
            return [["A", "FIN"]]

    class Batch(Snap):
        def insert_or_update(self, table: str, columns: Any, values: Any) -> None:
            seen["write"] = (table, columns, values)

    class Db:
        def snapshot(self) -> Snap:
            return Snap()

        def batch(self) -> Batch:
            return Batch()

    class Client:
        def __init__(self, project: str, disable_builtin_metrics: bool = False) -> None:
            seen["project"] = project
            seen["metrics_off"] = disable_builtin_metrics

        def instance(self, name: str) -> Any:
            seen["instance"] = name
            return types.SimpleNamespace(database=lambda d: seen.setdefault("db", d) and Db())

    pt = types.SimpleNamespace(STRING="STRING", Array=lambda t: f"ARRAY<{t}>")
    fake = types.ModuleType("google.cloud.spanner")
    fake.Client = Client  # type: ignore[attr-defined]
    fake.param_types = pt  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google.cloud.spanner", fake)
    import google.cloud

    monkeypatch.setattr(google.cloud, "spanner", fake, raising=False)
    from app.graph.spanner import CloudSpannerPort

    port = CloudSpannerPort("use-case-24-project", "c2-spanner", "c2graph")
    assert seen["metrics_off"] is True
    assert (seen["project"], seen["instance"], seen["db"]) == (
        "use-case-24-project",
        "c2-spanner",
        "c2graph",
    )
    assert port.query("SELECT x FROM t WHERE id IN UNNEST(@ids)", {"ids": ["A", "B"]}) == [
        ("A", "FIN")
    ]
    assert seen["query"][1] == {"ids": ["A", "B"]}
    assert seen["query"][2] == {"ids": "ARRAY<STRING>"}
    port.query("SELECT 1")
    assert seen["query"][1:] == (None, None)
    port.upsert(
        "graph_edges", ["source", "kind", "target", "confirmed"], [("A", "CITES", "B", True)]
    )
    assert seen["write"] == (
        "graph_edges",
        ("source", "kind", "target", "confirmed"),
        [["A", "CITES", "B", True]],
    )
