"""Cloud SQL backups and point-in-time recovery for the C2-24 instance (ADR-0057; plan §14.4).

Owner configuration (18 Nov 2026): daily automated backups, 14 kept, point-in-time recovery,
deletion protection, backup-failure alerts (30_backup_alerts.sh), restore drills
(31_restore_drill.py)
— and every backup kept in Mumbai (asia-south1), never in the default "asia" multi-region.

Run from backend/ (dry run by default: reads the instance and prices, changes nothing):

    env -u VIRTUAL_ENV uv run python ../infrastructure/gcp/29_cloudsql_backups.py
    APPLY=1 RESTART_OK=1 env -u VIRTUAL_ENV uv run python \
        ../infrastructure/gcp/29_cloudsql_backups.py

What it does:
1. Reads the instance (edition, region, disk, current backup settings) and refuses to go on if the
   instance itself is not in asia-south1.
2. Prints the residency of every existing backup. A backup outside asia-south1 is reported, never
   deleted (the owner decides; the command to delete it is printed).
3. Prices the change from the Cloud Billing Catalog (asia-south1 SKUs, INR and USD) and the disk the
   database uses now (Cloud Monitoring): the extra monthly cost, low and high estimates.
4. With APPLY=1: one `gcloud sql instances patch` — backup window 20:30 UTC (02:00 IST), backup
   location asia-south1, 14 backups kept, PITR with the longest log window the edition allows that
   stays below the backup count (Enterprise 7 days, Enterprise Plus 13), deletion protection, and
   backups kept if the instance is ever deleted (--retain-backups-on-delete).
   Enabling PITR RESTARTS the instance (a short outage): RESTART_OK=1 is required.
5. Reads the instance back and checks every setting took.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("schema12", HERE / "12_cloudsql_schema.py")
assert _spec and _spec.loader
kit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kit)

APPLY = os.environ.get("APPLY") == "1"
RESIDENCY = "asia-south1"  # Mumbai: the only place C2-24 data may be stored
KEEP = 14  # automated backups kept (owner)
WINDOW_UTC = "20:30"  # 02:00 IST, outside office hours
CLOUD_SQL_SERVICE = "9662-B51E-5089"  # Cloud Billing Catalog service id of Cloud SQL
HOURS_PER_MONTH = 730


def log_days(edition: str) -> int:
    """PITR log retention must be below the backup count; Enterprise allows at most 7 days."""
    return 7 if edition != "ENTERPRISE_PLUS" else KEEP - 1


def api(url: str) -> dict[str, Any]:
    token = kit.gcloud("auth", "print-access-token")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 — fixed Google API host
        return dict(json.loads(r.read()))


def skus(currency: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    token = ""
    while True:
        q = urllib.parse.urlencode({"currencyCode": currency, "pageSize": 5000, "pageToken": token})
        page = api(f"https://cloudbilling.googleapis.com/v1/services/{CLOUD_SQL_SERVICE}/skus?{q}")
        out += [s for s in page.get("skus", []) if RESIDENCY in s.get("serviceRegions", [])]
        token = page.get("nextPageToken", "")
        if not token:
            return out


def per_gib_month(sku: dict[str, Any]) -> float:
    """The SKU's list price per GiB-month (the catalog prices storage per GiB-hour or -month)."""
    expr = sku["pricingInfo"][0]["pricingExpression"]
    rate = expr["tieredRates"][-1]["unitPrice"]
    price = float(int(rate.get("units", 0)) + int(rate.get("nanos", 0)) / 1e9)
    unit = expr.get("usageUnit", "")
    return price * HOURS_PER_MONTH if unit.endswith(".h") else price


def disk_used_gib(project: str, instance: str) -> float | None:
    end = dt.datetime.now(dt.UTC)
    q = urllib.parse.urlencode(
        {
            "filter": 'metric.type="cloudsql.googleapis.com/database/disk/bytes_used" AND '
            f'resource.labels.database_id="{project}:{instance}"',
            "interval.startTime": (end - dt.timedelta(hours=2)).isoformat(),
            "interval.endTime": end.isoformat(),
        }
    )
    series = api(f"https://monitoring.googleapis.com/v3/projects/{project}/timeSeries?{q}")
    points = [p for s in series.get("timeSeries", []) for p in s.get("points", [])]
    if not points:
        return None
    return max(int(p["value"].get("int64Value", 0)) for p in points) / 2**30


def price_report(project: str, instance: str, edition: str, disk_gib: int) -> None:
    used = disk_used_gib(project, instance)
    print(
        f"database disk in use: {used:.2f} GiB of {disk_gib} GiB provisioned"
        if used is not None
        else "database disk in use: unknown (no Monitoring points in the last 2 h)"
    )
    for currency in ("INR", "USD"):
        rows = skus(currency)
        backup = [s for s in rows if "backup" in s["description"].lower()]
        if not backup:
            print(f"[{currency}] no asia-south1 backup SKU found in the catalog: check by hand")
            continue
        for s in backup:
            print(f"[{currency}] {s['description']}: {per_gib_month(s):.4f} per GiB-month")
        price = max(per_gib_month(s) for s in backup)
        if used is not None:
            # backups after the first are incremental: about one copy of the data plus 14 days of
            # changes. Low: one copy. High: KEEP full copies (a database rewritten every day).
            low, high = used * price, used * KEEP * price
            print(
                f"[{currency}] extra per month for backups: about {low:.2f} (low) to "
                f"{high:.2f} (high, {KEEP} full copies)"
            )
    print(
        f"PITR ({edition}): transaction logs for {log_days(edition)} days are kept on the "
        "instance's own disk in its own region (no separate charge while the provisioned disk has "
        "room; if storage auto-increase grows the disk, the extra GiB bill at the SSD rate)"
    )


def main() -> None:
    cfg = kit.config()
    project, region, prefix = cfg["PROJECT_ID"], cfg["REGION"], cfg["PREFIX"]
    instance = f"{prefix}-sql"
    if region != RESIDENCY:
        sys.exit(f"config REGION is {region}, not {RESIDENCY}: stop (data residency)")
    d = json.loads(
        kit.gcloud("sql", "instances", "describe", instance, "--project", project, "--format=json")
    )
    st, bc = d["settings"], d["settings"].get("backupConfiguration", {})
    edition = st.get("edition", "ENTERPRISE")
    print(
        f"{project}:{d['region']}:{instance} — {d['databaseVersion']}, {edition}, tier "
        f"{st['tier']}, disk {st.get('dataDiskSizeGb')} GiB {st.get('dataDiskType')}, "
        f"auto-increase {st.get('storageAutoResize')}"
    )
    print(
        f"now: backups {bc.get('enabled', False)} at {bc.get('startTime')}, location "
        f"{bc.get('location') or 'default multi-region'}, kept "
        f"{bc.get('backupRetentionSettings', {}).get('retainedBackups')}, PITR "
        f"{bc.get('pointInTimeRecoveryEnabled', False)} "
        f"({bc.get('transactionLogRetentionDays')} days), deletion protection "
        f"{st.get('deletionProtectionEnabled', False)}"
    )
    if d["region"] != RESIDENCY:
        sys.exit(f"the instance is in {d['region']}, not {RESIDENCY}: stop (data residency)")

    backups = json.loads(
        kit.gcloud(
            "sql", "backups", "list", "--instance", instance, "--project", project,
            "--format=json",
        )
    )  # fmt: skip
    outside = [b for b in backups if b.get("location") != RESIDENCY]
    for b in backups:
        print(f"  backup {b['id']} {b.get('type')} {b.get('status')} {b.get('windowStartTime')} "
              f"location={b.get('location')}")  # fmt: skip
    for b in outside:
        print(
            f"  ! backup {b['id']} is stored in {b.get('location')!r}, outside {RESIDENCY}. Owner "
            "decision: once an in-region backup has succeeded and been restored, delete it with\n"
            f"    gcloud sql backups delete {b['id']} --instance {instance} --project {project}"
        )

    price_report(project, instance, edition, int(st.get("dataDiskSizeGb", 0)))

    days = log_days(edition)
    patch = [
        "sql", "instances", "patch", instance, "--project", project,
        f"--backup-start-time={WINDOW_UTC}",
        f"--backup-location={RESIDENCY}",
        f"--retained-backups-count={KEEP}",
        "--enable-point-in-time-recovery",
        f"--retained-transaction-log-days={days}",
        "--deletion-protection",
        "--retain-backups-on-delete",
        "--quiet",
    ]  # fmt: skip
    if not APPLY:
        print("[dry-run] gcloud " + " ".join(patch))
        print(
            "[dry-run] nothing changed. Re-run with APPLY=1 RESTART_OK=1 "
            "(enabling PITR restarts the instance)."
        )
        return
    if os.environ.get("RESTART_OK") != "1" and not bc.get("pointInTimeRecoveryEnabled"):
        sys.exit("enabling PITR restarts the instance: re-run with RESTART_OK=1 when that is fine")
    print("+ gcloud " + " ".join(patch))
    kit.gcloud(*patch)

    a = json.loads(
        kit.gcloud("sql", "instances", "describe", instance, "--project", project, "--format=json")
    )
    abc = a["settings"]["backupConfiguration"]
    checks = {
        "automated backups on": abc.get("enabled") is True,
        f"window {WINDOW_UTC} UTC": abc.get("startTime") == WINDOW_UTC,
        f"location {RESIDENCY}": abc.get("location") == RESIDENCY,
        f"{KEEP} backups kept": abc.get("backupRetentionSettings", {}).get("retainedBackups")
        == KEEP,
        "PITR on": abc.get("pointInTimeRecoveryEnabled") is True,
        f"{days} days of logs": abc.get("transactionLogRetentionDays") == days,
        "deletion protection": a["settings"].get("deletionProtectionEnabled") is True,
    }
    print(
        f"  · backups kept on delete: {a['settings'].get('retainBackupsOnDelete', 'not reported')}"
    )
    for name, ok in checks.items():
        print(f"  {'✓' if ok else '✗'} {name}")
    if not all(checks.values()):
        sys.exit("some settings did not take: see ✗ above")
    print("+ backups configured. Next: 30_backup_alerts.sh, then 31_restore_drill.py")


if __name__ == "__main__":
    main()
