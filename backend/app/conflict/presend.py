"""Pre-send check — touchpoint 11 (plan §11.5, §6.2, §6.4): the deterministic conflict types on a
draft note before it is sent.

- A / E / F: every order the note cites, checked against the temporal facts the officer may see.
- C: proposal facts read from the note, checked against approval-authority rules (ADR-0010).
- F (action): the proposal's own date against the windows the in-force orders open for that
  action (`conflict.windows`), e.g. a transfer proposed while the ban on transfers is in force.
- Status coverage (owner rule, 3 Nov 2026): a cited order whose status the officer's records
  cannot establish completely is listed as "status unconfirmed", never assumed in force.
- Awaiting review: a cited order not found while the officer may see records of its department
  that wait in review (a scan before Document AI) keeps its E flag, marked uncertain, and is
  listed in `awaiting_review` (`citations.py`).
- Overall result is CLEAR only when nothing is flagged, every cited order's status is confirmed,
  every needed fact was read, and type C returned NO_CONFLICT_VERIFIED. With mock rules it is
  therefore never CLEAR. B and G: grounded Gemini judgment (`judgment.py`) when a model is
  configured; if it is configured but cannot answer, the report says the check is incomplete.
  D needs comparable-case judgment (later).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.auth.models import AccessPolicy, DocumentAccessTags, StatusCoverage
from app.auth.policy import ScopeError, check, scope_for
from app.auth.store import AuthzStore
from app.config import Classification
from app.conflict.citations import review_citations
from app.conflict.deterministic import Citation, ConflictFlag
from app.conflict.facts import FactsResult, extract_proposal_facts
from app.conflict.procedural import (
    AuthorityOutcome,
    AuthorityResult,
    AuthorityRules,
    check_authority,
)
from app.conflict.windows import check_action_window
from app.identifiers.canonical import InvalidCanonicalIdError, lookup_keys
from app.ingestion.metadata import DocumentMetadata
from app.temporal.engine import Instrument, TemporalRelation
from app.temporal.windows import ActionWindow


class PreSendOutcome(StrEnum):
    CONFLICTS_FOUND = "conflicts_found"
    REVIEW_NEEDED = "review_needed"
    CLEAR = "clear"


class PreSendReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    note_id: str
    outcome: PreSendOutcome
    flags: tuple[ConflictFlag, ...]  # A, E, F (citations), F (action window), C
    authority: AuthorityResult | None
    status_unconfirmed: tuple[str, ...]  # cited orders whose status cannot be confirmed
    awaiting_review: tuple[str, ...] = ()  # cited orders that may be among records in review
    fact_gaps: tuple[str, ...]
    facts: FactsResult | None


def _citations(meta: DocumentMetadata, known_ids: Mapping[str, object]) -> list[Citation]:
    """Each cited order, matched to a stored ID (exact, then without the ADR-0007 date tag)."""
    out = []
    for ref in meta.references:
        if ref.raw.startswith("file:"):
            continue  # e-File proceedings, not an order
        cid = ref.canonical_id
        if cid is not None:
            try:
                cid = next((k for k in lookup_keys(cid) if k in known_ids), cid)
            except InvalidCanonicalIdError:
                pass
        out.append(Citation(raw=ref.raw, canonical_id=cid))
    return out


def presend_check(
    note_id: str,
    text: str,
    meta: DocumentMetadata,
    *,
    user_id: str,
    instruments: Mapping[str, Instrument],
    relations: list[TemporalRelation],
    tags_of: Mapping[str, DocumentAccessTags],
    rules: AuthorityRules,
    store: AuthzStore,
    policy: AccessPolicy,
    classification: Classification,
    windows: Iterable[ActionWindow] = (),
    awaiting_review: Iterable[DocumentAccessTags] = (),
    contradictions: Callable[[list[str], str], tuple[list[ConflictFlag], bool]] | None = None,
    file_notes: str = "",
    precedents: Callable[[str, DocumentMetadata], list[ConflictFlag]] | None = None,
) -> PreSendReport:
    """Run on the officer's draft at "Send" (touchpoint 11). Fails closed to REVIEW_NEEDED."""
    action_date = meta.issue_date or dt.date.today()
    try:
        scope = scope_for(user_id, store, policy, classification)
    except ScopeError:
        return PreSendReport(
            note_id=note_id,
            outcome=PreSendOutcome.REVIEW_NEEDED,
            flags=(),
            authority=None,
            status_unconfirmed=(),
            fact_gaps=("no valid scope",),
            facts=None,
        )

    visible_ids = {
        cid
        for cid in instruments
        if (t := tags_of.get(cid)) is not None
        and check(user_id, t, store, policy, classification).allowed
    }
    cites = _citations(meta, dict.fromkeys(visible_ids))  # match IDs only against visible records
    review = review_citations(
        cites,
        action_date,
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
    flags, unconfirmed = review.flags, review.unconfirmed
    known, rels = review.known, review.relations

    def ceiling_for(tags: DocumentAccessTags) -> str:
        if policy.status_coverage is StatusCoverage.UP_TO_DOCUMENT:
            return tags.classification
        return max(classification.levels, key=lambda lv: lv.rank).name

    # A draft often only says "Para 4 may kindly be seen": the proposal (and any concurrence
    # recorded) is then in the file's earlier notes, which the officer may see (`file_notes`).
    # The draft comes last, so its own proposal wins when it states one.
    facts = extract_proposal_facts(
        f"{file_notes}\n{text}" if file_notes else text, meta, rules, note_id
    )
    authority = None
    gaps = list(facts.missing)
    if contradictions is not None:  # B / G on the cited records the officer may see
        cited = list(dict.fromkeys(c.canonical_id for c in cites if c.canonical_id in known))
        bg, complete = contradictions(cited, text)
        flags = [*flags, *bg]
        if not complete:
            gaps.append("contradiction check (B/G) incomplete: model unavailable")
    if facts.facts is not None:
        window = check_action_window(
            facts.facts.action.value, facts.facts.proposal_date, windows, known, rels
        )
        if window is not None:
            wt = tags_of[window.evidence_ids[0]]
            if not scope.covers_status_domain(wt.department, ceiling_for(wt)):
                window = window.model_copy(
                    update={
                        "certain": False,
                        "explanation": window.explanation
                        + " Your records may not show every later order on this subject.",
                    }
                )
            flags = [*flags, window]
        authority = check_authority(facts.facts, rules, set(known))
        flags = [*flags, *authority.flags]

    clear = (
        not flags
        and not unconfirmed
        and not review.awaiting
        and not gaps
        and authority is not None
        and authority.outcome is AuthorityOutcome.NO_CONFLICT_VERIFIED
    )
    if precedents is not None:  # type D, review only: earlier files the officer may see
        flags += precedents(f"{file_notes}\n{text}" if file_notes else text, meta)
    # the same order cited twice (Read list and a para) gives one flag, not two
    flags = list({(f.type, f.cited, f.explanation): f for f in flags}.values())
    outcome = (
        PreSendOutcome.CONFLICTS_FOUND
        if flags
        else PreSendOutcome.CLEAR
        if clear
        else PreSendOutcome.REVIEW_NEEDED
    )
    return PreSendReport(
        note_id=note_id,
        outcome=outcome,
        flags=tuple(flags),
        authority=authority,
        status_unconfirmed=tuple(dict.fromkeys(unconfirmed)),
        awaiting_review=tuple(review.awaiting),
        fact_gaps=tuple(gaps),
        facts=facts,
    )
