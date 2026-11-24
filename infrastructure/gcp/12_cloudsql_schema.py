"""Create or update the app tables in Cloud SQL (`c2-sql`, database `c2`) and grant access.

Run from backend/ with the gcp extra (dry run by default; APPLY=1 executes):

    env -u VIRTUAL_ENV uv run python ../infrastructure/gcp/12_cloudsql_schema.py
    APPLY=1 env -u VIRTUAL_ENV uv run python ../infrastructure/gcp/12_cloudsql_schema.py

What it does (safe to run again; migrations are idempotent and never drop data):
1. Sets a random one-time password on the built-in `postgres` user. IAM users cannot create
   tables in `public` on Cloud SQL, so schema work needs `postgres`. The password is never printed
   or saved.
2. Applies data/schemas/postgres/NNNN_*.sql in order, as `postgres`, through the Cloud SQL connector
   (no authorized networks, no open IP ranges).
3. Grants the least the app needs:
   - c2-api and c2-ingest: read/write on review items and confirmed text, insert-only on the
     audit trail (no UPDATE/DELETE: the trigger would refuse them anyway);
   - knowledge graph tables: c2-ingest read/write (no DELETE), c2-api read-only;
   - conversation memory: c2-api insert and read only;
   - the developer's IAM login: read-only.
4. Sets `postgres` to a new random password that nobody ever sees. No usable password is left.
5. Checks the developer's IAM login (no password) can connect and read the migration table.

Needs: gcloud signed in as the developer, and Application Default Credentials
(`gcloud auth application-default login`).
"""

from __future__ import annotations

import os
import re
import secrets
import shutil
import string
import subprocess
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MIGRATIONS = HERE.parents[1] / "data" / "schemas" / "postgres"
APPLY = os.environ.get("APPLY") == "1"
_NAME = re.compile(r"^[a-z0-9][a-z0-9._@-]*$")


def config() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (HERE / "config.env").read_text("utf-8").splitlines():
        m = re.match(r'^([A-Z_]+)="?([^"#]*)"?', line.strip())
        if m:
            out[m.group(1)] = m.group(2).strip()
    for k in ("PROJECT_ID", "REGION", "PREFIX"):
        if not out.get(k):
            sys.exit(f"set {k} in infrastructure/gcp/config.env")
    return out


def gcloud(*args: str, secret: str | None = None) -> str:
    exe = shutil.which("gcloud") or sys.exit("gcloud not installed")
    r = subprocess.run([exe, *args], capture_output=True, text=True, check=False)  # noqa: S603
    if r.returncode != 0:
        msg = r.stderr.strip()
        if secret:
            msg = msg.replace(secret, "<hidden>")  # the error is shown, the password never is
        sys.exit(f"gcloud {args[0]} {args[1]} failed: {msg}")
    return r.stdout.strip()


def ident(name: str) -> str:
    if not _NAME.match(name):
        sys.exit(f"unexpected database user name: {name!r}")
    return f'"{name}"'


def grants(api: str, ingest: str, me: str) -> list[str]:
    out: list[str] = []
    for u in (ident(api), ident(ingest)):
        out += [
            f"GRANT USAGE ON SCHEMA public TO {u}",
            f"GRANT SELECT, INSERT, UPDATE ON review_items, confirmed_texts TO {u}",
            f"GRANT SELECT, INSERT ON audit_events TO {u}",
            f"GRANT SELECT ON schema_migrations TO {u}",
            f"GRANT USAGE ON SEQUENCE review_item_seq, audit_events_seq_seq TO {u}",
        ]
    # conversation memory (ADR-0029): the API adds turns and reads them; it never edits or deletes
    out += [f"GRANT SELECT, INSERT ON session_owners, session_turns TO {ident(api)}"]
    # draft recovery (ADR-0046): the officer's own workspace, the API's alone (saved, cleared)
    out += [f"GRANT SELECT, INSERT, UPDATE, DELETE ON draft_workspaces TO {ident(api)}"]
    # chat history (ADR-0066): the officer's own conversations; kept, trimmed and deleted by the API
    out += [f"GRANT SELECT, INSERT, UPDATE, DELETE ON chat_conversations, chat_turns TO {ident(api)}"]
    # model usage (ADR-0060 addendum): the API counts and logs optional model calls; the log is
    # append-only for it (no UPDATE / DELETE), the daily count is updated in place
    out += [
        f"GRANT SELECT, INSERT, UPDATE ON model_usage_daily TO {ident(api)}",
        f"GRANT SELECT, INSERT ON model_usage_log TO {ident(api)}",
        f"GRANT USAGE ON SEQUENCE model_usage_log_id_seq TO {ident(api)}",
    ]
    # knowledge graph (ADR-0023): the ingestion job writes it, the API only reads it
    out += [
        f"GRANT SELECT, INSERT, UPDATE ON graph_nodes, graph_edges TO {ident(ingest)}",
        f"GRANT SELECT ON graph_nodes, graph_edges TO {ident(api)}",
    ]
    out += [
        f"GRANT USAGE ON SCHEMA public TO {ident(me)}",
        f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {ident(me)}",
    ]
    return out


def main() -> None:
    cfg = config()
    project, region, prefix = cfg["PROJECT_ID"], cfg["REGION"], cfg["PREFIX"]
    instance = f"{prefix}-sql"
    name = f"{project}:{region}:{instance}"
    db = prefix
    me = gcloud("config", "get-value", "account")
    api, ingest = f"{prefix}-api@{project}.iam", f"{prefix}-ingest@{project}.iam"
    files = sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    plan = grants(api, ingest, me)

    print(f"instance {name}, database {db}, developer {me}")
    print("migrations:", ", ".join(f.stem for f in files))
    for g in plan:
        print("  " + g)
    if not APPLY:
        print("[dry-run] nothing changed. Re-run with APPLY=1.")
        return

    from google.cloud.sql.connector import Connector

    connector = Connector(refresh_strategy="lazy")

    def rotate() -> str:
        # Letters and digits only: a value starting with "-" would be read by gcloud as a flag.
        pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(40))
        gcloud(
            "sql", "users", "set-password", "postgres", "--instance", instance,
            "--project", project, f"--password={pw}", secret=pw,
        )  # fmt: skip
        return pw

    try:
        pw = rotate()
        conn: Any = connector.connect(name, "pg8000", user="postgres", password=pw, db=db)
        try:
            cur = conn.cursor()
            for f in files:
                cur.execute(f.read_text("utf-8"))
                conn.commit()
                print(f"+ applied {f.stem}")
            for g in plan:
                cur.execute(g)
            conn.commit()
            print(f"+ {len(plan)} grants")
        finally:
            conn.close()
    finally:
        rotate()  # leave no usable postgres password behind, even if a step failed
        print("+ postgres password reset to an unseen random value")

    try:
        conn = connector.connect(name, "pg8000", user=me, db=db, enable_iam_auth=True)
    except Exception as exc:
        connector.close()
        sys.exit(
            f"tables are in place, but the IAM login check failed ({type(exc).__name__}). "
            "Check roles/cloudsql.client + roles/cloudsql.instanceUser for you, and "
            "`gcloud auth application-default login`."
        )
    try:
        cur = conn.cursor()
        cur.execute("SELECT version FROM schema_migrations ORDER BY version")
        print("check as", me, "→ migrations:", [r[0] for r in cur.fetchall()])
        cur.execute(
            "SELECT (SELECT count(*) FROM review_items), (SELECT count(*) FROM audit_events)"
        )
        items, events = cur.fetchone()
        print(f"check: review_items={items}, audit_events={events}")
    finally:
        conn.close()
        connector.close()


if __name__ == "__main__":
    main()
