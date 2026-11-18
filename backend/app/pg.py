"""PostgreSQL access for application state (plan §3.5: Cloud SQL holds app data, review decisions,
authz tuples and the checkpointer; CLAUDE.md §2.2).

`Pg` keeps a small pool of DB-API connections and hands out transactions, with a connect timeout
and a statement timeout on every connection (ADR-0039). Each transaction
commits, or rolls back on any error, and the error propagates: callers fail closed, nothing is
retried silently. Two ways to connect:
- `C2_PG_DSN`: local or test Postgres (psycopg);
- `C2_CLOUDSQL_INSTANCE` + `C2_CLOUDSQL_USER`: Cloud SQL through the Cloud SQL Python connector,
  with IAM database authentication (no passwords) and no open IP ranges.

Both drivers use the `%s` parameter style, so the SQL in callers is driver-neutral. Schema changes
are applied by the bootstrap script (`data/schemas/postgres/*.sql`), never by the running app.
"""

from __future__ import annotations

import contextlib
import importlib
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.config import Settings


class PgError(Exception):
    """Postgres is misconfigured or unreachable. Fail closed."""


class Pg:
    """A small pool of connections (ADR-0039). Each `tx()` borrows one connection for one
    transaction; at most `size` run at once, the rest wait up to `wait_s` and then fail closed
    (`PgError`) instead of queueing forever. A connection that errors is dropped, not reused."""

    def __init__(self, connect: Callable[[], Any], size: int = 4, wait_s: float = 10.0) -> None:
        self._connect = connect
        self._idle: list[Any] = []
        self._slots = threading.BoundedSemaphore(max(1, size))
        self._lock = threading.Lock()
        self._wait_s = wait_s

    @contextmanager
    def tx(self) -> Iterator[Any]:
        """A cursor inside one transaction: commit on success, roll back and re-raise on error."""
        if not self._slots.acquire(timeout=self._wait_s):
            raise PgError("no database connection free in time")
        conn: Any = None
        healthy = True
        try:
            with self._lock:
                conn = self._idle.pop() if self._idle else None
            if conn is None:
                conn = self._connect()
            cur = conn.cursor()
            try:
                yield cur
                conn.commit()
            except BaseException:
                try:
                    conn.rollback()
                except Exception:  # broken connection: drop it, the next call reconnects
                    healthy = False
                raise
            finally:
                try:
                    cur.close()
                except Exception:
                    healthy = False
        except BaseException:
            if conn is not None and not healthy:
                self._close(conn)
                conn = None
            raise
        finally:
            if conn is not None and healthy:
                with self._lock:
                    self._idle.append(conn)
            self._slots.release()

    @staticmethod
    def _close(conn: Any) -> None:
        with contextlib.suppress(Exception):  # already broken
            conn.close()

    def close(self) -> None:
        with self._lock:
            idle, self._idle = self._idle, []
        for c in idle:
            self._close(c)


def apply_migrations(pg: Pg, directory: Path) -> list[str]:
    """Apply `NNNN_*.sql` files in order (each is idempotent). Returns the versions applied."""
    done: list[str] = []
    for f in sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        with pg.tx() as cur:
            cur.execute(f.read_text("utf-8"))
        done.append(f.stem)
    return done


def pg_from_settings(settings: Settings) -> Pg | None:
    """None when state is kept in memory (sandbox default). Bad config raises at startup."""
    if settings.state_store == "memory":
        return None
    if settings.pg_dsn:
        dsn = settings.pg_dsn

        def local() -> Any:
            return importlib.import_module("psycopg").connect(
                dsn,
                connect_timeout=settings.pg_connect_timeout_s,
                options=f"-c statement_timeout={settings.pg_statement_timeout_ms}",
            )

        return Pg(local, size=settings.pg_pool_size)
    if not (settings.cloudsql_instance and settings.cloudsql_user):
        raise PgError("postgres state needs C2_PG_DSN or C2_CLOUDSQL_INSTANCE + C2_CLOUDSQL_USER")
    instance, user, db = settings.cloudsql_instance, settings.cloudsql_user, settings.cloudsql_db
    connector: Any = None

    def cloud() -> Any:  # IAM database auth via the Cloud SQL connector (`gcp` extra)
        nonlocal connector
        if connector is None:
            mod = importlib.import_module("google.cloud.sql.connector")
            connector = mod.Connector(refresh_strategy="lazy")
        conn = connector.connect(
            instance,
            "pg8000",
            user=user,
            db=db,
            enable_iam_auth=True,
            timeout=settings.pg_connect_timeout_s,
        )
        # every statement on this connection is cut off after the limit (fail closed, not hang)
        cur = conn.cursor()
        cur.execute(f"SET statement_timeout = {int(settings.pg_statement_timeout_ms)}")
        cur.close()
        conn.commit()
        return conn

    return Pg(cloud, size=settings.pg_pool_size)
