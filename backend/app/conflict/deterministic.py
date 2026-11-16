"""Deterministic conflict checks on cited references: types A, E, F (plan §6.2, §6.4).

No LLM: canonical IDs + temporal facts only. Flags are advisory ("Potential conflict … review
recommended"), never verdicts. `known` must already be the officer's AUTHORISED set, so a missing
authority is reported as "not found in the records available to you" — the check can neither
confirm nor deny that a restricted document exists (plan §5.4).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.auth.messages import NOT_IN_COLLECTION
from app.temporal.engine import (
    Instrument,
    RelationKind,
    Status,
    TemporalRelation,
    status_as_of,
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ConflictType(StrEnum):
    A = "A"  # superseded reference
    B = "B"  # direct contradiction (hybrid, not here)
    C = "C"  # procedural / wrong authority (needs rule metadata, not here)
    D = "D"  # precedent inconsistency (hybrid, not here)
    E = "E"  # missing / unresolvable authority
    F = "F"  # temporal mismatch
    G = "G"  # hierarchy conflict (hybrid, not here)


class Citation(_Frozen):
    """One reference cited by a proposal: raw text kept for provenance (plan §4.4)."""

    raw: str
    canonical_id: str | None


class ConflictFlag(_Frozen):
    type: ConflictType
    cited: str  # canonical ID, or the raw text when unresolved
    evidence_ids: tuple[str, ...]
    explanation: str
    dates: dict[str, dt.date]
    certain: bool = True
    review_state: str = "needs_review"


def _fmt(d: dt.date | None) -> str:
    return d.strftime("%d-%m-%Y") if d else "unknown date"


def check_citations(
    citations: Iterable[Citation],
    action_date: dt.date,
    known: Mapping[str, Instrument],
    relations: Iterable[TemporalRelation],
) -> list[ConflictFlag]:
    """Types A, E, F for every citation of a proposal dated `action_date` (plan §6.2)."""
    rels = list(relations)
    cites = list(citations)
    # A proposal that cites the newer order itself (e.g. "G.O.57 read with G.O.54") applies it; the
    # older one is named as history, not relied on: no type A for that pair (efiles_v2 clean cases).
    cited_ids = {c.canonical_id for c in cites if c.canonical_id}
    flags: list[ConflictFlag] = []
    for c in cites:
        if c.canonical_id is None or c.canonical_id not in known:
            flags.append(
                ConflictFlag(
                    type=ConflictType.E,
                    cited=c.canonical_id or c.raw,
                    evidence_ids=(),
                    explanation=(
                        f"Potential conflict — relies on {c.raw.strip()}, which was not found in "
                        f"the records available to you. {NOT_IN_COLLECTION} "
                        "Review recommended: verify the authority."
                    ),
                    dates={},
                    certain=c.canonical_id is not None,
                )
            )
            continue
        st = status_as_of(c.canonical_id, action_date, known, rels)
        doc = known[c.canonical_id]
        if (
            st.status in (Status.SUPERSEDED, Status.REPEALED)
            and st.by
            and st.since
            and st.by not in cited_ids
        ):
            verb = "superseded" if st.status is Status.SUPERSEDED else "repealed"
            flags.append(
                ConflictFlag(
                    type=ConflictType.A,
                    cited=c.canonical_id,
                    evidence_ids=(c.canonical_id, st.by),
                    explanation=(
                        f"Potential conflict — relies on {c.canonical_id} "
                        f"({_fmt(doc.effective_from)}), which appears {verb} by {st.by} "
                        f"({_fmt(st.since)}). Review recommended: verify applicability before "
                        "approval."
                    ),
                    dates={"cited_effective_from": doc.effective_from, "ended_on": st.since}
                    if doc.effective_from
                    else {"ended_on": st.since},
                )
            )
        elif st.status in (Status.EXPIRED, Status.NOT_YET_EFFECTIVE, Status.UNKNOWN):
            dates = {"action_date": action_date}
            if doc.effective_from:
                dates["effective_from"] = doc.effective_from
            if doc.valid_until:
                dates["valid_until"] = doc.valid_until
            why = {
                Status.EXPIRED: f"whose validity ended on {_fmt(doc.valid_until)}",
                Status.NOT_YET_EFFECTIVE: f"which takes effect only on {_fmt(doc.effective_from)}",
                Status.UNKNOWN: "whose effective date is not recorded",
            }[st.status]
            flags.append(
                ConflictFlag(
                    type=ConflictType.F,
                    cited=c.canonical_id,
                    evidence_ids=(c.canonical_id,),
                    explanation=(
                        f"Potential conflict — relies on {c.canonical_id}, {why}; the proposal is "
                        f"dated {_fmt(action_date)}. Review recommended."
                    ),
                    dates=dates,
                    certain=st.status is not Status.UNKNOWN,
                )
            )
        if st.status is Status.IN_FORCE:
            # Type F (plan §6.2): an order amended before the proposal's date, where the proposal
            # does not cite the amending order — the note may apply the unamended text.
            seen: set[str] = set()
            for rel in rels:
                if (
                    rel.kind is not RelationKind.AMENDS
                    or rel.target != c.canonical_id
                    or rel.source in cited_ids
                    or rel.source in seen
                    or rel.source not in known
                ):
                    continue
                amender = known[rel.source]
                if amender.effective_from is None or amender.effective_from > action_date:
                    continue
                seen.add(rel.source)
                flags.append(
                    ConflictFlag(
                        type=ConflictType.F,
                        cited=c.canonical_id,
                        evidence_ids=(c.canonical_id, rel.source),
                        explanation=(
                            f"Potential conflict — relies on {c.canonical_id} "
                            f"({_fmt(doc.effective_from)}), which {rel.source} amended with effect "
                            f"from {_fmt(amender.effective_from)}, before the proposal's date "
                            f"({_fmt(action_date)}). Review recommended: check that the amended "
                            "provisions are applied."
                        ),
                        dates={"amended_from": amender.effective_from, "action_date": action_date},
                        certain=rel.confirmed,
                    )
                )
        for src in st.pending_review:
            if src in cited_ids:
                continue
            flags.append(
                ConflictFlag(
                    type=ConflictType.A,
                    cited=c.canonical_id,
                    evidence_ids=(c.canonical_id, src),
                    explanation=(
                        f"Possible supersession — {src} may replace {c.canonical_id}; the link is "
                        "not yet confirmed. Review recommended."
                    ),
                    dates={},
                    certain=False,
                )
            )
    return flags
