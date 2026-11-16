"""Audit trail in PostgreSQL (plan §10.4; CLAUDE.md §4.11). IDs and outcomes only, never text.

The table is append-only: a trigger refuses UPDATE and DELETE (schema 0001). If a write fails, the
request fails: an action that cannot be audited does not happen silently.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from app.audit.log import AuditEvent, AuditLog
from app.pg import Pg

# Fixed statements only; every value is a bound parameter.
_INSERT = "INSERT INTO audit_events (at, request_id, user_id, action, outcome, ids, detail) \
VALUES (%s, %s, %s, %s, %s, %s, %s) \
RETURNING seq, at, request_id, user_id, action, outcome, ids, detail"
_ALL = "SELECT seq, at, request_id, user_id, action, outcome, ids, detail FROM audit_events \
ORDER BY seq"
_REFUSED = "SELECT seq, at, request_id, user_id, action, outcome, ids, detail FROM audit_events \
WHERE at >= %s AND outcome IN ('denied', 'not_available') ORDER BY seq LIMIT 20000"


def _event(row: Any) -> AuditEvent:
    return AuditEvent(
        seq=int(row[0]),
        at=row[1],
        request_id=row[2],
        user_id=row[3],
        action=row[4],
        outcome=row[5],
        ids=tuple(row[6] or ()),
        detail=row[7],
    )


class PostgresAuditLog(AuditLog):
    def __init__(self, pg: Pg) -> None:
        self.pg = pg

    def record(
        self,
        request_id: str,
        user_id: str | None,
        action: str,
        outcome: str,
        ids: tuple[str, ...] = (),
        detail: str = "",
    ) -> AuditEvent:
        with self.pg.tx() as cur:
            now = dt.datetime.now(dt.UTC)
            cur.execute(
                _INSERT, (now, request_id, user_id, action, outcome, list(ids), detail[:200])
            )
            return _event(cur.fetchone())

    def events(self) -> tuple[AuditEvent, ...]:
        with self.pg.tx() as cur:
            cur.execute(_ALL)
            return tuple(_event(r) for r in cur.fetchall())

    def refused_since(self, since: dt.datetime) -> tuple[AuditEvent, ...]:
        with self.pg.tx() as cur:
            cur.execute(_REFUSED, (since,))
            return tuple(_event(r) for r in cur.fetchall())
