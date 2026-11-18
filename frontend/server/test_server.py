"""Frontend server: static screens + an authenticated pass-through to c2-api (ADR-0032).
Run with the backend environment:  cd backend && uv run pytest ../frontend/server"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from server import IdTokens, build_app
from starlette.testclient import TestClient


@pytest.fixture
def web(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>sandbox</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path.parent / "secret.txt").write_text("not for the web")
    return tmp_path


def _client(
    web: Path, seen: list[httpx.Request], status: int = 200, extra: dict[str, str] | None = None
) -> TestClient:
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(
            status,
            content=b'{"ok": true}',
            headers={
                "content-type": "application/json",
                "set-cookie": "x=1",
                "server": "u",
                **(extra or {}),
            },
        )

    tokens = IdTokens("https://c2-api", fetch=lambda aud: f"token-for-{aud}")
    app = build_app(web, "https://c2-api", tokens, transport=httpx.MockTransport(handler))
    return TestClient(app)


def test_api_calls_carry_this_services_token_never_the_browsers(web: Path) -> None:
    seen: list[httpx.Request] = []
    r = _client(web, seen).post(
        "/assist/chat?x=1",
        json={"message": "hi"},
        headers={
            "X-Sandbox-User": "V14",
            "Authorization": "Bearer from-the-browser",
            "Cookie": "GCP_IAP_UID=abc",
            "X-Goog-IAP-JWT-Assertion": "jwt",
        },
    )
    assert r.status_code == 200 and r.json() == {"ok": True}
    (req,) = seen
    assert str(req.url) == "https://c2-api/assist/chat?x=1"
    assert req.headers["authorization"] == "Bearer token-for-https://c2-api"
    assert req.headers["x-sandbox-user"] == "V14"
    assert "cookie" not in req.headers and "x-goog-iap-jwt-assertion" not in req.headers
    assert req.headers["x-c2-iap-assertion"] == "jwt"  # verified by c2-api itself (ADR-0039)
    assert "set-cookie" not in r.headers and r.headers["x-content-type-options"] == "nosniff"


def test_no_store_request_id_and_retry_after_reach_the_browser(web: Path) -> None:
    """Found by the container check (ADR-0043): these were dropped, so a browser could keep an
    authorised answer in its cache and an officer over the limit got no Retry-After."""
    seen: list[httpx.Request] = []
    api = {
        "cache-control": "no-store",
        "pragma": "no-cache",
        "x-request-id": "abc12345",
        "retry-after": "7",
    }
    r = _client(web, seen, status=429, extra=api).post(
        "/assist/chat", json={"message": "hi"}, headers={"X-Request-ID": "trace-0001"}
    )
    assert r.status_code == 429
    for k, v in api.items():
        assert r.headers[k] == v
    assert seen[0].headers["x-request-id"] == "trace-0001"  # the API validates its format


def test_errors_and_files_pass_through_unchanged(web: Path) -> None:
    seen: list[httpx.Request] = []
    r = _client(web, seen, status=404).get("/assist/documents/X", headers={"X-Sandbox-User": "V1"})
    assert r.status_code == 404


def test_screens_are_served_and_unknown_paths_get_the_page(web: Path) -> None:
    c = _client(web, [])
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert c.get("/").text == "<html>sandbox</html>"
    assert c.get("/files/2894562").text == "<html>sandbox</html>"  # client-side route
    assert "not for the web" not in c.get("/../secret.txt").text
    assert "not for the web" not in c.get("/%2e%2e/secret.txt").text


def test_tokens_are_reused_until_near_expiry() -> None:
    calls: list[str] = []
    t = IdTokens("aud", fetch=lambda a: calls.append(a) or "t")
    assert t.get() == t.get() == "t" and calls == ["aud"]


def test_a_streamed_answer_passes_through_as_it_comes(web: Path) -> None:
    body = b"event: stage\ndata: {}\n\nevent: done\ndata: {}\n\n"

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream; charset=utf-8"}
        )

    tokens = IdTokens("https://c2-api", fetch=lambda aud: "t")
    app = build_app(web, "https://c2-api", tokens, transport=httpx.MockTransport(handler))
    with TestClient(app).stream("POST", "/assist/chat/stream", json={"message": "x"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-cache"
        assert b"".join(r.iter_raw()) == body
