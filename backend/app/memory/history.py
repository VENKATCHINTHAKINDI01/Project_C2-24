"""Chat history: each officer's conversations with the assistant, kept by the server (ADR-0066).

The officer sees their earlier conversations again after closing the panel, reloading or signing
in again, and a conversation continues where it stopped (the same session, so "that order" still
finds what it found before, re-checked; plan §10.1).

- **The officer's own, never shared:** keyed by (user_id, conversation_id). Another officer asking
  for the same id gets nothing, exactly like an id that does not exist.
- **Re-checked on every read** (CLAUDE.md §4.6, §4.9): the route opens a file conversation only
  while the officer can still open the file, and withholds any stored answer that cites a record
  the officer may no longer see. A file's own answers (movements, summary, …) are not stored at
  all: only the question and which tool answered it; they are read again when shown.
- **Not a record and not a log:** never read by ingestion, search, the query log or analytics.
  The officer can delete a conversation.
- **Kept by the server**, not the browser: answers quote records, and an office machine is often
  shared. In memory by default; in Postgres (`chat_conversations`, `chat_turns`) when a database is
  configured, so it survives a restart. Bounded per officer.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from collections import OrderedDict
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.pg import Pg

ALL = "all"  # the general conversation (top bar), as opposed to a file's Computer No.
MAX_CONVERSATIONS = 30  # per officer: the oldest goes first
MAX_TURNS = 60  # per conversation: the oldest goes first
MAX_ANSWER_BYTES = 200_000


class HistTurn(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    at: dt.datetime
    asked: str = Field(max_length=500)
    kind: Literal["chat", "tool"]
    tool: str | None = Field(default=None, pattern=r"^[a-z_]{1,40}$")  # kind == "tool"
    answer: dict[str, Any] | None = None  # kind == "chat": the answer as it was shown
    cited: tuple[str, ...] = ()  # canonical IDs the answer cites (re-checked on read)


class Conversation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: str
    place: str  # a file's Computer No., or ALL
    title: str
    updated_at: dt.datetime
    turns: tuple[HistTurn, ...] = ()


def cited_ids(answer: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(c.get("canonical_id"))
            for key in ("statements", "review_needed")
            for st in answer.get(key) or []
            for c in st.get("citations") or []
        )
    )


def fit(answer: dict[str, Any]) -> dict[str, Any] | None:
    """The answer to keep, without parts that only made sense at the moment (a first-cut preview
    tied to that request); None when it is too large to keep."""
    kept = {k: v for k, v in answer.items() if k not in {"first_cut"}}
    return kept if len(json.dumps(kept, default=str)) <= MAX_ANSWER_BYTES else None


class ChatHistory(Protocol):
    def add(self, user_id: str, conversation_id: str, place: str, turn: HistTurn) -> None: ...
    def list(self, user_id: str, place: str | None) -> list[Conversation]: ...  # no turns
    def get(self, user_id: str, conversation_id: str) -> Conversation | None: ...
    def delete(self, user_id: str, conversation_id: str) -> bool: ...
    def clear(self, user_id: str) -> int: ...  # every conversation of this officer


class InMemoryChatHistory:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by: OrderedDict[tuple[str, str], Conversation] = OrderedDict()
        self._owner: dict[str, str] = {}

    def add(self, user_id: str, conversation_id: str, place: str, turn: HistTurn) -> None:
        with self._lock:
            if self._owner.setdefault(conversation_id, user_id) != user_id:
                return  # another officer's id: never written into, never hinted at
            key = (user_id, conversation_id)
            old = self._by.pop(key, None)
            turns = (*(old.turns if old else ()), turn)[-MAX_TURNS:]
            self._by[key] = Conversation(
                conversation_id=conversation_id,
                place=old.place if old else place,
                title=old.title if old else turn.asked[:120],
                updated_at=turn.at,
                turns=turns,
            )
            mine = [k for k in self._by if k[0] == user_id]
            for k in mine[: max(0, len(mine) - MAX_CONVERSATIONS)]:  # oldest first
                del self._by[k]
                self._owner.pop(k[1], None)

    def list(self, user_id: str, place: str | None) -> list[Conversation]:
        with self._lock:
            mine = [
                c.model_copy(update={"turns": ()})
                for (u, _), c in self._by.items()
                if u == user_id and (place is None or c.place == place)
            ]
        return sorted(mine, key=lambda c: c.updated_at, reverse=True)

    def get(self, user_id: str, conversation_id: str) -> Conversation | None:
        with self._lock:
            return self._by.get((user_id, conversation_id))

    def delete(self, user_id: str, conversation_id: str) -> bool:
        with self._lock:
            gone = self._by.pop((user_id, conversation_id), None) is not None
            if gone:
                self._owner.pop(conversation_id, None)
            return gone

    def clear(self, user_id: str) -> int:
        with self._lock:
            mine = [k for k in self._by if k[0] == user_id]
            for k in mine:
                del self._by[k]
                self._owner.pop(k[1], None)
            return len(mine)


class PostgresChatHistory:
    """`chat_conversations` + `chat_turns` (migration 0006); the API's alone."""

    def __init__(self, pg: Pg) -> None:
        self.pg = pg

    def add(self, user_id: str, conversation_id: str, place: str, turn: HistTurn) -> None:
        with self.pg.tx() as cur:
            cur.execute(
                "INSERT INTO chat_conversations (conversation_id, user_id, place, title, "
                "updated_at) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (conversation_id) DO NOTHING",
                (conversation_id, user_id, place, turn.asked[:120], turn.at),
            )
            cur.execute(
                "UPDATE chat_conversations SET updated_at = %s "
                "WHERE conversation_id = %s AND user_id = %s",
                (turn.at, conversation_id, user_id),
            )
            if not cur.rowcount:
                return  # another officer's id
            cur.execute(
                "INSERT INTO chat_turns (conversation_id, seq, body) SELECT %s, "
                "COALESCE(MAX(seq), 0) + 1, %s FROM chat_turns WHERE conversation_id = %s",
                (conversation_id, turn.model_dump_json(), conversation_id),
            )
            cur.execute(
                "DELETE FROM chat_turns WHERE conversation_id = %s AND seq <= "
                "(SELECT MAX(seq) FROM chat_turns WHERE conversation_id = %s) - %s",
                (conversation_id, conversation_id, MAX_TURNS),
            )
            cur.execute(
                "DELETE FROM chat_conversations WHERE user_id = %s AND conversation_id IN ("
                "SELECT conversation_id FROM chat_conversations WHERE user_id = %s "
                "ORDER BY updated_at DESC OFFSET %s)",
                (user_id, user_id, MAX_CONVERSATIONS),
            )

    def list(self, user_id: str, place: str | None) -> list[Conversation]:
        with self.pg.tx() as cur:
            cur.execute(
                "SELECT conversation_id, place, title, updated_at FROM chat_conversations "
                "WHERE user_id = %s AND (%s::text IS NULL OR place = %s) ORDER BY updated_at DESC",
                (user_id, place, place),
            )
            rows = cur.fetchall()
        return [
            Conversation(conversation_id=r[0], place=r[1], title=r[2], updated_at=r[3])
            for r in rows
        ]

    def get(self, user_id: str, conversation_id: str) -> Conversation | None:
        with self.pg.tx() as cur:
            cur.execute(
                "SELECT place, title, updated_at FROM chat_conversations "
                "WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, user_id),
            )
            head = cur.fetchone()
            if head is None:
                return None
            cur.execute(
                "SELECT body FROM chat_turns WHERE conversation_id = %s ORDER BY seq",
                (conversation_id,),
            )
            turns = tuple(HistTurn.model_validate_json(r[0]) for r in cur.fetchall())
        return Conversation(
            conversation_id=conversation_id,
            place=head[0],
            title=head[1],
            updated_at=head[2],
            turns=turns,
        )

    def delete(self, user_id: str, conversation_id: str) -> bool:
        with self.pg.tx() as cur:
            cur.execute(
                "DELETE FROM chat_conversations WHERE conversation_id = %s AND user_id = %s",
                (conversation_id, user_id),
            )
            return bool(cur.rowcount)

    def clear(self, user_id: str) -> int:
        with self.pg.tx() as cur:
            cur.execute("DELETE FROM chat_conversations WHERE user_id = %s", (user_id,))
            return int(cur.rowcount or 0)
