"""Load the knowledge graph the build job wrote (gs://<project>-<prefix>-artifacts/graph/) into
Spanner Graph (ADR-0048), the same files 16_graph_load.py loads into Cloud SQL.

Run from backend/ with the gcp extra (dry run by default; APPLY=1 executes):

    env -u VIRTUAL_ENV uv run --extra gcp python ../infrastructure/gcp/27_spanner_graph_load.py
    APPLY=1 env -u VIRTUAL_ENV uv run --extra gcp \
        python ../infrastructure/gcp/27_spanner_graph_load.py

Uses your gcloud login and Application Default Credentials (roles/editor writes Spanner data); no
keys, no passwords. The two files are read straight from the bucket, nothing is written to disk.
The store is made equal to the build (ADR-0055): links and nodes the build no longer
produces are deleted, the rest upserted. APPLY=1 PLAN_ONLY=1 connects and prints what would
change, changing nothing; a sync deleting more than MAX_DELETE_SHARE (0.2) is refused unless
ALLOW_LARGE_DELETE=1. A node without access tags is refused.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))
APPLY = os.environ.get("APPLY") == "1"


def config() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (HERE / "config.env").read_text("utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def rows(uri: str) -> list[dict[str, Any]]:
    gcloud = shutil.which("gcloud")
    if gcloud is None:
        sys.exit("gcloud not installed")
    text = subprocess.run(  # noqa: S603 — fixed program, our own bucket path
        [gcloud, "storage", "cat", uri], check=True, capture_output=True, text=True
    ).stdout
    return [json.loads(x) for x in text.splitlines() if x.strip()]


def main() -> None:
    cfg = config()
    project, prefix = cfg["PROJECT_ID"], cfg["PREFIX"]
    instance = os.environ.get("SPANNER_INSTANCE", f"{prefix}-spanner")
    database = os.environ.get("SPANNER_DATABASE", f"{prefix}graph")
    base = f"gs://{project}-{prefix}-artifacts/graph"
    nodes, edges = rows(f"{base}/nodes.jsonl"), rows(f"{base}/edges.jsonl")
    print(
        f"{base}: {len(nodes)} nodes, {len(edges)} edges → spanner {project}/{instance}/{database}"
    )
    if not APPLY:
        print("[dry-run] nothing changed. Re-run with APPLY=1.")
        return

    from app.graph.spanner import CloudSpannerPort, SpannerGraphRepository

    repo = SpannerGraphRepository(CloudSpannerPort(project, instance, database))
    p = repo.sync_rows(
        nodes,
        edges,
        max_delete_share=float(os.environ.get("MAX_DELETE_SHARE", "0.2")),
        allow_large_delete=os.environ.get("ALLOW_LARGE_DELETE") == "1",
        dry_run=os.environ.get("PLAN_ONLY") == "1",
    )
    plan_only = os.environ.get("PLAN_ONLY") == "1"
    verb = "PLAN ONLY, nothing changed:" if plan_only else "+ synced:"
    print(f"{verb} {p.summary()}; Spanner now holds {repo.counts()}")


if __name__ == "__main__":
    main()
