"""Type F for the proposed action itself (plan §6.2, §6.4): a proposal dated outside every window
the orders in force open for that action (e.g. a transfer proposed while the ban on transfers is
in force). Complements `deterministic.check_citations`, which checks the orders a note cites.

- Only windows from orders the officer may see and that are IN FORCE on the proposal date count.
- No such order states a window for the action → no flag (no basis; never assumed).
- Inside any window → no flag.
- The source order has an amendment on record → the flag is uncertain (the window may have
  changed). The caller also marks it uncertain when the officer's records cannot establish the
  order's status completely (status-coverage rule, 3 Nov 2026).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping

from app.conflict.deterministic import ConflictFlag, ConflictType
from app.temporal.engine import (
    Instrument,
    RelationKind,
    Status,
    TemporalRelation,
    status_as_of,
)
from app.temporal.windows import ActionWindow


def _fmt(d: dt.date) -> str:
    return d.strftime("%d-%m-%Y")


def check_action_window(
    action: str,
    action_date: dt.date,
    windows: Iterable[ActionWindow],
    known: Mapping[str, Instrument],
    relations: Iterable[TemporalRelation],
) -> ConflictFlag | None:
    """`known` / `relations`: the officer's AUTHORISED temporal facts (as in check_citations)."""
    rels = list(relations)
    live = [
        w
        for w in windows
        if w.action == action
        and w.document_id in known
        and status_as_of(w.document_id, action_date, known, rels).status is Status.IN_FORCE
    ]
    if not live or any(w.contains(action_date) for w in live):
        return None
    last = max(live, key=lambda w: (w.end, w.source))
    amended = any(r.kind is RelationKind.AMENDS and r.target == last.document_id for r in rels)
    note = " The order has been amended; check whether the period was changed." if amended else ""
    return ConflictFlag(
        type=ConflictType.F,
        cited=last.source,
        evidence_ids=(last.document_id,),
        explanation=(
            f"Potential conflict — the proposal is dated {_fmt(action_date)}, outside the period "
            f"{_fmt(last.start)} to {_fmt(last.end)} set under {last.source} "
            f'("{last.evidence}"), and no later period is on record in the orders available to '
            f"you.{note} Review recommended: confirm the {action} can be made at this time."
        ),
        dates={"proposal_date": action_date, "window_start": last.start, "window_end": last.end},
        certain=not amended,
    )
