"""The one-shot schema job (ADR-0043): applies every migration, is safe to re-run, and fails
with exit 1 (no secret printed) when it cannot do its job."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from app import migrate
from app.config import get_settings

DSN = os.environ.get("C2_TEST_PG_DSN")


@pytest.fixture(autouse=True)
def _fresh_settings() -> None:
    get_settings.cache_clear()


def test_without_a_dsn_it_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("C2_PG_DSN", raising=False)
    assert migrate.main() == 1


def test_an_empty_migrations_folder_is_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("C2_PG_DSN", "host=127.0.0.1 port=1 dbname=x user=x")
    monkeypatch.setenv("C2_MIGRATIONS_DIR", str(tmp_path))
    assert migrate.main() == 1


def test_an_unreachable_database_fails_after_the_wait_without_printing_the_dsn(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    pytest.importorskip("psycopg")
    monkeypatch.setenv("C2_PG_DSN", "host=127.0.0.1 port=1 dbname=x user=x password=s3cret")
    monkeypatch.setenv("C2_MIGRATE_WAIT_S", "0")
    monkeypatch.setenv("C2_PG_CONNECT_TIMEOUT_S", "1")
    assert migrate.main() == 1
    assert "database not reachable" in caplog.text and "s3cret" not in caplog.text


@pytest.mark.skipif(DSN is None, reason="C2_TEST_PG_DSN not set (local Postgres 16)")
def test_applies_all_and_is_safe_to_run_again(monkeypatch: pytest.MonkeyPatch) -> None:
    psycopg = pytest.importorskip("psycopg")
    db = f"m_{uuid.uuid4().hex[:10]}"  # a throwaway database: the job sets its own connect options
    admin = psycopg.connect(DSN, autocommit=True)
    admin.execute(f"CREATE DATABASE {db}")
    try:
        monkeypatch.setenv("C2_PG_DSN", f"{DSN} dbname={db}")
        assert migrate.main() == 0
        get_settings.cache_clear()
        assert migrate.main() == 0  # idempotent
        with psycopg.connect(f"{DSN} dbname={db}") as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
                )
            }
        assert {"review_items", "audit_events", "graph_nodes", "session_turns"} <= tables
    finally:
        admin.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")
        admin.close()
