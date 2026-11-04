"""Service boots with valid config and exposes only non-sensitive health data."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_reports_config_versions() -> None:
    body = TestClient(create_app()).get("/healthz").json()
    assert body["status"] == "ok"
    assert body["env"] == "local"
    assert set(body) == {
        "status",
        "env",
        "hierarchy_version",
        "classification_version",
        "runtime_config_version",
    }
