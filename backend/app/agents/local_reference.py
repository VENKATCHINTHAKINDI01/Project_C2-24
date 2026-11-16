"""Local reference — touchpoint 10 (plan §11.5): the officer cites an order (and a paragraph);
the assistant says whether it is superseded and shows the provision. Deterministic.

Built on the status tool, so the coverage rule holds (owner, 3 Nov 2026): supersession by an order
the officer may see is stated; "current" is claimed only with full coverage.
- The cited paragraph: its own text from the cited order.
- When the order was superseded: the SAME paragraph number in the superseding order, shown side
  by side and labelled "check it covers the same point". It is never presented as the current
  provision unless the status tool itself returned `current_version`.
A paragraph that is absent, or appears more than once, is not shown (never guessed).
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from app.agents.tools import ToolResult
from app.identifiers.canonical import InvalidCanonicalIdError, clause_id
from app.ingestion.clauses import clause_text, paragraph_label

SAME_NUMBER = (
    "Same paragraph number in the order that superseded it — check it covers the same point."
)


class ClauseText(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    clause_id: str
    text: str


class LocalReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    paragraph: str | None  # locator the officer named, e.g. "2.v"
    cited_clause: ClauseText | None
    successor_clause: ClauseText | None
    successor_is_current: bool  # True only when the status tool confirmed the current version
    note: str | None


def _clause(cid: str, locator: str, text_of: Callable[[str], str]) -> ClauseText | None:
    body = clause_text(text_of(cid), locator)
    if body is None:
        return None
    try:
        return ClauseText(clause_id=clause_id(cid, locator), text=body)
    except InvalidCanonicalIdError:
        return None


def local_reference(
    request: str, cited: str, status: ToolResult, text_of: Callable[[str], str]
) -> LocalReference:
    """`cited`: the order the officer may see (from the scoped lookup); `status`: its status-tool
    result; `text_of`: indexed text by canonical ID (only `cited` and `status.by` are read)."""
    loc = paragraph_label(request)
    if loc is None or not status.available:
        return LocalReference(
            paragraph=loc,
            cited_clause=None,
            successor_clause=None,
            successor_is_current=False,
            note=None,
        )
    own = _clause(cited, loc, text_of)
    succ = None
    is_current = False
    if status.status == "superseded" and status.by:
        succ = _clause(status.by, loc, text_of)
        is_current = succ is not None and status.current_version == status.by
    note = None
    if succ is not None and not is_current:
        note = SAME_NUMBER
    elif own is None and succ is None:
        note = "That paragraph could not be found in the order's text."
    return LocalReference(
        paragraph=loc,
        cited_clause=own,
        successor_clause=succ,
        successor_is_current=is_current,
        note=note,
    )
