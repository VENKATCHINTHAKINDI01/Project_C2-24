"""Conversation / session memory with scope rules (plan §10.1; CLAUDE.md §4.6, §4.9, §4.11).

- Keyed by (user_id, session_id): a session is never shared; another user cannot read it.
- Holds IDs and metadata only (canonical query, entity IDs, scope signature) — never document text.
- Current scope is re-applied on EVERY turn: entities remembered from earlier turns are re-checked
  against the officer's current grants before reuse ("that precedent"), and silently dropped if
  no longer permitted — a mid-session revocation applies immediately.
In-memory reference store; the LangGraph Postgres checkpointer implements the same behaviour
(not Redis, CLAUDE.md §2.3).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.auth.models import AccessPolicy, DocumentAccessTags
from app.auth.policy import check
from app.auth.store import AuthzStore
from app.config import Classification


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Turn(_Frozen):
    request_id: str
    at: dt.datetime
    canonical_query: str = Field(max_length=1000)
    entity_ids: tuple[str, ...] = ()  # canonical IDs / file numbers used in this turn
    scope_signature: str | None


class SessionError(Exception):
    """Wrong owner or unknown session: callers start a fresh session, never borrow one."""


class SessionMemory:
    """Reference store keyed by (user_id, session_id)."""

    def __init__(self, max_turns: int = 50) -> None:
        self._sessions: dict[tuple[str, str], list[Turn]] = {}
        self._owner: dict[str, str] = {}
        self._max = max_turns

    def append(self, user_id: str, session_id: str, turn: Turn) -> None:
        owner = self._owner.setdefault(session_id, user_id)
        if owner != user_id:
            raise SessionError("session belongs to another user")
        turns = self._sessions.setdefault((user_id, session_id), [])
        turns.append(turn)
        del turns[: max(0, len(turns) - self._max)]

    def turns(self, user_id: str, session_id: str) -> tuple[Turn, ...]:
        if self._owner.get(session_id, user_id) != user_id:
            raise SessionError("session belongs to another user")
        return tuple(self._sessions.get((user_id, session_id), ()))

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
        """Entities from earlier turns that the officer may STILL see, newest first.

        `locations` maps an entity ID to its document tags (from the metadata store). Unknown
        entities and anything not allowed now are dropped without comment (no existence hint).
        """
        out: list[str] = []
        for turn in reversed(self.turns(user_id, session_id)):
            for eid in turn.entity_ids:
                tags = locations.get(eid)
                if eid in out or tags is None:
                    continue
                if check(user_id, tags, store, policy, classification).allowed:
                    out.append(eid)
        return tuple(out)
