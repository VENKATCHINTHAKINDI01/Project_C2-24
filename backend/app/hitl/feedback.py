"""Feedback capture: every human action on an assistant output is one record (plan §9.2, §10.4;
CLAUDE.md §8; ADR-0031).

What is recorded: who acted, on which assistant output (its request ID = the query log's
`query_id`), on which records (canonical IDs, Computer Nos., draft / note IDs), what they did, a
fixed reason code, and — for a confirmed Yellow Note — how much of the AI's text the officer
changed (`edit_share`, a number). Never any text: not the question, not the draft, not the
officer's edits, not a free-text reason.

Feedback is evaluation data in the PoC. Nothing here changes retrieval, conflict rules, prompts
or access — no code path reads these records back (CLAUDE.md §8 "never silently use it").
"""

from __future__ import annotations

import datetime as dt
import difflib
import logging
import re
import uuid
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.connectors.eoffice import DraftOutcome, DraftOutcomeKind
from app.tracking.retry_buffer import RetryBuffer

log = logging.getLogger(__name__)


class TargetKind(StrEnum):
    ANSWER = "answer"  # a whole answer in the conversation
    STATEMENT = "statement"  # one cited statement / one precedent
    CONFLICT_FLAG = "conflict_flag"  # a pre-send / brief / DFA flag
    YELLOW_NOTE = "yellow_note"  # an inserted AI first-cut, confirmed or discarded in e-Office
    DFA_DRAFT = "dfa_draft"
    SUGGESTED_REFERENCE = "suggested_reference"
    ALERT = "alert"  # a monitoring alert, reviewed by a monitoring officer (ADR-0036)


class Action(StrEnum):
    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    ACCEPTED = "accepted"  # a conflict flag the officer agrees needs review
    DISMISSED = "dismissed"  # a conflict flag the officer sets aside
    CONFIRMED = "confirmed"  # Yellow Note confirmed (Green) without changing the AI's words
    CONFIRMED_EDITED = "confirmed_edited"  # confirmed after the officer changed it
    DISCARDED = "discarded"  # draft thrown away
    REVIEWED = "reviewed"  # a monitoring officer looked at an alert: nothing further (ADR-0036)
    ESCALATED = "escalated"  # ... and marked it for the department's own procedure


class Reason(StrEnum):
    """Fixed codes only — a free-text reason could carry restricted content."""

    WRONG_SOURCE = "wrong_source"
    NOT_RELEVANT = "not_relevant"
    OUTDATED = "outdated"
    INCOMPLETE = "incomplete"
    NOT_APPLICABLE = "not_applicable"
    ALREADY_HANDLED = "already_handled"
    EXPECTED_ACTIVITY = "expected_activity"  # an alert on work the officer was doing (ADR-0036)
    OTHER = "other"


class HumanAction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str
    ts: dt.datetime
    user_id: str
    query_id: str  # request ID of the assistant output acted on (joins the query log)
    target_kind: TargetKind
    target_ids: tuple[str, ...] = Field(default=(), max_length=10)
    action: Action
    reason: Reason | None = None
    flag_type: str | None = Field(default=None, pattern=r"^[A-G]$")
    edit_share: float | None = Field(default=None, ge=0.0, le=1.0)


# What the assistant writes to mark its drafts as drafts (noting agent ADR-0030, first-cut points
# ADR-0019 era, pre-send points). True while it is a draft, false once the officer confirms it.
_DRAFT_MARKERS = (
    (re.compile(r"(?m)^[ \t]*(?:AI FIRST-CUT|FIRST-CUT NOTE —)[^\n]*\n?"), ""),
    (re.compile(r" \(C2-24 pre-send check, draft\)"), ""),
    (re.compile(r"(?m)^[ \t]*DRAFT(?: NOTE)? — prepared with C2-24 Assist\.[^\n]*\n?"), ""),
)


def strip_watermark(text: str) -> str:
    """The assistant's draft markers ("not a note until signed") go when the officer confirms,
    and removing them is not counted as the officer's edit."""
    for rx, repl in _DRAFT_MARKERS:
        text = rx.sub(repl, text)
    return text.strip()


def edit_share(ai_text: str, final_text: str) -> float:
    """Share of the AI's words the officer changed: 0.0 = confirmed as drafted, 1.0 = nothing
    of the draft kept. Word-level, whitespace-insensitive, watermark ignored."""
    a = strip_watermark(ai_text).split()
    b = strip_watermark(final_text).split()
    if not a and not b:
        return 0.0
    return round(1.0 - difflib.SequenceMatcher(None, a, b, autojunk=False).ratio(), 4)


class ActionLog(Protocol):
    def write(self, action: HumanAction) -> None: ...


class InMemoryActionLog:
    """Reference log (sandbox default, tests)."""

    def __init__(self, max_rows: int = 50_000) -> None:
        self.actions: list[HumanAction] = []
        self._max = max_rows  # bounded memory (ADR-0039): the oldest rows go first

    def write(self, action: HumanAction) -> None:
        self.actions.append(action)
        if len(self.actions) > self._max * 1.1:
            del self.actions[: len(self.actions) - self._max]


def bq_row(a: HumanAction) -> dict[str, Any]:
    row = a.model_dump(mode="json")
    row["target_ids"] = list(a.target_ids)
    return row


class BigQueryActionLog:
    """Streaming insert into `<project>.<prefix>_audit.human_action` (schema:
    data/schemas/bigquery/human_action.json). Append-only: the latest action per output wins in
    the `query_log_actions` view (script 22). A failed insert is kept and retried (RetryBuffer,
    plan §14.4): the officer's action in e-Office has already happened; tracking must not undo
    it."""

    def __init__(self, project: str, table: str, client: Any | None = None) -> None:
        if client is None:
            from google.cloud import bigquery  # lazy: unit tests never need the client

            client = bigquery.Client(project=project)
        self._client = client
        self._table = table
        self.buffer = RetryBuffer(
            "human_action", lambda rows: self._client.insert_rows_json(self._table, rows)
        )

    def write(self, action: HumanAction) -> None:
        self.buffer.write(bq_row(action))


def action_from_outcome(out: DraftOutcome) -> HumanAction:
    """What the officer did in e-Office with an assistant draft → one feedback record."""
    if out.outcome is DraftOutcomeKind.DISCARDED:
        act = Action.DISCARDED
    elif out.edit_share is not None and out.edit_share > 0:
        act = Action.CONFIRMED_EDITED
    else:
        act = Action.CONFIRMED
    return HumanAction(
        action_id=uuid.uuid4().hex[:16],
        ts=out.at,
        user_id=out.user_id,
        query_id=out.request_id or "",
        target_kind=TargetKind(out.kind.value),
        target_ids=tuple(x for x in (out.computer_no, out.draft_id, out.note_id) if x),
        action=act,
        edit_share=out.edit_share,
    )
