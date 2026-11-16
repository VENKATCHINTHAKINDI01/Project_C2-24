"""PostgreSQL access for application state (plan §3.5: Cloud SQL holds app data, review decisions,
authz tuples and the checkpointer; CLAUDE.md §2.2).

`Pg` holds one DB-API connection behind a lock and hands out transactions. Each transaction
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
    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect
        self._conn: Any = None
        self._lock = threading.Lock()

    @contextmanager
    def tx(self) -> Iterator[Any]:
        """A cursor inside one transaction: commit on success, roll back and re-raise on error."""
        with self._lock:
            if self._conn is None:
                self._conn = self._connect()
            cur = self._conn.cursor()
            try:
                yield cur
                self._conn.commit()
            except BaseException:
                try:
                    self._conn.rollback()
                except Exception:  # broken connection: drop it, the next call reconnects
                    self._drop()
                raise
            finally:
                try:
                    cur.close()
                except Exception:
                    self._drop()

    def _drop(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            with contextlib.suppress(Exception):  # already broken; the next call reconnects
                conn.close()

    def close(self) -> None:
        with self._lock:
            self._drop()


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
            return importlib.import_module("psycopg").connect(dsn)

        return Pg(local)
    if not (settings.cloudsql_instance and settings.cloudsql_user):
        raise PgError("postgres state needs C2_PG_DSN or C2_CLOUDSQL_INSTANCE + C2_CLOUDSQL_USER")
    instance, user, db = settings.cloudsql_instance, settings.cloudsql_user, settings.cloudsql_db
    connector: Any = None

    def cloud() -> Any:  # IAM database auth via the Cloud SQL connector (`gcp` extra)
        nonlocal connector
        if connector is None:
            mod = importlib.import_module("google.cloud.sql.connector")
            connector = mod.Connector(refresh_strategy="lazy")
        return connector.connect(instance, "pg8000", user=user, db=db, enable_iam_auth=True)

    return Pg(cloud)
