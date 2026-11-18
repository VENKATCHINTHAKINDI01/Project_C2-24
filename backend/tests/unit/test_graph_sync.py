"""Each graph load makes the store equal to the build (ADR-0055): links an earlier build produced
and this one does not are deleted, the rest upserted; guarded against emptying the store or
deleting too much; a dry run changes nothing. Same rules on Cloud SQL and Spanner."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from app.graph.postgres import PostgresGraphRepository
from app.graph.spanner import SpannerGraphRepository
from app.graph.sync import SyncRefusedError
from app.pg import Pg
from tests.unit.test_graph_postgres import DSN, SCHEMA, _Conn
from tests.unit.test_graph_spanner import SqlitePort

Repo = PostgresGraphRepository | SpannerGraphRepository


@pytest.fixture(params=["cloudsql", "spanner", "real-postgres"])
def repo(request: pytest.FixtureRequest) -> Iterator[Repo]:
    if request.param == "cloudsql":
        lite = _Conn()
        yield PostgresGraphRepository(Pg(lambda: lite))
    elif request.param == "spanner":
        yield SpannerGraphRepository(SqlitePort())
    else:
        if DSN is None:
            pytest.skip("C2_TEST_PG_DSN not set (local Postgres 16)")
        import psycopg

        conn = psycopg.connect(DSN)
        with conn.cursor() as cur:  # a throwaway schema: no other test's tables are touched
            cur.execute("DROP SCHEMA IF EXISTS c2_sync_test CASCADE; CREATE SCHEMA c2_sync_test")
            cur.execute("SET search_path TO c2_sync_test")
            cur.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)")
            cur.execute(SCHEMA.read_text("utf-8"))
        conn.commit()
        try:
            yield PostgresGraphRepository(Pg(lambda: conn))
        finally:
            with conn.cursor() as cur:
                cur.execute("DROP SCHEMA c2_sync_test CASCADE")
            conn.commit()
            conn.close()


def nodes(*ids: str) -> list[dict[str, Any]]:
    return [{"id": i, "department": "FIN", "section": "A", "classification": "UNCLASSIFIED",
             "file_no": None, "doc_type": "GO_MS"} for i in ids]  # fmt: skip


def edge(a: str, kind: str, b: str, confirmed: bool = True) -> dict[str, Any]:
    return {"from": a, "relation": kind, "to": b, "confirmed": confirmed}


IDS = [f"N{i:02d}" for i in range(12)]
FIRST = [edge(IDS[i], "REFERENCES", IDS[i + 1]) for i in range(11)] + [
    edge("N00", "SUPERSEDES", "N05", confirmed=False),  # an unconfirmed candidate…
    edge("N01", "AMENDS", "N02", confirmed=False),
]


def held(repo: Repo) -> set[tuple[str, str, str, bool]]:
    return {(e.source, e.kind.value, e.target, e.confirmed) for e in repo.edges()}


def test_a_link_the_build_no_longer_produces_is_deleted(repo: Repo) -> None:
    repo.load_rows(nodes(*IDS), FIRST)
    assert repo.counts() == (12, 13)
    second = [e for e in FIRST if e["relation"] != "SUPERSEDES"]  # …that a better reading dropped
    second[-1] = edge("N01", "AMENDS", "N02", confirmed=True)  # and one now stated in the text
    p = repo.sync_rows(nodes(*IDS), second)
    assert p.delete_edges == {("N00", "SUPERSEDES", "N05")} and p.kinds_deleted == {"SUPERSEDES": 1}
    assert p.update_edges == {("N01", "AMENDS", "N02")} and not p.add_edges
    assert repo.counts() == (12, 12)
    assert held(repo) == {(e["from"], e["relation"], e["to"], e["confirmed"]) for e in second}


def test_a_node_the_build_no_longer_produces_goes_with_its_links(repo: Repo) -> None:
    repo.load_rows(nodes(*IDS), FIRST)
    keep = IDS[:11]
    p = repo.sync_rows(nodes(*keep), [e for e in FIRST if e["from"] in keep and e["to"] in keep])
    assert p.delete_nodes == {"N11"} and ("N10", "REFERENCES", "N11") in p.delete_edges
    assert repo.counts()[0] == 11 and repo.node("N11") is None


def test_a_dry_run_reports_and_changes_nothing(repo: Repo) -> None:
    repo.load_rows(nodes(*IDS), FIRST)
    before = (repo.counts(), held(repo))
    p = repo.sync_rows(nodes(*IDS), FIRST[:-2], dry_run=True)
    assert len(p.delete_edges) == 2 and "delete 0 nodes / 2 links" in p.summary()
    assert (repo.counts(), held(repo)) == before


def test_deleting_too_much_or_an_empty_build_is_refused_and_changes_nothing(repo: Repo) -> None:
    repo.load_rows(nodes(*IDS), FIRST)
    before = (repo.counts(), held(repo))
    with pytest.raises(SyncRefusedError, match="would delete 10 of 13 links"):
        repo.sync_rows(nodes(*IDS), FIRST[:3])
    with pytest.raises(SyncRefusedError, match="no nodes"):
        repo.sync_rows([], [], allow_large_delete=True)
    assert (repo.counts(), held(repo)) == before
    p = repo.sync_rows(nodes(*IDS), FIRST[:3], allow_large_delete=True)  # after a dry run
    assert len(p.delete_edges) == 10 and repo.counts() == (12, 3)


def test_a_first_load_into_an_empty_store_just_adds(repo: Repo) -> None:
    p = repo.sync_rows(nodes(*IDS), FIRST)
    assert (len(p.add_nodes), len(p.add_edges), len(p.delete_edges)) == (12, 13, 0)
    assert repo.counts() == (12, 13)
