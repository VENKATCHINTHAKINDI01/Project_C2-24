"""Touchpoint 17 — "Reopening a file": what was decided, and what has changed since (plan §11.5,
§6 temporal).

Deterministic. The decision is the file's last direction (its own note, by number and post); its
date is when that note was signed (else the last movement). "What changed" comes only from the
records the officer may see: each order the file relied on, its status today with the order that
changed it and from when (supersession, repeal, expiry — `check_document_status`), and newer orders
that amend or clarify it (the graph, scoped). A change dated after the decision is "since"; one
dated before it was already in effect when the file was decided (worth knowing, not new). Nothing
is inferred from the text; when nothing changed the answer says so, limited to what the officer can
see.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

from app.agents.tools import ToolResult
from app.connectors.eoffice import MovementRef
from app.identifiers.display import reference_text
from app.noting.chain import FileSoFar
from app.noting.movements import PutUp, put_up

CHANGED = ("superseded", "repealed", "expired")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NewerOrder(_Frozen):
    """An order that AMENDS / CLARIFIES one the file relied on (a scoped graph edge)."""

    canonical_id: str
    kind: str  # "amended" | "clarified"
    issue_date: dt.date | None
    subject: str


class OrderChange(_Frozen):
    cited: str
    cited_reference: str
    change: str  # superseded | repealed | expired | amended | clarified
    by: str | None
    by_reference: str | None
    by_subject: str | None
    on: dt.date | None  # from when (status change) or the newer order's date
    current_version: str | None
    after_decision: bool | None  # None when either date is unknown


class SinceDecision(_Frozen):
    file_no: str
    state: str
    decided: PutUp | None
    decided_on: dt.date | None
    relied_on: tuple[str, ...]  # the orders the file relied on, as the officer may see them
    changes: tuple[OrderChange, ...]  # after the decision first, newest first
    unchanged: tuple[str, ...]
    headline: str


def since_decision(
    *,
    file_no: str,
    state: str,
    chain: FileSoFar,
    movements: Sequence[MovementRef],
    relied_on: Sequence[str],
    status_of: Callable[[str], ToolResult],
    newer: Mapping[str, Sequence[NewerOrder]],
    subject_of: Callable[[str], str | None],
    date_of: Callable[[str], dt.date | None],
) -> SinceDecision:
    """Plan §11.5 touchpoint 17. Every input is already limited to what the officer may see."""
    decided = put_up(chain.last_direction) if chain.last_direction else None
    if decided and decided.signed_at:
        on = decided.signed_at.date()
    elif movements:
        on = max(m.sent_at for m in movements).date()
    else:
        on = None

    def after(d: dt.date | None) -> bool | None:
        return None if d is None or on is None else d > on

    changes: list[OrderChange] = []
    for cid in relied_on:
        st = status_of(cid)
        if st.available and st.status in CHANGED:
            changes.append(
                OrderChange(
                    cited=cid,
                    cited_reference=reference_text(cid, date_of(cid)),
                    change=st.status or "",
                    by=st.by,
                    by_reference=reference_text(st.by, date_of(st.by)) if st.by else None,
                    by_subject=subject_of(st.by) if st.by else None,
                    on=st.since,
                    current_version=st.current_version,
                    after_decision=after(st.since),
                )
            )
        for n in newer.get(cid, ()):
            changes.append(
                OrderChange(
                    cited=cid,
                    cited_reference=reference_text(cid, date_of(cid)),
                    change=n.kind,
                    by=n.canonical_id,
                    by_reference=reference_text(n.canonical_id, n.issue_date),
                    by_subject=n.subject,
                    on=n.issue_date,
                    current_version=None,
                    after_decision=after(n.issue_date),
                )
            )
    changes.sort(
        key=lambda c: (c.after_decision is not True, -(c.on.toordinal() if c.on else 0), c.cited)
    )
    touched = {c.cited for c in changes}
    unchanged = tuple(c for c in relied_on if c not in touched)
    since = [c for c in changes if c.after_decision]
    if decided is not None:
        word = "Decided" if state == "closed" else "Last direction"  # an open file: not final
        head = f"{word} at Note #{decided.note_no}" + (
            f" by {decided.post}" if decided.post else ""
        )
        head += f" on {on:%d-%m-%Y}." if on else "."
    elif on is not None:
        head = f"No direction note you can read; last movement {on:%d-%m-%Y}."
    else:
        head = "No decision recorded in the notes you can read."
    if not relied_on:
        head += " The file cites no order you can see."
    elif since:
        kinds: dict[str, int] = {}
        for c in since:
            kinds[c.change] = kinds.get(c.change, 0) + 1
        what = ", ".join(f"{n} {k}" for k, n in kinds.items())
        n_orders = len({c.cited for c in since})
        head += (
            f" Since then {n_orders} of the {len(relied_on)} order(s) it relied on changed"
            f" ({what})."
        )
    else:
        head += (
            f" None of the {len(relied_on)} order(s) it relied on has changed since, in the"
            " records available to you."
        )
    return SinceDecision(
        file_no=file_no,
        state=state,
        decided=decided,
        decided_on=on,
        relied_on=tuple(relied_on),
        changes=tuple(changes),
        unchanged=unchanged,
        headline=head,
    )
