"""What else the records say about a draft's matter (ADR-0060): the history of each order it reads,
and the people its subject and request name — for the officer beside the draft, and as cited
sources for the model's suggested wording.

Nothing here widens access: order histories come from `graph_facts.order_history` (visible facts
only; "in force" only when the scope covers every member), people from `entity_facts.resolve`
(every record re-checked with `visible_document`). A record the officer may not see is never
named, counted or hinted at.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Sequence

from pydantic import BaseModel, ConfigDict

from app.agents.entity_facts import resolve
from app.agents.graph_facts import order_history
from app.agents.tools import ToolContext
from app.identifiers.entities import EntityKind

MAX_EVENTS = 6  # most recent changes per order
MAX_PEOPLE_RECORDS = 8


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HistoryLine(_Frozen):
    text: str
    refs: tuple[str, ...]


class OrderHistoryView(_Frozen):
    order: str
    lines: tuple[HistoryLine, ...]
    in_force: tuple[str, ...]  # empty when the scope does not cover every member's status
    status_reportable: bool


class PersonRecords(_Frozen):
    name: str
    role: str | None
    officer_id: str | None
    records: tuple[tuple[str, str], ...]  # (canonical ID, label), visible only, newest last


class DraftContext(_Frozen):
    histories: tuple[OrderHistoryView, ...] = ()
    people: tuple[PersonRecords, ...] = ()


def draft_context(
    ctx: ToolContext,
    *,
    orders: Sequence[str],
    text: str,
    label: Callable[[str, dt.date | None], str],
    file_no: str | None = None,
) -> DraftContext:
    """Histories of the orders read (those with more than one member) and the people (not offices)
    named in `text` (subject + request), all within the officer's scope. Records of `file_no`, the
    file being drafted in, are left out: its own notes are already quoted as file facts."""
    histories: list[OrderHistoryView] = []
    done: set[str] = set()
    for cid in orders:
        if cid in done:
            continue
        oh = order_history(ctx, cid)
        if oh is None or len(oh.history.members) < 2:
            continue
        done.update(oh.history.lineage)
        lines = []
        for e in oh.history.events[-MAX_EVENTS:]:
            who = label(e.canonical_id, None)
            if e.targets:
                what = " and ".join(label(t, None) for t in e.targets)
                lines.append(
                    HistoryLine(
                        text=f"{e.on:%d-%m-%Y}: {who} {e.change.value} {what}.",
                        refs=(e.canonical_id, *e.targets),
                    )
                )
            else:
                lines.append(
                    HistoryLine(text=f"{e.on:%d-%m-%Y}: {who} took effect.", refs=(e.canonical_id,))
                )
        histories.append(
            OrderHistoryView(
                order=cid,
                lines=tuple(lines),
                in_force=oh.history.in_force if oh.covered else (),
                status_reportable=oh.covered,
            )
        )
    people: list[PersonRecords] = []
    for m in resolve(ctx, text):
        if m.kind is EntityKind.OFFICE:
            continue
        recs = [r for r in m.records if not (file_no and r.file_no == file_no)][
            -MAX_PEOPLE_RECORDS:
        ]
        if not recs:
            continue  # named only in this file: nothing further to show
        people.append(
            PersonRecords(
                name=m.shown_as,
                role=m.roles[0] if m.roles else None,
                officer_id=m.officer_id,
                records=tuple(
                    (
                        r.canonical_id,
                        f"{r.doc_type} in File No.{r.file_no}"
                        if r.file_no
                        else label(r.canonical_id, r.issue_date),
                    )
                    for r in recs
                ),
            )
        )
    return DraftContext(histories=tuple(histories), people=tuple(people))
