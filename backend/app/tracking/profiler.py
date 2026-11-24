"""Opt-in wall-clock profile of chosen API paths (24 Nov 2026; ADR-0060 addendum 3).

A cloud draft took ≈ 270 s while its remote calls added up to ≈ 26 s. To see where the rest goes,
`C2_PROFILE_PATHS=/assist/draft/prepare` makes this middleware sample, every 50 ms, the stack of
the thread that serves such a request and log the code locations it waited in most:

    profile /assist/draft/prepare 270.8 s, 5416 samples:
      182.4 s  67%  noting/draft_studio.py:120 close_matches > … > psycopg/connection.py:connect

Only code locations (file:line function) are logged — never arguments, values or document text
(CLAUDE.md §4.11). Off unless the setting names the path; sampling costs a little CPU on that
request only.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections import Counter
from types import FrameType
from typing import Any

log = logging.getLogger(__name__)

INTERVAL_S = 0.05
TOP = 15
APP_MARK = "/app/"


def _name(f: FrameType, line: bool = True) -> str:
    path = f.f_code.co_filename
    short = path.split(APP_MARK, 1)[1] if APP_MARK in path else "/".join(path.split("/")[-2:])
    return f"{short}:{f.f_lineno} {f.f_code.co_name}" if line else f"{short} {f.f_code.co_name}"


def _where(frame: FrameType | None) -> tuple[str, list[str]] | None:
    """('app frames (innermost three) > leaf', [every app function on the stack]) — where the
    code is, never what it holds; None when no request code is on the stack."""
    stack: list[FrameType] = []
    while frame is not None:
        stack.append(frame)
        frame = frame.f_back
    app = [
        f
        for f in stack
        if APP_MARK in f.f_code.co_filename and "tracking/profiler" not in f.f_code.co_filename
    ]
    if not app:
        return None  # not request code (server loop, other requests' idle threads)
    chain = " > ".join(_name(f) for f in reversed(app[:3]))
    leaf = stack[0]
    spot = chain if leaf is app[0] else f"{chain} > {_name(leaf)}"
    return spot, list(dict.fromkeys(_name(f, line=False) for f in app))


class _Sampler(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True, name="c2-profile")
        self.done = threading.Event()
        self.seen: Counter[str] = Counter()  # exact waiting spots
        self.inclusive: Counter[str] = Counter()  # every app function on the stack
        self.samples = 0
        self.me = threading.get_ident()

    def run(self) -> None:
        while not self.done.wait(INTERVAL_S):
            self.samples += 1
            for ident, frame in sys._current_frames().items():  # noqa: SLF001 — CPython API
                if ident == self.me or ident == self.ident:
                    continue
                if (where := _where(frame)) is not None:
                    self.seen[where[0]] += 1
                    self.inclusive.update(where[1])


class ProfileMiddleware:
    """ASGI: profile requests whose path is listed; every other request passes straight on.
    One profiled request at a time (others run unprofiled), so samples are not mixed."""

    def __init__(self, app: Any, paths: frozenset[str]) -> None:
        self.app = app
        self.paths = paths
        self._busy = threading.Lock()

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        path = scope.get("path", "")
        if (
            scope.get("type") != "http"
            or path not in self.paths
            or not self._busy.acquire(blocking=False)
        ):
            await self.app(scope, receive, send)
            return
        sampler = _Sampler()
        started = time.monotonic()
        sampler.start()
        try:
            await self.app(scope, receive, send)
        finally:
            sampler.done.set()
            sampler.join(timeout=1)
            self._busy.release()
            total = time.monotonic() - started
            n_all = max(sampler.samples, 1)

            def rows(counts: Counter[str]) -> str:
                return "\n".join(
                    f"  {n * INTERVAL_S:7.1f} s {100 * n / n_all:3.0f}%  {where}"
                    for where, n in counts.most_common(TOP)
                )

            log.info(
                "profile %s %.1f s, %d samples\nby step (time inside each app function):\n%s"
                "\nwhere it waited:\n%s",
                path, total, sampler.samples, rows(sampler.inclusive), rows(sampler.seen),
            )  # fmt: skip
