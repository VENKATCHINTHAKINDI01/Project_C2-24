"""One-shot schema job for a local or self-hosted Postgres (ADR-0043; plan §2.2 Cloud SQL).

Applies `data/schemas/postgres/NNNN_*.sql` in order. Each file is idempotent, so running the job
again is safe. The running API never changes the schema (see `app/pg.py`); on GCP the same files
are applied by `infrastructure/gcp/12_cloudsql_schema.py`, which also sets least-privilege grants.

    C2_PG_DSN=… python -m app.migrate

The database may still be starting, so the first connection is retried for up to
`C2_MIGRATE_WAIT_S` seconds (default 60). Exit 0 on success, 1 on any failure, with no secret
printed.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

from app.config import REPO_ROOT, get_settings
from app.pg import apply_migrations, pg_from_settings

log = logging.getLogger("c2.migrate")
DEFAULT_DIR = REPO_ROOT / "data" / "schemas" / "postgres"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = get_settings().model_copy(update={"state_store": "postgres"})
    if not settings.pg_dsn:
        log.error("set C2_PG_DSN (the migration job connects with a DSN)")
        return 1
    directory = Path(os.environ.get("C2_MIGRATIONS_DIR", str(DEFAULT_DIR)))
    if not any(directory.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        log.error("no migrations found in %s", directory)
        return 1
    pg = pg_from_settings(settings)
    if pg is None:  # cannot happen with state_store=postgres; keeps the type checker honest
        return 1
    deadline = time.monotonic() + float(os.environ.get("C2_MIGRATE_WAIT_S", "60"))
    while True:
        try:
            with pg.tx() as cur:
                cur.execute("SELECT 1")
            break
        except Exception as exc:  # database not up yet: retry until the deadline
            if time.monotonic() > deadline:
                log.error("database not reachable: %s", type(exc).__name__)
                return 1
            time.sleep(1)
    try:
        applied = apply_migrations(pg, directory)
    except Exception as exc:  # report the type only: SQL errors can quote data
        log.error("migration failed: %s", type(exc).__name__)
        return 1
    finally:
        pg.close()
    log.info("applied %d migration file(s): %s", len(applied), ", ".join(applied))
    return 0


if __name__ == "__main__":
    sys.exit(main())
