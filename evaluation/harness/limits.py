"""Settings every evaluation run that drives the API in-process must use (ADR-0039, ADR-0050
addendum 4).

The per-officer request limits refuse a burst with HTTP 429. An evaluation that asks hundreds of
questions as one simulated officer would otherwise score refusals as "nothing found" or "nothing
disclosed": a run that measured nothing (seen 18 Nov: pre-send A 0/23). The limits are not what
these runs measure; the limiter has its own tests (tests/unit/test_hardening.py).
"""

from __future__ import annotations

from collections.abc import Iterable

NO_RATE_LIMITS = {"rate_model_per_minute": 1_000_000, "rate_any_per_minute": 1_000_000}


class RefusedError(RuntimeError):
    """A run whose requests were refused or failed measured nothing for them."""


def require_measured(statuses: Iterable[int], what: str) -> None:
    """Fail the run if any request was rate-limited (429) or failed (5xx)."""
    bad = sorted({s for s in statuses if s == 429 or s >= 500})
    if bad:
        raise RefusedError(f"{what}: requests refused or failed with HTTP {bad}; nothing measured")
