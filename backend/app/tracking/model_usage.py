"""Optional model calls per officer: a daily limit and a usage log (ADR-0060 addendum, plan §10.4).

The limit is enforced on the server against the authenticated officer (the identity the request
was signed in with, never a value the client sends). The count lives in Cloud SQL when state is in
Postgres (`model_usage_daily`, migration 0005), so every API instance and every restart sees the
same count; the increment is one atomic statement, so two requests at once cannot both take the
last call. In the sandbox it lives in memory.

Fail closed: if the count cannot be read or written, the optional call is not made (the draft is
still prepared, and the officer is told the wording is unavailable). Each attempt is logged with
IDs, outcome and counts only — never the officer's text, the prompt or the answer.
"""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from app.pg import Pg

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
WORDING = "draft.wording"
MAX_LOG = 20_000  # in-memory log only: oldest entries dropped first


class UsageEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    at: dt.datetime
    request_id: str
    user_id: str
    action: str
    outcome: str
    engine: str | None = None
    prompt_id: str | None = None
    target: str | None = None
    kept: int = 0
    removed: int = 0
    used_today: int = 0


class UsageUnavailableError(Exception):
    """The count could not be read or written. The caller makes no model call."""


class ModelUsageStore(Protocol):
    def take(self, user_id: str, action: str, day: dt.date, limit: int) -> int | None:
        """Count one call and return the new count, or None when `limit` is already reached."""

    def used(self, user_id: str, action: str, day: dt.date) -> int: ...

    def log(self, entry: UsageEntry) -> None: ...

    def entries(self, since: dt.datetime) -> list[UsageEntry]: ...


class InMemoryModelUsage:
    def __init__(self) -> None:
        self._counts: dict[tuple[str, str, dt.date], int] = {}
        self._log: list[UsageEntry] = []
        self._lock = threading.Lock()

    def take(self, user_id: str, action: str, day: dt.date, limit: int) -> int | None:
        key = (user_id, action, day)
        with self._lock:
            n = self._counts.get(key, 0)
            if n >= limit:
                return None
            self._counts[key] = n + 1
            return n + 1

    def used(self, user_id: str, action: str, day: dt.date) -> int:
        with self._lock:
            return self._counts.get((user_id, action, day), 0)

    def log(self, entry: UsageEntry) -> None:
        with self._lock:
            self._log.append(entry)
            del self._log[:-MAX_LOG]

    def entries(self, since: dt.datetime) -> list[UsageEntry]:
        with self._lock:
            return [e for e in self._log if e.at >= since]


# Fixed statements only; every value is a bound parameter.
_TAKE = (
    "INSERT INTO model_usage_daily (user_id, day, action, calls) VALUES (%s, %s, %s, 1) "
    "ON CONFLICT (user_id, day, action) DO UPDATE SET calls = model_usage_daily.calls + 1 "
    "WHERE model_usage_daily.calls < %s RETURNING calls"
)
_USED = "SELECT calls FROM model_usage_daily WHERE user_id = %s AND day = %s AND action = %s"
_LOG = (
    "INSERT INTO model_usage_log (at, request_id, user_id, action, outcome, engine, prompt_id, "
    "target, kept, removed, used_today) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
)
_SINCE = (
    "SELECT at, request_id, user_id, action, outcome, engine, prompt_id, target, kept, removed, "
    "used_today FROM model_usage_log WHERE at >= %s ORDER BY id LIMIT 20000"
)


class PostgresModelUsage:
    """`model_usage_daily` / `model_usage_log` (migration 0005)."""

    def __init__(self, pg: Pg) -> None:
        self.pg = pg

    def take(self, user_id: str, action: str, day: dt.date, limit: int) -> int | None:
        with self.pg.tx() as cur:
            cur.execute(_TAKE, (user_id, day, action, limit))
            row = cur.fetchone()
        return int(row[0]) if row is not None else None

    def used(self, user_id: str, action: str, day: dt.date) -> int:
        with self.pg.tx() as cur:
            cur.execute(_USED, (user_id, day, action))
            row = cur.fetchone()
        return int(row[0]) if row is not None else 0

    def log(self, entry: UsageEntry) -> None:
        e = entry
        with self.pg.tx() as cur:
            cur.execute(
                _LOG,
                (
                    e.at,
                    e.request_id,
                    e.user_id,
                    e.action,
                    e.outcome,
                    e.engine,
                    e.prompt_id,
                    e.target,
                    e.kept,
                    e.removed,
                    e.used_today,
                ),
            )

    def entries(self, since: dt.datetime) -> list[UsageEntry]:
        with self.pg.tx() as cur:
            cur.execute(_SINCE, (since,))
            rows = cur.fetchall()
        keys = list(UsageEntry.model_fields)
        return [UsageEntry(**dict(zip(keys, r, strict=True))) for r in rows]


class ModelQuota:
    """A daily number of one kind of optional model call per officer (IST days)."""

    def __init__(
        self,
        store: ModelUsageStore,
        per_day: int,
        action: str = WORDING,
        now: Callable[[], dt.datetime] | None = None,
    ) -> None:
        self.store, self.per_day, self.action = store, per_day, action
        self._now = now or (lambda: dt.datetime.now(IST))

    def today(self) -> dt.date:
        return self._now().astimezone(IST).date()

    def take(self, user_id: str) -> int | None:
        """The officer's count after this call, or None past the limit (0: always None).
        Raises `UsageUnavailableError` when the count cannot be kept (the caller fails closed)."""
        if self.per_day <= 0:
            return None
        try:
            return self.store.take(user_id, self.action, self.today(), self.per_day)
        except Exception as exc:  # database errors of many kinds: never make the call uncounted
            raise UsageUnavailableError(type(exc).__name__) from exc

    def used(self, user_id: str) -> int:
        try:
            return self.store.used(user_id, self.action, self.today())
        except Exception as exc:
            raise UsageUnavailableError(type(exc).__name__) from exc

    def log(self, entry: UsageEntry) -> None:
        self.store.log(entry)
