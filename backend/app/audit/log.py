"""Audit trail of assistant requests (plan §10.4; CLAUDE.md §4.11).

Records who asked what kind of thing, the access outcome and the IDs involved — never document
text, note bodies or the question itself. In-memory reference store; BigQuery / Cloud SQL later.
"""

from __future__ import annotations

import datetime as dt
import itertools
import threading

from pydantic import BaseModel, ConfigDict, Field


class AuditEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int
    at: dt.datetime
    request_id: str
    user_id: str | None
    action: str  # e.g. "assist.search", "assist.presend", "draft.created"
    outcome: str  # "ok" | "denied" | "not_available" | "no_answer" | "error"
    ids: tuple[str, ...] = ()  # canonical IDs / computer numbers / draft IDs — never text
    detail: str = Field(default="", max_length=200)  # short, non-sensitive


class AuditLog:
    """In-memory audit trail (sandbox, tests). Bounded (ADR-0039): past `max_events` the oldest
    go. A real deployment keeps the trail in Cloud SQL (`PostgresAuditLog`), unbounded."""

    def __init__(self, max_events: int = 200_000) -> None:
        self._max = max_events
        self._events: list[AuditEvent] = []
        self._seq = itertools.count(1)
        self._lock = threading.Lock()

    def record(
        self,
        request_id: str,
        user_id: str | None,
        action: str,
        outcome: str,
        ids: tuple[str, ...] = (),
        detail: str = "",
    ) -> AuditEvent:
        with self._lock:
            ev = AuditEvent(
                seq=next(self._seq),
                at=dt.datetime.now(dt.UTC),
                request_id=request_id,
                user_id=user_id,
                action=action,
                outcome=outcome,
                ids=ids,
                detail=detail[:200],
            )
            self._events.append(ev)
            if len(self._events) > self._max * 1.1:
                del self._events[: len(self._events) - self._max]
            return ev

    def events(self) -> tuple[AuditEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def refused_since(self, since: dt.datetime) -> tuple[AuditEvent, ...]:
        """Refused requests ("denied" / "not_available") from `since` on, for the monitoring
        pad's alerts (ADR-0036)."""
        with self._lock:
            return tuple(
                e
                for e in self._events
                if e.at >= since and e.outcome in ("denied", "not_available")
            )
