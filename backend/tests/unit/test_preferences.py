"""Officer preferences (ADR-0041): per officer, validated, and never a way to change access."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

H1, H2 = {"X-Sandbox-User": "U01"}, {"X-Sandbox-User": "U02"}


def _client() -> TestClient:
    return TestClient(create_app(get_settings().model_copy(update={"sandbox": True})))


def test_defaults_save_and_reset_per_officer() -> None:
    with _client() as c:
        first = c.get("/sandbox/me/preferences", headers=H1).json()
        assert first["text_size"] == "normal" and first["landing"] == "inbox"
        saved = c.post(
            "/sandbox/me/preferences",
            json={**first, "text_size": "large", "landing": "search", "due_soon_days": 7},
            headers=H1,
        )
        assert saved.status_code == 200 and saved.json()["text_size"] == "large"
        assert c.get("/sandbox/me/preferences", headers=H1).json()["landing"] == "search"
        assert c.get("/sandbox/me/preferences", headers=H2).json() == first  # not shared
        assert c.post("/sandbox/me/preferences/reset", headers=H1).json() == first
        assert c.get("/sandbox/me/preferences", headers=H1).json() == first


def test_unknown_or_out_of_range_values_are_refused() -> None:
    with _client() as c:
        base = c.get("/sandbox/me/preferences", headers=H1).json()
        before = c.get("/sandbox/me", headers=H1).json()
        for bad in (
            {"clearance": "SECRET"},  # access is not a preference
            {"search_scopes": ["ALL"]},
            {"text_size": "huge"},
            {"due_soon_days": 99},
            {"landing": "admin"},
        ):
            r = c.post("/sandbox/me/preferences", json={**base, **bad}, headers=H1)
            assert r.status_code == 422, bad
        assert c.get("/sandbox/me", headers=H1).json() == before  # profile and access unchanged
        assert c.get("/sandbox/me/preferences", headers=H1).json() == base


def test_not_signed_in_gets_nothing() -> None:
    with _client() as c:
        assert c.get("/sandbox/me/preferences").status_code == 401
        assert c.post("/sandbox/me/preferences", json={}).status_code == 401
