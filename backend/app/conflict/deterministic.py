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

from app.temporal.engine import Instrument, Status, TemporalRelation, status_as_of


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
    flags: list[ConflictFlag] = []
    for c in citations:
        if c.canonical_id is None or c.canonical_id not in known:
            flags.append(
                ConflictFlag(
                    type=ConflictType.E,
                    cited=c.canonical_id or c.raw,
                    evidence_ids=(),
                    explanation=(
                        f"Potential conflict — relies on {c.raw.strip()}, which was not found in "
                        "the records available to you. Review recommended: verify the authority."
                    ),
                    dates={},
                    certain=c.canonical_id is not None,
                )
            )
            continue
        st = status_as_of(c.canonical_id, action_date, known, rels)
        doc = known[c.canonical_id]
        if st.status in (Status.SUPERSEDED, Status.REPEALED) and st.by and st.since:
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
        for src in st.pending_review:
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
