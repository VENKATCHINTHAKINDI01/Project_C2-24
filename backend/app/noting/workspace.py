"""Draft recovery: an officer's draft workspace, kept by the server as they work (ADR-0046).

A power cut, a dropped network or a closed tab must not cost the officer their draft. The screen
saves its state here a moment after each change; opening Draft again puts the officer back
exactly where they were: the format, their inputs, the draft with their edits, the references
they added or removed, the earlier files they ticked.

- **One per officer and target:** a file's Computer No., or "new" for a matter with no file yet.
  Never shared: another officer asking for the same file gets nothing.
- **Not a record:** a workspace is scratch, not a draft on the file, and never enters
  institutional memory or any search. Saving it into the file (Yellow Note / DFA) clears it.
- **Access re-checked on every restore** by the route (the file must still be open to the
  officer). Restoring re-prepares the records beside the draft under the officer's access TODAY;
  their own text is kept as they left it.
- **Kept by the server**, not the browser: draft text can carry restricted content, and an
  office machine is often shared. In memory by default; in Postgres (`draft_workspaces`) when a
  database is configured, so it survives a restart of the service too.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from typing import Annotated, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.pg import Pg

NEW_MATTER = "new"
RecordRef = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9#.()/_-]{1,120}$")]
FileNo = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9./-]{1,64}$")]


class WorkspaceInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    subject: str = Field(default="", max_length=500)
    request: str = Field(default="", max_length=4000)
    facts: str = Field(default="", max_length=4000)
    proposal: str = Field(default="", max_length=4000)
    signatory: str = Field(default="", max_length=4000)
    addressees: str = Field(default="", max_length=4000)
    copy_to: str = Field(default="", max_length=4000)


class Workspace(BaseModel):
    """What the officer had on screen. Only their own choices and words: the records beside the
    draft are worked out again on restore, under their access at that moment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,40}$")
    inputs: WorkspaceInputs = WorkspaceInputs()
    suggest: bool = False
    added: tuple[RecordRef, ...] = Field(default=(), max_length=20)
    dropped: tuple[RecordRef, ...] = Field(default=(), max_length=40)
    previous_references: tuple[FileNo, ...] = Field(default=(), max_length=20)  # new matter only
    prepared: bool = False  # a draft had been prepared (restore prepares again, keeping `text`)
    text: str = Field(default="", max_length=40_000)  # the draft as the officer last edited it


class Saved(BaseModel):
    model_config = ConfigDict(frozen=True)

    workspace: Workspace
    saved_at: dt.datetime


class WorkspaceStore(Protocol):
    def get(self, user_id: str, target: str) -> Saved | None: ...
    def put(self, user_id: str, target: str, ws: Workspace, at: dt.datetime) -> Saved: ...
    def discard(self, user_id: str, target: str) -> bool: ...


class InMemoryWorkspaceStore:
    """Per (officer, target); bounded per officer so a stuck client cannot grow it forever."""

    MAX_PER_OFFICER = 50

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by: dict[tuple[str, str], Saved] = {}

    def get(self, user_id: str, target: str) -> Saved | None:
        with self._lock:
            return self._by.get((user_id, target))

    def put(self, user_id: str, target: str, ws: Workspace, at: dt.datetime) -> Saved:
        saved = Saved(workspace=ws, saved_at=at)
        with self._lock:
            self._by.pop((user_id, target), None)
            self._by[(user_id, target)] = saved
            mine = [k for k in self._by if k[0] == user_id]
            for k in mine[: max(0, len(mine) - self.MAX_PER_OFFICER)]:  # oldest first
                del self._by[k]
        return saved

    def discard(self, user_id: str, target: str) -> bool:
        with self._lock:
            return self._by.pop((user_id, target), None) is not None


class PostgresWorkspaceStore:
    """`draft_workspaces` (migration 0004). The officer's own words are stored here, as in e-Office
    a saved draft is; the table is the API's alone and never read by ingestion or search."""

    def __init__(self, pg: Pg) -> None:
        self.pg = pg

    def get(self, user_id: str, target: str) -> Saved | None:
        with self.pg.tx() as cur:
            cur.execute(
                "SELECT body, saved_at FROM draft_workspaces WHERE user_id = %s AND target = %s",
                (user_id, target),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return Saved(workspace=Workspace.model_validate(json.loads(row[0])), saved_at=row[1])

    def put(self, user_id: str, target: str, ws: Workspace, at: dt.datetime) -> Saved:
        with self.pg.tx() as cur:
            cur.execute(
                "INSERT INTO draft_workspaces (user_id, target, body, saved_at) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT (user_id, target) "
                "DO UPDATE SET body = EXCLUDED.body, saved_at = EXCLUDED.saved_at",
                (user_id, target, ws.model_dump_json(), at),
            )
        return Saved(workspace=ws, saved_at=at)

    def discard(self, user_id: str, target: str) -> bool:
        with self.pg.tx() as cur:
            cur.execute(
                "DELETE FROM draft_workspaces WHERE user_id = %s AND target = %s",
                (user_id, target),
            )
            return bool(cur.rowcount)
