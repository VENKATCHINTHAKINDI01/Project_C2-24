"""Touchpoint 19 — "Section reassignment": a cited handover summary of the section's key matters
and standing orders (plan §11.5).

Deterministic, from the section's files the officer can open now (e-Office reach + C2-24's own
check) and the orders those files cite that the officer may see:

- **files in hand** — open files, where each is pending, since when, due / overdue, sent back, and
  the last direction (note number + post), overdue and oldest first;
- **standing orders** — orders the section's files rely on that are not known to have changed, by
  how many files cite them (the orders a newcomer needs first); "in force" only where the
  officer's access covers every record that could change it, otherwise "status not confirmed";
- **orders no longer in force** — cited by the section's files but superseded / repealed / expired,
  with the order that replaced them: check before relying on the old one;
- **recent decisions** — closed files with their last direction, newest first (precedent).

Every line carries its reference (file number, note number, canonical ID). Counts are over the
officer's authorised set only; nothing hints at files they cannot open.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from app.agents.tools import ToolResult
from app.connectors.eoffice import OfficerFile
from app.identifiers.display import reference_text
from app.noting.movements import MovementSummary, PutUp
from app.temporal.since_decision import CHANGED

TOP_ORDERS = 15
TOP_DECISIONS = 10


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


@dataclass(frozen=True)
class SectionFile:
    """One file of the section, already opened under the officer's access."""

    file: OfficerFile
    moves: MovementSummary
    relied_on: Sequence[
        tuple[str, ToolResult, dt.date | None, str | None]
    ]  # id, status, date, subj


class FileInHand(_Frozen):
    computer_no: str
    file_no: str
    subject: str
    pending_with: str | None
    pending_with_post: str | None
    since: dt.date | None
    days_pending: int | None
    due_on: dt.date | None
    overdue: bool
    sent_back: bool
    last_direction: PutUp | None
    changed_orders: int  # cited orders no longer in force


class SectionOrder(_Frozen):
    canonical_id: str
    reference: str
    subject: str | None
    status: str
    by: str | None
    by_reference: str | None
    since: dt.date | None
    files: tuple[str, ...]  # file numbers citing it (authorised set)


class Decision(_Frozen):
    computer_no: str
    file_no: str
    subject: str
    decided: PutUp


class Handover(_Frozen):
    section: str
    department: str
    as_of: dt.date
    open_files: int
    closed_files: int
    in_hand: tuple[FileInHand, ...]
    standing: tuple[SectionOrder, ...]
    no_longer_in_force: tuple[SectionOrder, ...]
    decisions: tuple[Decision, ...]
    headline: str


def build_handover(
    *,
    section: str,
    department: str,
    as_of: dt.date,
    files: Sequence[SectionFile],
    date_of: Callable[[str], dt.date | None] = lambda _: None,
) -> Handover:
    """Plan §11.5 touchpoint 19."""
    in_hand: list[FileInHand] = []
    decisions: list[Decision] = []
    cited_by: dict[str, list[str]] = defaultdict(list)
    info: dict[str, tuple[ToolResult, dt.date | None, str | None]] = {}
    for sf in files:
        f, m = sf.file, sf.moves
        for cid, st, date, subj in sf.relied_on:
            if f.file_no not in cited_by[cid]:
                cited_by[cid].append(f.file_no)
            info[cid] = (st, date, subj)
        if f.state == "closed":
            if m.last_direction is not None:
                decisions.append(
                    Decision(
                        computer_no=f.computer_no,
                        file_no=f.file_no,
                        subject=f.subject,
                        decided=m.last_direction,
                    )
                )
            continue
        in_hand.append(
            FileInHand(
                computer_no=f.computer_no,
                file_no=f.file_no,
                subject=f.subject,
                pending_with=m.pending_with,
                pending_with_post=m.pending_with_post,
                since=m.pending_since.date() if m.pending_since else None,
                days_pending=m.days_pending,
                due_on=m.due_on,
                overdue=m.overdue,
                sent_back=bool(m.steps and m.steps[-1].sent_back),
                last_direction=m.last_direction,
                changed_orders=sum(
                    1 for _, st, _, _ in sf.relied_on if st.available and st.status in CHANGED
                ),
            )
        )
    in_hand.sort(key=lambda x: (not x.overdue, -(x.days_pending or 0), x.file_no))
    decisions.sort(
        key=lambda d: (d.decided.signed_at or dt.datetime.min).replace(tzinfo=None), reverse=True
    )

    orders: list[SectionOrder] = []
    for cid, file_nos in cited_by.items():
        st, date, subj = info[cid]
        if not st.available:
            continue
        orders.append(
            SectionOrder(
                canonical_id=cid,
                reference=reference_text(cid, date),
                subject=subj,
                # "unconfirmed": seen, but the officer's access does not cover every record that
                # could have changed it: "in force" is not claimed (check_document_status)
                status=st.status or "unconfirmed",
                by=st.by,
                by_reference=reference_text(st.by, date_of(st.by)) if st.by else None,
                since=st.since,
                files=tuple(sorted(file_nos)),
            )
        )
    orders.sort(key=lambda o: (-len(o.files), o.canonical_id))
    in_force = [o for o in orders if o.status == "in_force"]
    # orders the section relies on that are not known to have changed, confirmed ones first
    standing = tuple(
        sorted(
            (o for o in orders if o.status in ("in_force", "unconfirmed")),
            key=lambda o: (o.status != "in_force", -len(o.files), o.canonical_id),
        )[:TOP_ORDERS]
    )
    gone = tuple(o for o in orders if o.status in CHANGED)
    standing_all = [o for o in orders if o.status in ("in_force", "unconfirmed")]
    closed = sum(1 for sf in files if sf.file.state == "closed")
    overdue = sum(f.overdue for f in in_hand)
    head = (
        f"{section}, {department}: {len(in_hand)} file(s) in hand"
        + (f" ({overdue} overdue)" if overdue else "")
        + f", {closed} closed; {len(standing_all)} order(s) relied on and not known to have changed"
        + f" ({len(in_force)} confirmed in force)"
        + (f", {len(gone)} cited order(s) no longer in force" if gone else "")
        + ". Only files and orders you can open are counted."
    )
    return Handover(
        section=section,
        department=department,
        as_of=as_of,
        open_files=len(in_hand),
        closed_files=closed,
        in_hand=tuple(in_hand),
        standing=standing,
        no_longer_in_force=gone,
        decisions=tuple(decisions[:TOP_DECISIONS]),
        headline=head,
    )
