"""Touchpoint 12 — "Initiate action": the remarks recorded at each movement of the file, the note
each sender put up before sending, and where the file is pending now (plan §11.5).

Deterministic: e-Office's own movement records (who, to whom, when, due date, priority, remarks,
sent back) and the file's notes the officer may read (`app.noting.chain`). Nothing is inferred:
a movement with no matching note says so, and the sentence at the top is a fixed template filled
from these records. The note's words shown are its own (first lines), with its note number as the
reference.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from app.connectors.eoffice import MovementRef
from app.noting.chain import FileSoFar, NoteEntry

EXCERPT = 240


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PutUp(_Frozen):
    """A note the sender signed between the previous movement and this one."""

    note_no: int
    post: str | None
    signed_at: dt.datetime | None
    excerpt: str
    source: str  # canonical ID of the note document


class Step(_Frozen):
    seq: int
    from_user: str
    from_post: str | None
    to_user: str
    to_post: str | None
    sent_at: dt.datetime
    due_on: dt.date | None
    priority: str
    remarks: str
    sent_back: bool
    days_held: int | None  # until the next movement (the last one: until today; closed: None)
    notes: tuple[PutUp, ...]


class MovementSummary(_Frozen):
    file_no: str
    state: str
    steps: tuple[Step, ...]
    pending_with: str | None  # user_id
    pending_with_post: str | None
    pending_since: dt.datetime | None
    days_pending: int | None
    due_on: dt.date | None
    overdue: bool
    sent_back_times: int
    headline: str
    last_direction: PutUp | None


def _excerpt(text: str) -> str:
    one = " ".join(text.split())
    return one if len(one) <= EXCERPT else one[: EXCERPT - 1].rsplit(" ", 1)[0] + " …"


def _same_post(a: str | None, b: str | None) -> bool:
    if not a or not b:
        return False
    x, y = " ".join(a.lower().split()), " ".join(b.lower().split())
    return x == y or x in y or y in x


def put_up(n: NoteEntry) -> PutUp:
    return PutUp(
        note_no=n.note_no,
        post=n.post,
        signed_at=n.signed_at,
        excerpt=_excerpt(n.text),
        source=n.source,
    )


# A note's signature time is printed without a zone; e-Office in AP writes local time (IST).
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _aware(t: dt.datetime) -> dt.datetime:
    return t if t.tzinfo else t.replace(tzinfo=IST)


def movement_summary(
    *,
    file_no: str,
    state: str,
    movements: Sequence[MovementRef],
    chain: FileSoFar,
    as_of: dt.date,
    created_by: str | None = None,
    created_by_post: str | None = None,
) -> MovementSummary:
    """Plan §11.5 touchpoint 12. `chain`: the notes this officer may read (already filtered)."""
    moves = sorted(movements, key=lambda m: m.seq)
    signed = [n for n in chain.notes if n.signed_at is not None]
    steps: list[Step] = []
    prev: dt.datetime | None = None
    for i, m in enumerate(moves):
        sent = _aware(m.sent_at)
        nxt: dt.date | None = (
            _aware(moves[i + 1].sent_at).date()
            if i + 1 < len(moves)
            else (None if state == "closed" else as_of)
        )
        mine = tuple(
            put_up(n)
            for n in signed
            if n.signed_at is not None
            and (prev is None or _aware(n.signed_at) > prev)
            and _aware(n.signed_at) <= sent
            and _same_post(n.post, m.from_post)
        )
        steps.append(
            Step(
                seq=m.seq,
                from_user=m.from_user,
                from_post=m.from_post,
                to_user=m.to_user,
                to_post=m.to_post,
                sent_at=m.sent_at,
                due_on=m.due_on,
                priority=m.priority,
                remarks=m.remarks.strip(),
                sent_back=m.sent_back,
                days_held=max(0, (nxt - sent.date()).days) if nxt else None,
                notes=mine,
            )
        )
        prev = sent
    last = moves[-1] if moves else None
    if state == "closed":
        holder = holder_post = None
        since = None
    elif last is not None:
        holder, holder_post, since = last.to_user, last.to_post, _aware(last.sent_at)
    else:
        holder, holder_post, since = created_by, created_by_post, None
    days = (as_of - since.date()).days if since else None
    due = last.due_on if last and state != "closed" else None
    overdue = bool(due and due < as_of)
    back = sum(m.sent_back for m in moves)
    who = f"{holder_post} ({holder})" if holder_post and holder else holder
    if state == "closed":
        head = f"File closed. It moved {len(moves)} time(s)."
    elif who and since:
        head = f"Pending with {who} since {since.date():%d-%m-%Y} ({days} day(s))."
    elif who:
        head = f"With {who}; not sent yet."
    else:
        head = "Where the file is now is not recorded."
    if due and state != "closed":
        head += f" Due {due:%d-%m-%Y}" + (" — overdue." if overdue else ".")
    if back:
        head += f" Sent back {back} time(s)."
    return MovementSummary(
        file_no=file_no,
        state=state,
        steps=tuple(steps),
        pending_with=holder,
        pending_with_post=holder_post,
        pending_since=since,
        days_pending=days,
        due_on=due,
        overdue=overdue,
        sent_back_times=back,
        headline=head,
        last_direction=put_up(chain.last_direction) if chain.last_direction else None,
    )
