"""Conversation memory in Cloud SQL behaves like the reference `SessionMemory` (ADR-0029).
SQL runs on SQLite through the same `%s` → `?` shim as the graph tests; real Postgres when
C2_TEST_PG_DSN is set."""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import pytest

from app.memory.pg_session import PostgresSessionMemory
from app.memory.session import SessionError, SessionMemory, Turn
from app.pg import Pg
from tests.unit.test_graph_postgres import _Cur

SCHEMA = Path(__file__).parents[3] / "data" / "schemas" / "postgres" / "0003_sessions.sql"


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


def _turn(n: int, *ids: str) -> Turn:
    return Turn(
        request_id=f"R{n}",
        at=dt.datetime(2026, 11, 15, 9, n, tzinfo=dt.UTC),
        canonical_query=f"question {n}",
        entity_ids=ids,
        scope_signature="sig",
    )


@pytest.mark.parametrize("make", [lambda: SessionMemory(max_turns=3), "pg"])
def test_same_behaviour_as_the_reference(make: object) -> None:
    conn = _Conn()
    mem = PostgresSessionMemory(Pg(lambda: conn), max_turns=3) if make == "pg" else make()  # type: ignore[operator]
    for n in range(1, 6):
        mem.append("U01", "s1", _turn(n, f"D{n}"))
    got = mem.turns("U01", "s1")
    assert [t.request_id for t in got] == ["R3", "R4", "R5"]  # the last three, oldest first
    assert got[-1].entity_ids == ("D5",)
    with pytest.raises(SessionError):
        mem.turns("U02", "s1")  # another officer's session
    with pytest.raises(SessionError):
        mem.append("U02", "s1", _turn(9))
    assert mem.turns("U02", "fresh") == ()


@pytest.mark.skipif(
    not __import__("os").environ.get("C2_TEST_PG_DSN"), reason="C2_TEST_PG_DSN not set"
)
def test_on_real_postgres() -> None:
    import os

    import psycopg

    conn = psycopg.connect(os.environ["C2_TEST_PG_DSN"])
    with conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS c2_sess_test CASCADE; CREATE SCHEMA c2_sess_test")
        cur.execute("SET search_path TO c2_sess_test")
        cur.execute("CREATE TABLE schema_migrations (version TEXT PRIMARY KEY)")
        cur.execute(SCHEMA.read_text("utf-8"))
    conn.commit()
    try:
        mem = PostgresSessionMemory(Pg(lambda: conn), max_turns=2)
        for n in range(1, 4):
            mem.append("U01", "s1", _turn(n, f"D{n}"))
        assert [t.entity_ids for t in mem.turns("U01", "s1")] == [("D2",), ("D3",)]
        with pytest.raises(SessionError):
            mem.append("U02", "s1", _turn(9))
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA c2_sess_test CASCADE")
        conn.commit()
        conn.close()
