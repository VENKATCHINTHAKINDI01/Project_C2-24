"""Copy the knowledge graph the build job wrote (gs://<project>-<prefix>-artifacts/graph/) into
Cloud SQL. Stop-gap for one situation only: the job's service account has not yet been given the
Cloud SQL roles (cloudsql.client + cloudsql.instanceUser need Project IAM Admin), so the job can
build the graph but cannot load it. Once the roles are granted, run the job with its own load step
and this script is not needed.

Run from backend/ (dry run by default; APPLY=1 executes):

    env -u VIRTUAL_ENV uv run python ../infrastructure/gcp/16_graph_load.py
    APPLY=1 env -u VIRTUAL_ENV uv run python ../infrastructure/gcp/16_graph_load.py

Like 12_cloudsql_schema.py: sets a random one-time password on `postgres`, loads through the
Cloud SQL connector (no open IP ranges), then resets the password to a value nobody sees. The two
files are read straight from the bucket and nothing is written to disk. The tables are made equal to
the build (ADR-0055): links and nodes it no longer produces are deleted, the rest upserted.
APPLY=1 PLAN_ONLY=1 connects and prints what would change, changing nothing; a sync deleting more
than MAX_DELETE_SHARE (0.2) is refused unless ALLOW_LARGE_DELETE=1. A node without access tags is
refused.
"""

from __future__ import annotations

import importlib.util
import json
import os
import secrets
import string
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))
_spec = importlib.util.spec_from_file_location("schema12", HERE / "12_cloudsql_schema.py")
assert _spec and _spec.loader
kit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kit)

APPLY = os.environ.get("APPLY") == "1"


def rows(uri: str) -> list[dict[str, Any]]:
    return [json.loads(x) for x in kit.gcloud("storage", "cat", uri).splitlines() if x.strip()]


def main() -> None:
    cfg = kit.config()
    project, region, prefix = cfg["PROJECT_ID"], cfg["REGION"], cfg["PREFIX"]
    instance = f"{prefix}-sql"
    base = f"gs://{project}-{prefix}-artifacts/graph"
    nodes, edges = rows(f"{base}/nodes.jsonl"), rows(f"{base}/edges.jsonl")
    print(
        f"{base}: {len(nodes)} nodes, {len(edges)} edges → {project}:{region}:{instance}/{prefix}"
    )
    if not APPLY:
        print("[dry-run] nothing changed. Re-run with APPLY=1.")
        return

    from google.cloud.sql.connector import Connector

    from app.graph.postgres import PostgresGraphRepository
    from app.pg import Pg

    connector = Connector(refresh_strategy="lazy")

    def rotate() -> str:
        pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(40))
        kit.gcloud(
            "sql", "users", "set-password", "postgres", "--instance", instance,
            "--project", project, f"--password={pw}", secret=pw,
        )  # fmt: skip
        return pw

    try:
        pw = rotate()
        name = f"{project}:{region}:{instance}"
        pg = Pg(lambda: connector.connect(name, "pg8000", user="postgres", password=pw, db=prefix))
        try:
            repo = PostgresGraphRepository(pg)
            p = repo.sync_rows(
                nodes,
                edges,
                max_delete_share=float(os.environ.get("MAX_DELETE_SHARE", "0.2")),
                allow_large_delete=os.environ.get("ALLOW_LARGE_DELETE") == "1",
                dry_run=os.environ.get("PLAN_ONLY") == "1",
            )
            verb = (
                "PLAN ONLY, nothing changed:" if os.environ.get("PLAN_ONLY") == "1" else "+ synced:"
            )
            print(f"{verb} {p.summary()}; tables now hold {repo.counts()}")
        finally:
            pg.close()
    finally:
        rotate()
        connector.close()
        print("+ postgres password reset to an unseen random value")


if __name__ == "__main__":
    main()
