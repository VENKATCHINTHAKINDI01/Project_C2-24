"""Pre-send check — touchpoint 11 (plan §11.5, §6.2, §6.4): the deterministic conflict types on a
draft note before it is sent.

- A / E / F: every order the note cites, checked against the temporal facts the officer may see.
- C: proposal facts read from the note, checked against approval-authority rules (ADR-0010).
- F (action): the proposal's own date against the windows the in-force orders open for that
  action (`conflict.windows`), e.g. a transfer proposed while the ban on transfers is in force.
- Status coverage (owner rule, 3 Nov 2026): a cited order whose status the officer's records
  cannot establish completely is listed as "status unconfirmed", never assumed in force.
- Overall result is CLEAR only when nothing is flagged, every cited order's status is confirmed,
  every needed fact was read, and type C returned NO_CONFLICT_VERIFIED. With mock rules it is
  therefore never CLEAR. B, D and G need grounded Gemini judgment (later).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.auth.models import AccessPolicy, DocumentAccessTags, StatusCoverage
from app.auth.policy import ScopeError, check, scope_for
from app.auth.store import AuthzStore
from app.config import Classification
from app.conflict.deterministic import Citation, ConflictFlag, check_citations
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
from app.temporal.engine import Instrument, Status, TemporalRelation, status_as_of
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

    def visible(cid: str) -> bool:
        t = tags_of.get(cid)
        return t is not None and check(user_id, t, store, policy, classification).allowed

    known = {cid: inst for cid, inst in instruments.items() if visible(cid)}
    rels = [r for r in relations if r.source in known and r.target in known]
    cites = _citations(meta, known)
    flags = check_citations(cites, action_date, known, rels)  # A, E, F

    flagged = {f.cited for f in flags}

    def ceiling_for(tags: DocumentAccessTags) -> str:
        if policy.status_coverage is StatusCoverage.UP_TO_DOCUMENT:
            return tags.classification
        return max(classification.levels, key=lambda lv: lv.rank).name

    unconfirmed = []
    for c in cites:
        if c.canonical_id is None or c.canonical_id not in known or c.canonical_id in flagged:
            continue
        st = status_as_of(c.canonical_id, action_date, known, rels)
        tags = tags_of[c.canonical_id]
        if st.status is Status.IN_FORCE and not scope.covers_status_domain(
            tags.department, ceiling_for(tags)
        ):
            unconfirmed.append(c.canonical_id)  # never assume "in force" from a partial record set

    facts = extract_proposal_facts(text, meta, rules, note_id)
    authority = None
    gaps = list(facts.missing)
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
        and not gaps
        and authority is not None
        and authority.outcome is AuthorityOutcome.NO_CONFLICT_VERIFIED
    )
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
        fact_gaps=tuple(gaps),
        facts=facts,
    )
