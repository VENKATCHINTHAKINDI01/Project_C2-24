"""HTTP guard for every request (ADR-0039): body-size limit, request ID, response headers.

Pure ASGI middleware, so it also covers streamed answers:
- **Body limit.** A request whose declared or actual body exceeds `max_body_bytes` gets 413
  before the app reads it into memory (the officer-facing inputs are short; the largest is an OCR
  correction, well under 1 MiB).
- **Request ID.** Each request gets an ID (a well-formed inbound `X-Request-ID` is kept, so a
  trace can follow the frontend's), stored for the routes and the audit trail, and returned.
- **Failures.** Anything a route did not handle ends with 503 and the neutral message; the log
  gets the path and the error type only (never its text, which can carry query parameters).
- **Response headers.** `Cache-Control: no-store` (answers can carry restricted content: no
  browser or proxy may keep them), `X-Content-Type-Options: nosniff`, `Referrer-Policy:
  no-referrer`, and a `frame-ancestors 'none'` CSP for the API's own responses.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.messages import NEUTRAL_FAILURE

log = logging.getLogger("c2.http")

_RID = re.compile(r"^[A-Za-z0-9-]{8,64}$")
HEADERS = [
    (b"cache-control", b"no-store"),
    (b"pragma", b"no-cache"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"content-security-policy", b"frame-ancestors 'none'"),
    (b"x-mock-sandbox", b"synthetic; not NIC e-Office"),
]
TOO_LARGE = {"detail": "The request is too large."}


# The one route that takes a file: an officer attaching a paper to an e-File (ADR-0045)
_UPLOAD = re.compile(r"^/sandbox/files/[A-Za-z0-9._-]{1,64}/attachments$")


class HttpGuard:
    def __init__(self, app: ASGIApp, max_body_bytes: int, upload_max_bytes: int = 0) -> None:
        self.app = app
        self.default_max = max_body_bytes
        self.upload_max = max(upload_max_bytes, max_body_bytes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        inbound = headers.get(b"x-request-id", b"").decode("latin-1")
        rid = inbound if _RID.match(inbound) else uuid.uuid4().hex[:16]
        scope.setdefault("state", {})["request_id"] = rid
        upload = scope.get("method") == "POST" and _UPLOAD.match(scope.get("path", ""))
        limit = self.upload_max if upload else self.default_max
        declared = headers.get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    await self._reject(send, rid)
                    return
            except ValueError:
                await self._reject(send, rid, 400, {"detail": "Bad request."})
                return
        seen = 0
        started = False
        too_large = False

        async def counted() -> Message:
            # over the limit: tell the app the client went away (frameworks turn errors raised
            # here into 400), then answer 413 ourselves
            nonlocal seen, too_large
            if too_large:
                return {"type": "http.disconnect"}
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit:
                    too_large = True
                    return {"type": "http.disconnect"}
            return msg

        async def guarded(msg: Message) -> None:
            nonlocal started
            if too_large:
                return  # whatever the app answers to a cut-off body is replaced by 413
            if msg["type"] == "http.response.start":
                started = True
                names = {k.lower() for k, _ in msg.get("headers", [])}
                extra = [(k, v) for k, v in HEADERS if k not in names]
                msg["headers"] = [*msg.get("headers", []), *extra, (b"x-request-id", rid.encode())]
            await send(msg)

        try:
            await self.app(scope, counted, guarded)
        except Exception as exc:
            if too_large:
                pass
            else:
                # any unexpected failure ends closed with one neutral message (CLAUDE.md §4.4):
                # only the error's type is logged, never its text (it can carry query text)
                log.error("request failed closed: %s %s", scope.get("path"), type(exc).__name__)
                if not started:
                    await self._reject(send, rid, 503, {"detail": NEUTRAL_FAILURE})
                return
        if too_large and not started:
            await self._reject(send, rid)

    async def _reject(
        self, send: Send, rid: str, status: int = 413, body: dict[str, Any] | None = None
    ) -> None:
        data = json.dumps(body or TOO_LARGE).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(data)).encode()),
                    *HEADERS,
                    (b"x-request-id", rid.encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": data})


# assistant routes that change the in-memory stores themselves: they take the write side inside
_WRITERS = re.compile(r"^/assist/(notices|review/ocr/[^/]+/(confirm|reject))$")


class ReadGate:
    """Holds the runtime's read side for the whole of an assistant request, streamed body
    included, so a change to the in-memory stores never runs under a request that is reading them
    (ADR-0039). Waiting happens on a worker thread, not the event loop."""

    def __init__(self, app: ASGIApp, lock_of: Any) -> None:
        self.app = app
        self.lock_of = lock_of  # () -> RWLock | None (None until the sandbox is built)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "") if scope["type"] == "http" else ""
        lock = self.lock_of() if path.startswith("/assist/") and not _WRITERS.match(path) else None
        if lock is None:
            await self.app(scope, receive, send)
            return
        import anyio.to_thread

        await anyio.to_thread.run_sync(lock.acquire_read)
        try:
            await self.app(scope, receive, send)
        finally:
            lock.release_read()
