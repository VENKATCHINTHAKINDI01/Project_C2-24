"""Postgres-backed review queue, confirmed text and audit log (plan §3.5, §4.2, §10.4).

The same contract as the in-memory classes, checked against a real PostgreSQL 16. These tests run
only when `C2_TEST_PG_DSN` points at a throwaway database (they create and drop their own schema);
otherwise they are skipped. Transaction handling is checked with a fake connection, always.
"""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.audit.log import AuditLog
from app.audit.pg_log import PostgresAuditLog
from app.config import Settings
from app.hitl.pg_queue import PostgresConfirmedText, PostgresReviewQueue
from app.hitl.queue import ReviewError, ReviewKind, ReviewQueue, ReviewState
from app.pg import Pg, PgError, apply_migrations, pg_from_settings

MIGRATIONS = Path(__file__).resolve().parents[3] / "data" / "schemas" / "postgres"
DSN = os.environ.get("C2_TEST_PG_DSN")
AT = dt.datetime(2026, 11, 12, 9, tzinfo=dt.UTC)
LOW = ReviewKind.LOW_CONFIDENCE_EXTRACTION


# ---- transaction handling (no database needed) ----


class _Cur:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    def execute(self, sql: str, params: Any = None) -> None:
        if "boom" in sql:
            raise RuntimeError("boom")
        self.conn.ops.append("exec")

    def close(self) -> None:
        pass


class _Conn:
    def __init__(self) -> None:
        self.ops: list[str] = []

    def cursor(self) -> _Cur:
        return _Cur(self)

    def commit(self) -> None:
        self.ops.append("commit")

    def rollback(self) -> None:
        self.ops.append("rollback")

    def close(self) -> None:
        self.ops.append("close")


def test_tx_commits_or_rolls_back_and_reraises() -> None:
    conn = _Conn()
    pg = Pg(lambda: conn)
    with pg.tx() as cur:
        cur.execute("select 1")
    with pytest.raises(RuntimeError), pg.tx() as cur:
        cur.execute("boom")
    assert conn.ops == ["exec", "commit", "rollback"]


def test_memory_by_default_and_bad_postgres_config_fails_at_startup() -> None:
    assert pg_from_settings(Settings()) is None
    with pytest.raises(PgError):
        pg_from_settings(Settings(state_store="postgres"))


# ---- against a real PostgreSQL (skipped without C2_TEST_PG_DSN) ----

needs_pg = pytest.mark.skipif(DSN is None, reason="C2_TEST_PG_DSN not set (local Postgres 16)")


@pytest.fixture
def pg() -> Iterator[Pg]:
    psycopg = pytest.importorskip("psycopg")
    schema = f"t_{uuid.uuid4().hex[:10]}"
    admin = psycopg.connect(DSN, autocommit=True)
    admin.execute(f"CREATE SCHEMA {schema}")
    p = Pg(lambda: psycopg.connect(DSN, options=f"-c search_path={schema}"))
    try:
        assert apply_migrations(p, MIGRATIONS) == [
            "0001_review_audit",
            "0002_graph",
            "0003_sessions",
        ]
        apply_migrations(p, MIGRATIONS)  # idempotent
        yield p
    finally:
        p.close()
        admin.execute(f"DROP SCHEMA {schema} CASCADE")
        admin.close()


@needs_pg
def test_queue_matches_in_memory_contract(pg: Pg) -> None:
    for q in (ReviewQueue(), PostgresReviewQueue(pg)):
        a = q.submit(LOW, "doc-1", "v1", "threshold not calibrated", AT)
        assert q.submit(LOW, "doc-1", "v1", "again", AT) == a  # idempotent
        assert a.item_id == "RV-000001" and a.state is ReviewState.PENDING
        b = q.submit(ReviewKind.UNRESOLVED_REFERENCE, "doc-2", "v1", "no canonical ID", AT)
        assert [i.item_id for i in q.pending()] == [a.item_id, b.item_id]
        assert [i.item_id for i in q.pending(LOW)] == [a.item_id]
        assert q.blocks("doc-1", "v1") and not q.blocks("doc-1", "v2")

        with pytest.raises(ReviewError, match="unknown"):
            q.decide("RV-999999", reviewer="U01", confirm=True, reason="ok", at=AT)
        with pytest.raises(ReviewError, match="required"):
            q.decide(a.item_id, reviewer=" ", confirm=True, reason="ok", at=AT)
        done = q.decide(a.item_id, reviewer="U01", confirm=True, reason="read the scan", at=AT)
        assert done.state is ReviewState.CONFIRMED and done.reviewer == "U01"
        assert done.decided_at == AT and not q.blocks("doc-1", "v1")
        with pytest.raises(ReviewError, match="already decided"):
            q.decide(a.item_id, reviewer="U02", confirm=False, reason="no", at=AT)
        q.decide(b.item_id, reviewer="U01", confirm=False, reason="wrong file", at=AT)
        assert q.blocks("doc-2", "v1")  # rejected still holds
        assert q.pending() == ()
        assert [i.state for i in q.history()] == [ReviewState.CONFIRMED, ReviewState.REJECTED]


@needs_pg
def test_decisions_survive_a_restart(pg: Pg) -> None:
    item = PostgresReviewQueue(pg).submit(LOW, "doc-1", "v1", "held", AT)
    PostgresReviewQueue(pg).decide(item.item_id, reviewer="U01", confirm=True, reason="ok", at=AT)
    PostgresConfirmedText(pg)["v1"] = "corrected text"
    pg.close()  # a new process: new connection, nothing in memory

    again = PostgresReviewQueue(pg).submit(LOW, "doc-1", "v1", "held", AT)  # re-ingest at startup
    assert again.state is ReviewState.CONFIRMED and again.item_id == item.item_id
    texts = PostgresConfirmedText(pg)
    assert texts.get("v1") == "corrected text" and texts.get("v2") is None
    texts["v1"] = "corrected again"
    assert dict(texts) == {"v1": "corrected again"} and len(texts) == 1
    with pytest.raises(ReviewError):
        del texts["v1"]


@needs_pg
def test_audit_is_append_only_ids_only(pg: Pg) -> None:
    log: AuditLog = PostgresAuditLog(pg)
    e1 = log.record("req-1", "U01", "assist.document.preview", "allowed", ("AP-FIN01-GO-88-2022",))
    e2 = log.record("req-2", None, "assist.document.preview", "denied", detail="x" * 300)
    assert (e1.seq, e2.seq) == (1, 2) and e1.ids == ("AP-FIN01-GO-88-2022",)
    assert len(e2.detail) == 200 and e2.ids == ()
    assert [e.request_id for e in log.events()] == ["req-1", "req-2"]
    for sql in ("UPDATE audit_events SET outcome = 'allowed'", "DELETE FROM audit_events"):
        with pytest.raises(Exception, match="append-only"), pg.tx() as cur:
            cur.execute(sql)
    assert len(log.events()) == 2


@needs_pg
def test_schema_refuses_inconsistent_rows(pg: Pg) -> None:
    with pytest.raises(Exception, match="check"), pg.tx() as cur:  # decided without a reviewer
        cur.execute(
            "INSERT INTO review_items (item_id, kind, subject, version, reason, created_at, state) "
            "VALUES ('RV-X', 'low_confidence_extraction', 'd', 'v', 'r', now(), 'confirmed')"
        )


def test_app_uses_postgres_state_when_configured() -> None:
    from app.main import create_app

    s = Settings(state_store="postgres", pg_dsn="host=127.0.0.1 dbname=unused")  # lazy: no connect
    assert isinstance(create_app(s).state.audit, PostgresAuditLog)
    assert not isinstance(create_app(Settings()).state.audit, PostgresAuditLog)
