"""C2-24 frontend on Cloud Run (plan §2.1, §11; ADR-0032).

Serves the built mock e-Office screens (frontend/eoffice/dist) and forwards the API paths to the
private c2-api service, adding a Google ID token minted for THIS service's own account
(c2-frontend, run.invoker on c2-api). The browser never holds a token for c2-api, and any
Authorization header it sends is dropped. People reach this service only through IAP.

Nothing here decides access: c2-api authorises every call (sandbox profile, scope, re-check).
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route

log = logging.getLogger("c2.frontend")

API_PREFIXES = ("/assist/", "/sandbox/", "/healthz")
# request headers passed on to c2-api; everything else (cookies, Authorization, IAP's own
# headers) stays here
FORWARD_IN = ("content-type", "accept", "x-sandbox-user")
FORWARD_OUT = ("content-type", "content-disposition", "x-c2-sandbox")
SECURITY = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "content-security-policy": (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "frame-src 'self' blob:; object-src 'self' blob:; frame-ancestors 'self'; base-uri 'none'"
    ),
}


class IdTokens:
    """ID tokens for one audience, refreshed a few minutes before they expire (1 h)."""

    def __init__(self, audience: str, fetch: Callable[[str], str] | None = None) -> None:
        self._audience = audience
        self._fetch = fetch or _fetch_id_token
        self._token, self._until = "", 0.0
        self._lock = threading.Lock()

    def get(self) -> str:
        with self._lock:
            if time.time() >= self._until:
                self._token = self._fetch(self._audience)
                self._until = time.time() + 50 * 60
            return self._token


def _fetch_id_token(audience: str) -> str:
    import google.auth.transport.requests
    import google.oauth2.id_token

    return str(
        google.oauth2.id_token.fetch_id_token(google.auth.transport.requests.Request(), audience)
    )


def build_app(
    web_dir: Path,
    api_url: str,
    tokens: IdTokens | None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Starlette:
    web = web_dir.resolve()
    # c2-api builds its sandbox on the first call after idle (minutes): wait for it
    client = httpx.AsyncClient(
        base_url=api_url.rstrip("/"), timeout=httpx.Timeout(900.0), transport=transport
    )

    async def proxy(request: Request) -> Response:
        headers = {k: v for k, v in request.headers.items() if k.lower() in FORWARD_IN}
        if tokens is not None:
            headers["authorization"] = f"Bearer {tokens.get()}"
        try:
            up = await client.send(
                client.build_request(
                    request.method,
                    request.url.path,
                    params=request.query_params,
                    headers=headers,
                    content=await request.body(),
                ),
                stream=True,  # answers stream through as they are written (ADR-0033)
            )
        except httpx.HTTPError as exc:
            log.error("c2-api unreachable: %s", type(exc).__name__)
            return PlainTextResponse("The assistant is not reachable just now.", status_code=502)
        out = {k: v for k, v in up.headers.items() if k.lower() in FORWARD_OUT}
        if up.headers.get("content-type", "").startswith("text/event-stream"):
            out["cache-control"] = "no-cache"
            out["x-accel-buffering"] = "no"
        return StreamingResponse(
            up.aiter_bytes(),  # decoded: content-encoding is not passed on
            status_code=up.status_code,
            headers={**out, **SECURITY},
            background=BackgroundTask(up.aclose),
        )

    async def page(request: Request) -> Response:
        rel = request.path_params.get("path", "")
        target = (web / rel).resolve()
        if rel and target.is_relative_to(web) and target.is_file():
            return FileResponse(target, headers=SECURITY)
        # the app's own routes are client-side: every other path gets the page
        return FileResponse(web / "index.html", headers={**SECURITY, "cache-control": "no-store"})

    methods = ["GET", "POST", "PUT", "DELETE"]
    routes = [Route("/healthz", proxy, methods=["GET"])]
    routes += [Route(p + "{rest:path}", proxy, methods=methods) for p in API_PREFIXES[:2]]
    routes += [Route("/{path:path}", page, methods=["GET"])]

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        yield
        await client.aclose()

    return Starlette(routes=routes, lifespan=lifespan)


def from_env() -> Starlette:
    api_url = os.environ["C2_API_URL"]  # the c2-api service URL; fail at start if missing
    web_dir = Path(os.environ.get("C2_WEB_DIR", "/srv/web"))
    tokens = None if os.environ.get("C2_API_NO_AUTH") == "1" else IdTokens(api_url)
    return build_app(web_dir, api_url, tokens)
