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
