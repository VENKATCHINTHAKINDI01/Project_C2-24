"""Citation review shared by the pre-send check (touchpoint 11) and the receipt inbox
(touchpoint 2): types A, E, F on cited orders over the officer's VISIBLE temporal facts, plus the
status-coverage rule — an order that looks in force is listed as "status unconfirmed" when the
officer's records can't establish its status completely (owner rule, 3 Nov 2026).

Records awaiting review (e.g. a scan waiting for Document AI) are not evidence, but they are not
proof of absence either: when the officer may see a held record of the cited order's department, a
type E flag on that citation is marked uncertain and says the order may be awaiting review, instead
of "not found in the records available to you". The held record is never named. Department is the
only signal a held scan carries, so a truly missing order of that department is softened too — it
stays flagged (checkpoint eval, 4 Nov 2026; owner-approved fix)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from app.auth.models import AccessPolicy, DocumentAccessTags, Scope, StatusCoverage
from app.auth.policy import check
from app.auth.store import AuthzStore
from app.config import Classification
from app.conflict.deterministic import Citation, ConflictFlag, ConflictType, check_citations
from app.identifiers.canonical import InvalidCanonicalIdError, parse_canonical_id
from app.temporal.engine import Instrument, Status, TemporalRelation, status_as_of


@dataclass(frozen=True)
class CitationReview:
    flags: list[ConflictFlag]
    unconfirmed: list[str]
    known: dict[str, Instrument]  # the officer's visible temporal facts
    relations: list[TemporalRelation]
    awaiting: list[str]  # cited orders not found while records of their department await review


def review_citations(
    cites: list[Citation],
    action_date: dt.date,
    *,
    user_id: str,
    scope: Scope,
    instruments: Mapping[str, Instrument],
    relations: Iterable[TemporalRelation],
    tags_of: Mapping[str, DocumentAccessTags],
    store: AuthzStore,
    policy: AccessPolicy,
    classification: Classification,
    awaiting_review: Iterable[DocumentAccessTags] = (),
) -> CitationReview:
    def visible(cid: str) -> bool:
        t = tags_of.get(cid)
        return t is not None and check(user_id, t, store, policy, classification).allowed

    known = {cid: inst for cid, inst in instruments.items() if visible(cid)}
    rels = [r for r in relations if r.source in known and r.target in known]
    flags = check_citations(cites, action_date, known, rels)  # A, E, F
    held_depts = {
        t.department
        for t in awaiting_review
        if check(user_id, t, store, policy, classification).allowed
    }
    awaiting: list[str] = []
    for i, f in enumerate(flags):
        if f.type is ConflictType.E and f.certain and _dept(f.cited) in held_depts:
            awaiting.append(f.cited)  # may be among the officer's records awaiting review
            flags[i] = f.model_copy(
                update={
                    "certain": False,
                    "explanation": (
                        f"Potential conflict — relies on {f.cited}, which was not found among "
                        "your indexed records. Some records of this department that you may see "
                        "are still awaiting review (for example a scan not yet read); it may be "
                        "among them. Review recommended: verify the authority."
                    ),
                }
            )
    flagged = {f.cited for f in flags}

    def ceiling_for(tags: DocumentAccessTags) -> str:
        if policy.status_coverage is StatusCoverage.UP_TO_DOCUMENT:
            return tags.classification
        return max(classification.levels, key=lambda lv: lv.rank).name

    unconfirmed: list[str] = []
    for c in cites:
        if c.canonical_id is None or c.canonical_id not in known or c.canonical_id in flagged:
            continue
        st = status_as_of(c.canonical_id, action_date, known, rels)
        tags = tags_of[c.canonical_id]
        if st.status is Status.IN_FORCE and not scope.covers_status_domain(
            tags.department, ceiling_for(tags)
        ):
            unconfirmed.append(c.canonical_id)  # never assume "in force" from a partial record set
    return CitationReview(
        flags=flags,
        unconfirmed=list(dict.fromkeys(unconfirmed)),
        known=known,
        relations=rels,
        awaiting=list(dict.fromkeys(awaiting)),
    )


def _dept(cid: str) -> str | None:
    try:
        return parse_canonical_id(cid).department
    except InvalidCanonicalIdError:
        return None
