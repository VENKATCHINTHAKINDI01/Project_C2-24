"""Per-officer request limits (plan §4 abuse resistance; ADR-0039).

A sliding one-minute window per officer and tier, in this instance's memory: the model-backed
actions (answers, drafts, checks) have a tight limit because each one costs a model call; every
other assistant action has a looser one. Over the limit the request is refused with 429 and a
`Retry-After`, before any retrieval or model call, and the refusal is audited. Not a substitute for
an edge limit (Cloud Armor is out of PoC scope, CLAUDE.md §2.3): it keeps one officer, a stuck
script or a runaway client from spending the model quota or starving the others on an instance.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

MODEL_BACKED = frozenset(
    {
        "assist.chat",
        "assist.ask",
        "assist.presend",
        "assist.draft.prepare",  # pre-send check + optional Gemini wording
        "assist.first_cut",
        "assist.dfa",
        "assist.brief",
        "assist.receipt",
    }
)
MAX_KEYS = 10_000  # bounded memory: the oldest officer windows are dropped first


class RateLimiter:
    def __init__(
        self,
        model_per_minute: int,
        any_per_minute: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limits = {"model": model_per_minute, "any": any_per_minute}
        self._clock = clock
        self._hits: dict[tuple[str, str], deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, user_id: str, action: str) -> float | None:
        """None if allowed (and counted); else the seconds until the next request is allowed."""
        tiers = ("model", "any") if action in MODEL_BACKED else ("any",)
        now = self._clock()
        with self._lock:
            for tier in tiers:
                q = self._hits.get((user_id, tier))
                if q is None:
                    continue
                while q and now - q[0] >= 60.0:
                    q.popleft()
                if len(q) >= self.limits[tier]:
                    return max(1.0, 60.0 - (now - q[0]))
            for tier in tiers:
                key = (user_id, tier)
                if key not in self._hits:
                    if len(self._hits) >= MAX_KEYS:
                        self._hits.pop(next(iter(self._hits)))
                    self._hits[key] = deque()
                self._hits[key].append(now)
        return None
