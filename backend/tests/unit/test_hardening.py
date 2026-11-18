"""HTTP hardening (ADR-0039): body limit, no-store and other response headers, request IDs,
API docs only on a developer machine, per-officer request limits."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.testclient import TestClient

from app.auth.rate_limit import RateLimiter
from app.config import Environment, get_settings
from app.main import create_app


def _app(**over: object) -> TestClient:
    return TestClient(create_app(get_settings().model_copy(update={"sandbox": True, **over})))


H = {"X-Sandbox-User": "U01"}


def test_oversized_bodies_are_refused_before_they_are_read() -> None:
    with _app(max_body_bytes=2048) as c:
        big = b'{"message": "' + b"a" * 4000 + b'"}'
        r = c.post("/assist/chat", content=big, headers={**H, "content-type": "application/json"})
        assert r.status_code == 413 and r.json() == {"detail": "The request is too large."}

        def chunks() -> Iterator[bytes]:  # no Content-Length: counted as it arrives
            yield b'{"message": "'
            for _ in range(10):
                yield b"a" * 500
            yield b'"}'

        r2 = c.post(
            "/assist/chat", content=chunks(), headers={**H, "content-type": "application/json"}
        )
        assert r2.status_code == 413
        ok = c.post("/assist/chat", json={"message": "leave encashment precedent"}, headers=H)
        assert ok.status_code == 200


def test_every_response_is_not_stored_and_carries_a_request_id() -> None:
    with _app() as c:
        r = c.post("/assist/chat", json={"message": "Is G.O.Ms.No.88/2022 in force?"}, headers=H)
        for k, v in {
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
            "referrer-policy": "no-referrer",
        }.items():
            assert r.headers[k] == v
        assert r.headers["x-request-id"] == r.json()["request_id"]  # one ID end to end
        kept = c.get("/healthz", headers={"X-Request-ID": "trace-abc-12345"})
        assert kept.headers["x-request-id"] == "trace-abc-12345"
        bad = c.get("/healthz", headers={"X-Request-ID": "x\r\nset-cookie: a"})
        assert (
            bad.headers["x-request-id"] != "x\r\nset-cookie: a" and "set-cookie" not in bad.headers
        )
        assert c.get("/assist/nowhere", headers=H).headers["cache-control"] == "no-store"


def test_api_docs_exist_only_on_a_developer_machine() -> None:
    with _app() as c:
        assert c.get("/docs").status_code == 200
    with _app(env=Environment.GCP, gcp_project_id="p", gcp_region="asia-south1") as c:
        assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404


def test_an_officer_over_the_model_limit_waits_and_is_audited() -> None:
    with _app(rate_model_per_minute=2, rate_any_per_minute=100) as c:
        q = {"message": "leave encashment precedent"}
        codes = [c.post("/assist/chat", json=q, headers=H).status_code for _ in range(3)]
        assert codes == [200, 200, 429]
        r = c.post("/assist/chat", json=q, headers=H)
        assert int(r.headers["retry-after"]) >= 1 and "wait a moment" in r.json()["detail"]
        other = c.post("/assist/chat", json=q, headers={"X-Sandbox-User": "U02"})
        assert other.status_code == 200  # per officer, not global
        cheap = c.post("/assist/file-so-far", json={"computer_no": "1771342"}, headers=H)
        assert cheap.status_code == 200  # the looser tier still has room
        events = [e for e in c.app.state.audit.events() if e.outcome == "rate_limited"]  # type: ignore[attr-defined]
        assert events and events[-1].user_id == "U01"


def test_the_window_slides() -> None:
    now = [0.0]
    lim = RateLimiter(2, 100, clock=lambda: now[0])
    assert lim.check("U01", "assist.chat") is None and lim.check("U01", "assist.chat") is None
    wait = lim.check("U01", "assist.chat")
    assert wait is not None and 59 <= wait <= 60
    now[0] = 60.5
    assert lim.check("U01", "assist.chat") is None


def test_ready_only_once_the_assistant_is_built() -> None:
    with _app() as c:
        assert c.get("/readyz").status_code == 503  # built on first use (no warm start)
        c.post("/assist/search", json={"query": "transfer"}, headers=H)
        assert c.get("/readyz").json() == {"ready": True, "env": "local"}
