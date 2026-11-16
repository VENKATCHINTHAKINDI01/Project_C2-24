"""Conversation memory in Cloud SQL (plan §10.1; ADR-0029). Same behaviour as `SessionMemory`:
keyed by (user_id, session_id), IDs only, the officer's CURRENT access re-applied on recall.

Only the last `max_turns` turns are read; older rows stay (insert-only for the app account)."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping

from app.auth.models import AccessPolicy, DocumentAccessTags
from app.auth.policy import check
from app.auth.store import AuthzStore
from app.config import Classification
from app.memory.session import SessionError, Turn
from app.pg import Pg

_OWNER = "SELECT user_id FROM session_owners WHERE session_id = %s"
_CLAIM = (
    "INSERT INTO session_owners (session_id, user_id, created_at) VALUES (%s, %s, %s) "
    "ON CONFLICT (session_id) DO NOTHING"
)
_NEXT = "SELECT COALESCE(MAX(seq), 0) + 1 FROM session_turns WHERE session_id = %s"
_ADD = (
    "INSERT INTO session_turns (session_id, seq, request_id, at, canonical_query, entity_ids, "
    "scope_signature) VALUES (%s, %s, %s, %s, %s, %s, %s)"
)
_LAST = (
    "SELECT request_id, at, canonical_query, entity_ids, scope_signature FROM session_turns "
    "WHERE session_id = %s ORDER BY seq DESC LIMIT %s"
)


class PostgresSessionMemory:
    def __init__(self, pg: Pg, max_turns: int = 50) -> None:
        self.pg, self._max = pg, max_turns

    def append(self, user_id: str, session_id: str, turn: Turn) -> None:
        with self.pg.tx() as cur:
            cur.execute(_CLAIM, (session_id, user_id, turn.at))
            cur.execute(_OWNER, (session_id,))
            if cur.fetchone()[0] != user_id:
                raise SessionError("session belongs to another user")
            cur.execute(_NEXT, (session_id,))
            seq = int(cur.fetchone()[0])
            cur.execute(
                _ADD,
                (
                    session_id,
                    seq,
                    turn.request_id,
                    turn.at,
                    turn.canonical_query,
                    json.dumps(list(turn.entity_ids)),
                    turn.scope_signature,
                ),
            )

    def turns(self, user_id: str, session_id: str) -> tuple[Turn, ...]:
        with self.pg.tx() as cur:
            cur.execute(_OWNER, (session_id,))
            row = cur.fetchone()
            if row is not None and row[0] != user_id:
                raise SessionError("session belongs to another user")
            cur.execute(_LAST, (session_id, self._max))
            rows = cur.fetchall()
        return tuple(
            Turn(
                request_id=r[0],
                at=r[1] if isinstance(r[1], dt.datetime) else dt.datetime.fromisoformat(str(r[1])),
                canonical_query=r[2],
                entity_ids=tuple(json.loads(r[3])),
                scope_signature=r[4],
            )
            for r in reversed(rows)
        )

    def recall(
        self,
        user_id: str,
        session_id: str,
        *,
        locations: Mapping[str, DocumentAccessTags],
        store: AuthzStore,
        policy: AccessPolicy,
        classification: Classification,
    ) -> tuple[str, ...]:
        """Entities from earlier turns the officer may STILL see, newest first (re-checked now)."""
        out: list[str] = []
        for turn in reversed(self.turns(user_id, session_id)):
            for eid in turn.entity_ids:
                tags = locations.get(eid)
                if eid in out or tags is None:
                    continue
                if check(user_id, tags, store, policy, classification).allowed:
                    out.append(eid)
        return tuple(out)
