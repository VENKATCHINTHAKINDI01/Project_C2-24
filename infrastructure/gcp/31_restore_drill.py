"""Prove the Cloud SQL backups can be restored (ADR-0057): a restore drill, not just a backup list.

"A backup that has never been successfully restored is not a tested recovery strategy" (owner,
18 Nov 2026). This drill restores into a THROWAWAY clone in asia-south1, checks the data, and
deletes the clone. The production instance is never written to (only its `postgres` password is
rotated to an unseen value, as in 12/16, so the row counts can be read).

Run from backend/:

    CHECK_ONLY=1 env -u VIRTUAL_ENV uv run python ../infrastructure/gcp/31_restore_drill.py
        no cost: the latest successful automated backup is in asia-south1 and under 26 h old
    env -u VIRTUAL_ENV uv run python ../infrastructure/gcp/31_restore_drill.py
        dry run: prints the plan
    APPLY=1 I_ACCEPT_COST=1 env -u VIRTUAL_ENV uv run python \
        ../infrastructure/gcp/31_restore_drill.py
        the drill (bills a clone of the instance's tier for roughly 30-60 minutes)

The drill:
1. Counts the rows of every table in the database (c1), notes the time T, counts again (c2).
2. Point-in-time recovery: clones the instance as it was at T into `<prefix>-sql-drill-<stamp>`
   (same region). Pass: every table is there and each count lies between c1 and c2.
3. Backup restore: restores the newest successful backup into the same clone (overwriting it).
   Pass: every table is there, the migrations match, the graph tables are not empty.
4. Deletes the clone (only an instance this run created, named `<prefix>-sql-drill-*`), unless
   KEEP_DRILL=1. Prints how long each restore took (the recovery time) and writes the result to
   infrastructure/gcp/restore-drill-<date>.out.txt (git-ignored) for PROGRESS.md.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import re
import secrets
import string
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))
_spec = importlib.util.spec_from_file_location("schema12", HERE / "12_cloudsql_schema.py")
assert _spec and _spec.loader
kit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kit)

APPLY = os.environ.get("APPLY") == "1"
RESIDENCY = "asia-south1"
MAX_AGE = dt.timedelta(hours=26)  # a daily backup plus its window


def backups(instance: str, project: str) -> list[dict[str, Any]]:
    out = kit.gcloud(
        "sql", "backups", "list", "--instance", instance, "--project", project, "--format=json"
    )
    return list(json.loads(out))


def newest_ok(rows: list[dict[str, Any]], kind: str | None = None) -> dict[str, Any] | None:
    ok = [
        b
        for b in rows
        if b.get("status") == "SUCCESSFUL" and (kind is None or b.get("type") == kind)
    ]
    return max(ok, key=lambda b: b.get("windowStartTime", ""), default=None)


def check_only(instance: str, project: str) -> None:
    b = newest_ok(backups(instance, project), "AUTOMATED")
    if b is None:
        sys.exit("✗ no successful automated backup yet")
    at = dt.datetime.fromisoformat(b["windowStartTime"].replace("Z", "+00:00"))
    age = dt.datetime.now(dt.UTC) - at
    print(
        f"latest automated backup {b['id']}: {at:%Y-%m-%d %H:%M} UTC ({age}), {b.get('location')}"
    )
    if b.get("location") != RESIDENCY:
        sys.exit(f"✗ stored in {b.get('location')!r}, not {RESIDENCY}")
    if age > MAX_AGE:
        sys.exit(f"✗ older than {MAX_AGE}: the daily backup is not running")
    print("✓ backups current and in Mumbai")


def op(*args: str, project: str) -> None:
    """A long Cloud SQL operation, started without blocking and then waited for with no time
    limit. `gcloud sql instances clone` / `backups restore` give up waiting after a fixed time
    while the operation goes on (19 Nov 2026 drill: a 9-minute clone outlived the wait)."""
    name = kit.gcloud(*args, "--project", project, "--async", "--format=value(name)")
    name = name.strip().rsplit("/", 1)[-1]
    if not name:
        sys.exit(f"gcloud {args[0]} {args[1]} {args[2]}: no operation name returned")
    print(f"  waiting for operation {name} …", flush=True)
    kit.gcloud("sql", "operations", "wait", name, "--project", project, "--timeout=unlimited")


def settle(instance: str, project: str) -> None:
    """Wait for every unfinished operation on `instance` (a clone or restore still running is
    why a delete is refused)."""
    pending = kit.gcloud("sql", "operations", "list", "--instance", instance, "--project",
                         project, "--filter=status!=DONE", "--format=value(name)")  # fmt: skip
    for name in pending.split():
        print(f"  waiting for unfinished operation {name} on {instance} …", flush=True)
        kit.gcloud("sql", "operations", "wait", name, "--project", project, "--timeout=unlimited")


def password(instance: str, project: str) -> str:
    pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(40))
    kit.gcloud(
        "sql", "users", "set-password", "postgres", "--instance", instance, "--project", project,
        f"--password={pw}", secret=pw,
    )  # fmt: skip
    return pw


def counts(connect: Callable[[], Any]) -> dict[str, int]:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
            "AND table_type = 'BASE TABLE' ORDER BY table_name"
        )
        tables = [r[0] for r in cur.fetchall()]
        out = {}
        for t in tables:
            cur.execute(f"SELECT count(*) FROM {kit.ident(t)}")  # noqa: S608 — catalog names, checked
            out[t] = int(cur.fetchone()[0])
        return out
    finally:
        conn.close()


MIGRATIONS = HERE.parents[1] / "data" / "schemas" / "postgres"
_CREATE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-z_][a-z0-9_]*)", re.I)


def tables_by_migration(directory: Path = MIGRATIONS) -> dict[str, set[str]]:
    """The tables each migration creates (`0005_model_usage` → {model_usage_daily, …})."""
    return {
        f.stem: {m.lower() for m in _CREATE.findall(f.read_text("utf-8"))}
        for f in sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    }


def versions(connect: Callable[[], Any]) -> set[str]:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT version FROM schema_migrations")
        return {str(r[0]) for r in cur.fetchall()}
    finally:
        conn.close()


def backup_findings(
    source_counts: dict[str, int],
    source_versions: set[str],
    restored_counts: dict[str, int],
    restored_versions: set[str],
    by_migration: dict[str, set[str]],
) -> list[str]:
    """What is wrong with a restored backup. A backup is older than the source, so a migration
    applied since it was taken (and the tables it creates) is expected to be absent; anything
    else missing, or a migration the source never had, is a failure."""
    out: list[str] = []
    unknown = restored_versions - source_versions
    if unknown:
        out.append(f"backup restore: migrations the source does not have: {sorted(unknown)}")
    later = source_versions - restored_versions
    expected_absent = set().union(*(by_migration.get(v, set()) for v in later)) if later else set()
    for table in source_counts:
        if table not in restored_counts and table not in expected_absent:
            out.append(f"backup restore: table {table} missing")
    if not restored_counts.get("graph_nodes") or not restored_counts.get("graph_edges"):
        out.append("backup restore: graph tables empty")
    return out


def main() -> None:  # noqa: PLR0915 — one linear runbook, kept in one place on purpose
    cfg = kit.config()
    project, region, prefix = cfg["PROJECT_ID"], cfg["REGION"], cfg["PREFIX"]
    src = f"{prefix}-sql"
    if region != RESIDENCY:
        sys.exit(f"REGION is {region}, not {RESIDENCY}: stop (data residency)")
    if os.environ.get("CHECK_ONLY") == "1":
        check_only(src, project)
        return
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%d%H%M")
    drill = f"{prefix}-sql-drill-{stamp}"
    print(f"plan: count {project}:{region}:{src}; PITR clone → {drill}; restore newest backup "
          f"into {drill}; compare; delete {drill}")  # fmt: skip
    if not APPLY:
        print("[dry-run] nothing done. APPLY=1 I_ACCEPT_COST=1 runs the drill (bills the clone).")
        return
    if os.environ.get("I_ACCEPT_COST") != "1":
        sys.exit("the clone bills while it exists: re-run with I_ACCEPT_COST=1 APPLY=1")

    from google.cloud.sql.connector import Connector

    connector = Connector(refresh_strategy="lazy")
    report: list[str] = [f"restore drill {stamp} — {project}:{region}:{src}"]
    failed: list[str] = []
    created = False
    error: BaseException | None = None  # the first failure: reported before any clean-up
    try:
        pw = password(src, project)
        try:

            def on_src() -> Any:
                return connector.connect(f"{project}:{region}:{src}", "pg8000", user="postgres",
                                         password=pw, db=prefix)  # fmt: skip

            c1 = counts(on_src)
            v_src = versions(on_src)
            point = dt.datetime.now(dt.UTC).replace(microsecond=0)
            time.sleep(2)
            c2 = counts(on_src)
        finally:
            password(src, project)  # reset to an unseen value straight away
        report.append(f"source counts at {point:%Y-%m-%dT%H:%M:%SZ}: {c1}")

        t = time.time()
        print(f"+ PITR clone {src} → {drill} at {point:%Y-%m-%dT%H:%M:%SZ}")
        created = True  # from here on, a clone may exist and is cleaned up
        op("sql", "instances", "clone", src, drill,
           f"--point-in-time={point:%Y-%m-%dT%H:%M:%SZ}", project=project)  # fmt: skip
        pitr_s = time.time() - t
        d = json.loads(kit.gcloud("sql", "instances", "describe", drill, "--project", project,
                                  "--format=json"))  # fmt: skip
        if d["region"] != RESIDENCY:
            failed.append(f"clone landed in {d['region']}")
        # only deletion protection is lifted, so the clean-up can delete the clone. Backups and
        # PITR, inherited from the source, are left as they are: the clone lives under an hour,
        # and switching them off failed twice (19 Nov 2026: the API refuses --no-backup while
        # PITR is on; gcloud refuses --no-backup with the PITR flag in the same patch)
        op("sql", "instances", "patch", drill, "--no-deletion-protection", "--quiet",
           project=project)  # fmt: skip
        dpw = password(drill, project)

        def on_drill() -> Any:
            return connector.connect(f"{project}:{region}:{drill}", "pg8000", user="postgres",
                                     password=dpw, db=prefix)  # fmt: skip

        got = counts(on_drill)
        for table in sorted(set(c1) | set(c2) | set(got)):
            lo, hi = sorted((c1.get(table, -1), c2.get(table, -1)))
            if table not in got or not lo <= got[table] <= hi:
                failed.append(f"PITR {table}: {got.get(table)} not within {lo}..{hi}")
        report.append(f"PITR restore: {pitr_s / 60:.1f} min; counts {got}")

        rows = backups(src, project)
        b = newest_ok(rows)
        if b is None:
            failed.append("no successful backup to restore")
        else:
            if b.get("location") != RESIDENCY:
                failed.append(f"backup {b['id']} is stored in {b.get('location')!r}")
            t = time.time()
            print(
                f"+ restore backup {b['id']} ({b.get('type')}, "
                f"{b.get('windowStartTime')}) → {drill}"
            )
            op("sql", "backups", "restore", str(b["id"]), "--restore-instance", drill,
               "--backup-instance", src, "--quiet", project=project)  # fmt: skip
            restore_s = time.time() - t
            dpw = password(drill, project)  # the restore brought back the backup's users
            again = counts(on_drill)
            v_back = versions(on_drill)
            failed += backup_findings(c2, v_src, again, v_back, tables_by_migration())
            if v_src - v_back:
                report.append(
                    f"backup predates migration(s) {sorted(v_src - v_back)} (expected: applied "
                    "after the backup was taken)"
                )
            report.append(
                f"backup restore ({b['id']}, {b.get('type')}, {b.get('windowStartTime')}, "
                f"{b.get('location')}): {restore_s / 60:.1f} min; counts {again}"
            )
    except BaseException as exc:  # noqa: BLE001 — kit.gcloud exits with SystemExit; keep it
        error = exc
        failed.append(f"drill stopped: {exc}")
        print(f"✗ drill stopped: {exc}", file=sys.stderr, flush=True)  # before any clean-up
    finally:
        connector.close()
        if created and os.environ.get("KEEP_DRILL") != "1":
            assert drill.startswith(f"{prefix}-sql-drill-")  # never anything else
            try:
                exists = kit.gcloud("sql", "instances", "list", "--project", project,
                                    f"--filter=name={drill}", "--format=value(name)")  # fmt: skip
                if exists:
                    settle(drill, project)  # a clone or restore still running cannot be deleted
                    print(f"+ delete throwaway clone {drill}")
                    op("sql", "instances", "patch", drill, "--no-deletion-protection", "--quiet",
                       project=project)  # fmt: skip
                    op("sql", "instances", "delete", drill, "--quiet", project=project)
                    report.append(f"clone {drill} deleted")
                # the clone inherits "keep backups after delete" from the source: none should
                # exist (it lives under an hour, outside the backup window), but say so if any do
                left = kit.gcloud("sql", "backups", "list", "--instance=-", "--project", project,
                                  f"--filter=instance={drill}", "--format=value(id)")  # fmt: skip
                if left.split():
                    failed.append(f"backups of the deleted clone remain (billed): {left.split()}")
            except BaseException as exc:  # noqa: BLE001
                failed.append(f"clean-up failed: {exc}")
                report.append(
                    f"CLONE {drill} MAY STILL EXIST AND BILL: delete it by hand "
                    f"(gcloud sql instances delete {drill} --project {project})"
                )
    report.append("RESULT: " + ("PASS" if not failed else "FAIL — " + "; ".join(failed)))
    out = HERE / f"restore-drill-{stamp[:8]}.out.txt"
    out.write_text("\n".join(report) + "\n", "utf-8")
    print("\n".join(report))
    print(f"written: {out}")
    if error is not None and not isinstance(error, (SystemExit, Exception)):
        raise error  # KeyboardInterrupt and the like, after clean-up
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
