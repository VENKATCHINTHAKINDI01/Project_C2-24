"""Touchpoint 16 — "Closing a file": suggested closing remarks (plan §11.5).

Deterministic, from the file's own record as the officer may read it: the last direction (its note
number, post, date and opening words) and the orders or papers on the file dated on or after it.
What stands in the way of closing is listed rather than hidden: the file is not with this
officer, Yellow Notes are not yet confirmed, or no direction is recorded (then there is no
suggestion: the remarks need the officer's own words). The officer edits the text and closes the
file in e-Office; once closed, the file's notes go to ingestion and join the precedent index.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from app.identifiers.display import reference_text
from app.noting.chain import FileSoFar
from app.noting.movements import EXCERPT, put_up


class ClosingRemarks(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str | None  # the suggestion; None when the record gives nothing to base it on
    cited: tuple[str, ...]  # canonical IDs the text names (the direction note, the orders)
    blockers: tuple[str, ...]  # what stands in the way of closing, in plain words
    can_close: bool


def closing_remarks(
    *,
    state: str,
    chain: FileSoFar,
    issued: Sequence[tuple[str, dt.date | None, str]],
    yellow_notes: int,
    holder: str | None,
    user_id: str,
) -> ClosingRemarks:
    """Plan §11.5 touchpoint 16. `issued`: the file's non-note papers the officer may see
    (canonical ID, date, type)."""
    blockers = []
    if state == "closed":
        blockers.append("The file is already closed.")
    if holder is not None and holder != user_id:
        blockers.append("The file is not with you: only the officer holding it can close it.")
    if yellow_notes:
        blockers.append(f"{yellow_notes} Yellow Note(s) on the file are not yet confirmed.")
    d = put_up(chain.last_direction) if chain.last_direction else None
    if d is None:
        blockers.append("No direction is recorded in the notes you can read; write the remarks.")
        return ClosingRemarks(text=None, cited=(), blockers=tuple(blockers), can_close=False)
    on = d.signed_at.date() if d.signed_at else None
    words = d.excerpt if len(d.excerpt) < EXCERPT else d.excerpt.rstrip(" …") + " …"
    parts = [
        f"The last direction on the file is at Note #{d.note_no}"
        + (f" of the {d.post.title()}" if d.post else "")
        + (f" dated {on:%d-%m-%Y}" if on else "")
        + f' ("{words}").'
    ]
    after = [
        (cid, date) for cid, date, _ in issued if date is not None and (on is None or date >= on)
    ]
    if after:
        refs = "; ".join(reference_text(cid, date) for cid, date in after)
        parts.append(f"Orders / papers issued thereafter: {refs}.")
    parts.append("No further action is pending on this file. The file may be closed.")
    return ClosingRemarks(
        text=" ".join(parts),
        cited=(d.source, *(c for c, _ in after)),
        blockers=tuple(blockers),
        can_close=not blockers,
    )
