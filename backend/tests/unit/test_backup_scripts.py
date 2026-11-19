"""Cloud SQL backup scripts (ADR-0057): the pure parts — retention arithmetic, price parsing, the
backup freshness and residency check — without calling Google Cloud."""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

GCP = Path(__file__).resolve().parents[3] / "infrastructure" / "gcp"


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), GCP / name)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


backups = _load("29_cloudsql_backups.py")
drill = _load("31_restore_drill.py")


def test_log_window_stays_below_the_14_backups_kept() -> None:
    assert backups.KEEP == 14
    assert backups.log_days("ENTERPRISE") == 7  # the edition's maximum
    assert backups.log_days("ENTERPRISE_PLUS") == 13  # one below the backup count
    assert backups.RESIDENCY == drill.RESIDENCY == "asia-south1"


def test_catalog_prices_per_hour_and_per_month_both_become_per_month() -> None:
    hourly = {"pricingInfo": [{"pricingExpression": {"usageUnit": "GiBy.h", "tieredRates": [
        {"unitPrice": {"units": "0", "nanos": 109589}}]}}]}  # fmt: skip
    monthly = {"pricingInfo": [{"pricingExpression": {"usageUnit": "GiBy.mo", "tieredRates": [
        {"unitPrice": {"units": "6", "nanos": 500000000}}]}}]}  # fmt: skip
    assert backups.per_gib_month(hourly) == pytest.approx(0.08, abs=1e-3)
    assert backups.per_gib_month(monthly) == pytest.approx(6.5)


def _rows(age_h: float, location: str = "asia-south1", status: str = "SUCCESSFUL") -> str:
    at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=age_h)
    rows: list[dict[str, Any]] = [
        {"id": 1, "type": "ON_DEMAND", "status": "SUCCESSFUL", "location": "asia",
         "windowStartTime": "2026-11-18T08:21:00Z"},
        {"id": 2, "type": "AUTOMATED", "status": status, "location": location,
         "windowStartTime": at.isoformat().replace("+00:00", "Z")},
    ]  # fmt: skip
    return json.dumps(rows)


@pytest.mark.parametrize(
    ("age_h", "location", "status", "ok"),
    [
        (3, "asia-south1", "SUCCESSFUL", True),
        (30, "asia-south1", "SUCCESSFUL", False),  # the daily backup stopped
        (3, "asia", "SUCCESSFUL", False),  # outside Mumbai
        (3, "asia-south1", "FAILED", False),  # no successful automated backup
    ],
)
def test_the_daily_check_wants_a_fresh_successful_backup_in_mumbai(
    monkeypatch: pytest.MonkeyPatch, age_h: float, location: str, status: str, ok: bool
) -> None:
    monkeypatch.setattr(drill.kit, "gcloud", lambda *a, **k: _rows(age_h, location, status))
    if ok:
        drill.check_only("c2-sql", "p")
    else:
        with pytest.raises(SystemExit):
            drill.check_only("c2-sql", "p")


def test_the_drill_restores_the_newest_successful_backup() -> None:
    rows = [
        {"id": 1, "status": "SUCCESSFUL", "type": "AUTOMATED", "windowStartTime": "2026-11-17T20"},
        {"id": 2, "status": "FAILED", "type": "AUTOMATED", "windowStartTime": "2026-11-18T20"},
        {"id": 3, "status": "SUCCESSFUL", "type": "ON_DEMAND", "windowStartTime": "2026-11-18T08"},
    ]  # fmt: skip
    assert drill.newest_ok(rows)["id"] == 3
    assert drill.newest_ok(rows, "AUTOMATED")["id"] == 1


# ---- long operations (19 Nov 2026 drill: the clone outlived gcloud's own wait) -----------------


def test_a_long_operation_is_started_async_and_waited_for_without_a_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake(*args: str, secret: str | None = None) -> str:
        calls.append(args)
        return (
            "https://sqladmin.googleapis.com/v1/projects/p/operations/op-123"
            if "--async" in args
            else ""
        )

    monkeypatch.setattr(drill.kit, "gcloud", fake)
    drill.op(
        "sql", "instances", "clone", "c2-sql", "c2-sql-drill-1", "--point-in-time=T", project="p"
    )
    start, wait = calls
    assert start[:3] == ("sql", "instances", "clone") and "--async" in start
    assert wait == ("sql", "operations", "wait", "op-123", "--project", "p", "--timeout=unlimited")


def test_clean_up_waits_for_unfinished_operations_before_deleting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake(*args: str, secret: str | None = None) -> str:
        calls.append(args)
        return "op-a op-b" if args[:3] == ("sql", "operations", "list") else ""

    monkeypatch.setattr(drill.kit, "gcloud", fake)
    drill.settle("c2-sql-drill-1", "p")
    assert ("sql", "operations", "list") == calls[0][:3] and "--filter=status!=DONE" in calls[0]
    assert [c[3] for c in calls[1:]] == ["op-a", "op-b"]
    assert all("--timeout=unlimited" in c for c in calls[1:])


def test_an_operation_without_a_name_stops_the_drill(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drill.kit, "gcloud", lambda *a, secret=None: "")
    with pytest.raises(SystemExit, match="no operation name"):
        drill.op("sql", "backups", "restore", "1", project="p")


def test_the_clone_patch_only_lifts_deletion_protection() -> None:
    """19 Nov 2026: the API refuses --no-backup while PITR is on, and gcloud refuses --no-backup
    with the PITR flag in one patch. The clone keeps both; only deletion protection is lifted."""
    src = (GCP / "31_restore_drill.py").read_text("utf-8")
    code = "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith("#"))
    assert "--no-backup" not in code and "point-in-time-recovery" not in code
    assert code.count('"--no-deletion-protection"') == 2  # after the clone, and before the delete


def test_a_backup_older_than_a_migration_is_not_a_failure() -> None:
    """Last night's backup predates 0005 (applied 19 Nov morning): its two tables are absent."""
    by = drill.tables_by_migration()
    assert by["0005_model_usage"] == {"model_usage_daily", "model_usage_log"}
    src = {"graph_nodes": 5, "graph_edges": 9, "model_usage_daily": 0, "model_usage_log": 0,
           "audit_events": 3}  # fmt: skip
    v5 = {f"000{i}_x" for i in range(1, 5)} | {"0005_model_usage"}
    back = {"graph_nodes": 5, "graph_edges": 9, "audit_events": 2}
    v4 = v5 - {"0005_model_usage"}
    assert drill.backup_findings(src, v5, back, v4, by) == []
    # the same tables missing while the backup records 0005 as applied: a real failure
    assert drill.backup_findings(src, v5, back, v5, by) == [
        "backup restore: table model_usage_daily missing",
        "backup restore: table model_usage_log missing",
    ]
    lost = drill.backup_findings(src, v5, {"graph_nodes": 5, "graph_edges": 0}, v4, by)
    assert "backup restore: table audit_events missing" in lost
    assert "backup restore: graph tables empty" in lost
    assert drill.backup_findings(src, v4, back, v5, by)[0].startswith(
        "backup restore: migrations the source does not have"
    )
