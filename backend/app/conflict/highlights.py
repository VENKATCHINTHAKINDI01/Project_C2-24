"""Citation highlights on note text (ADR-0015; plan §6.2, §8.2, §11.5 touchpoints 10–11).

Each order a note cites is located in the text and given one state, checked against the records
the officer may see as of a date (default: today's as-of date, so an old note shows what has
changed since). The same deterministic A / E / F review as the pre-send check (`citations.py`):

- CONFLICT     a certain A or F flag (superseded, not in force / no longer in force)
- REVIEW       only uncertain A or F flags (the officer's records may not show everything)
- UNCONFIRMED  no flag, but the status cannot be confirmed from the officer's records (owner rule,
               3 Nov 2026) — never shown as "in force"
- NOT_FOUND    type E: not among the officer's records (or could not be read as a reference).
               Same answer for an order that does not exist and one the officer may not see; the
               flag names the order only in the note's own words, never by a resolved ID.
- OK           visible, status confirmed, no flag

`canonical_id` is set only when the officer may open the order (it is among their visible
records); the frontend links only those. e-File citations are returned as spans (kind "efile")
with no state; the e-Office side decides whether the officer can open that file.
Flags stay advisory: "Potential conflict — … Review recommended" (CLAUDE.md §6.6).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.auth.models import AccessPolicy, DocumentAccessTags
from app.auth.policy import check, scope_for
from app.auth.store import AuthzStore
from app.config import Classification
from app.conflict.citations import review_citations
from app.conflict.deterministic import Citation, ConflictFlag, ConflictType
from app.identifiers.canonical import InvalidCanonicalIdError, lookup_keys
from app.identifiers.resolver import DepartmentTable, resolve_reference
from app.ingestion.metadata import citation_spans
from app.temporal.engine import Instrument, TemporalRelation


class HighlightState(StrEnum):
    CONFLICT = "conflict"
    REVIEW = "review"
    UNCONFIRMED = "unconfirmed"
    NOT_FOUND = "not_found"
    OK = "ok"
    FILE = "file"  # an e-File citation: no conflict state


class Highlight(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    start: int
    end: int  # exclusive offset into the text that was checked
    raw: str
    kind: str  # "order" or "efile"
    state: HighlightState
    canonical_id: str | None  # only when the officer may open the order
    file_no: str | None = None  # e-File citations
    flags: tuple[ConflictFlag, ...] = ()


def _match(cid: str | None, visible: set[str]) -> str | None:
    """The stored ID the citation names (exact, then without the ADR-0007 date tag)."""
    if cid is None:
        return None
    try:
        return next((k for k in lookup_keys(cid) if k in visible), cid)
    except InvalidCanonicalIdError:
        return cid


def highlight_citations(
    text: str,
    as_of: dt.date,
    *,
    default_dept: str | None,
    departments: DepartmentTable,
    user_id: str,
    instruments: Mapping[str, Instrument],
    relations: Iterable[TemporalRelation],
    tags_of: Mapping[str, DocumentAccessTags],
    store: AuthzStore,
    policy: AccessPolicy,
    classification: Classification,
    awaiting_review: Iterable[DocumentAccessTags] = (),
    own_file_no: str | None = None,
) -> list[Highlight]:
    """Locate and check every citation in `text` for this officer. Raises `ScopeError` when the
    officer has no valid scope — the caller fails closed (no highlights, neutral message)."""
    scope = scope_for(user_id, store, policy, classification)
    visible = {
        cid
        for cid in instruments
        if (t := tags_of.get(cid)) is not None
        and check(user_id, t, store, policy, classification).allowed
    }
    spans = citation_spans(text)
    orders = [s for s in spans if s.kind == "order"]
    cites = [
        Citation(
            raw=s.raw,
            canonical_id=_match(
                resolve_reference(s.raw, departments, default_dept).canonical_id, visible
            ),
        )
        for s in orders
    ]
    review = review_citations(
        cites,
        as_of,
        user_id=user_id,
        scope=scope,
        instruments=instruments,
        relations=relations,
        tags_of=tags_of,
        store=store,
        policy=policy,
        classification=classification,
        awaiting_review=awaiting_review,
    )
    unconfirmed = set(review.unconfirmed)

    out: list[Highlight] = []
    cite_of = iter(cites)
    for s in spans:
        if s.kind == "efile":
            if s.raw != own_file_no:
                out.append(
                    Highlight(
                        start=s.start,
                        end=s.end,
                        raw=s.raw,
                        kind="efile",
                        state=HighlightState.FILE,
                        canonical_id=None,
                        file_no=s.raw,
                    )
                )
            continue
        c = next(cite_of)
        key = c.canonical_id or c.raw
        flags = tuple(f for f in review.flags if f.cited == key)
        cid = c.canonical_id if c.canonical_id in visible else None
        if cid is None or any(f.type is ConflictType.E for f in flags):
            state, cid = HighlightState.NOT_FOUND, None
            # Name it only in the officer's own words: an ID resolved from the text would read
            # like a record we hold, and must not differ for a hidden and a non-existent order.
            flags = tuple(
                f.model_copy(
                    update={"cited": s.raw, "explanation": f.explanation.replace(f.cited, s.raw)}
                )
                for f in flags
            )
        elif any(f.certain for f in flags):
            state = HighlightState.CONFLICT
        elif flags:
            state = HighlightState.REVIEW
        elif cid in unconfirmed:
            state = HighlightState.UNCONFIRMED
        else:
            state = HighlightState.OK
        out.append(
            Highlight(
                start=s.start,
                end=s.end,
                raw=s.raw,
                kind="order",
                state=state,
                canonical_id=cid,
                flags=flags,
            )
        )
    return out
