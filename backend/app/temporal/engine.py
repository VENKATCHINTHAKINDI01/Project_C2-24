"""Temporal validity, supersession chains and hierarchy precedence (plan §6.1, §6.3).

Pure, deterministic functions over metadata facts — never LLM guesses (CLAUDE.md §6.1).
Only *confirmed* relations change a status; unconfirmed ones are reported for human review (§7.3).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.config import Hierarchy


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Instrument(_Frozen):
    """Temporal facts for one document. `valid_until` is the document's OWN end date
    (e.g. "valid up to 31-03-2026"), not an end caused by supersession."""

    canonical_id: str
    hierarchy_level: int
    effective_from: dt.date | None
    valid_until: dt.date | None = None


class RelationKind(StrEnum):
    SUPERSEDES = "SUPERSEDES"
    REPEALS = "REPEALS"
    AMENDS = "AMENDS"
    CLARIFIES = "CLARIFIES"
    SAVES = "SAVES"  # the source explicitly keeps the target in force


class TemporalRelation(_Frozen):
    source: str
    kind: RelationKind
    target: str
    confirmed: bool = True


class Status(StrEnum):
    NOT_YET_EFFECTIVE = "not_yet_effective"
    IN_FORCE = "in_force"
    SUPERSEDED = "superseded"
    REPEALED = "repealed"
    EXPIRED = "expired"
    UNKNOWN = "unknown"  # missing facts: never treated as in force


class TemporalStatus(_Frozen):
    canonical_id: str
    as_of: dt.date
    status: Status
    by: str | None = None
    since: dt.date | None = None
    pending_review: tuple[str, ...] = ()  # unconfirmed relations that would change the status


class TemporalError(Exception):
    """Inconsistent facts (unknown ID, cycle, branching chain). Callers send to review."""


Instruments = Mapping[str, Instrument]


def _get(instruments: Instruments, cid: str) -> Instrument:
    try:
        return instruments[cid]
    except KeyError as exc:
        raise TemporalError(f"unknown instrument {cid}") from exc


def status_as_of(
    cid: str,
    as_of: dt.date,
    instruments: Instruments,
    relations: Iterable[TemporalRelation],
) -> TemporalStatus:
    """Status of `cid` on `as_of` (plan §6.1). Supersession counts from the superseder's
    effective date; an own validity end counts from the day after `valid_until`."""
    doc = _get(instruments, cid)
    if doc.effective_from is None:
        return TemporalStatus(canonical_id=cid, as_of=as_of, status=Status.UNKNOWN)
    if as_of < doc.effective_from:
        return TemporalStatus(canonical_id=cid, as_of=as_of, status=Status.NOT_YET_EFFECTIVE)

    ending: list[tuple[dt.date, Status, str]] = []
    pending: list[str] = []
    for rel in relations:
        if rel.target != cid or rel.kind not in (RelationKind.SUPERSEDES, RelationKind.REPEALS):
            continue
        src = _get(instruments, rel.source)
        if src.effective_from is None or src.effective_from > as_of:
            continue
        if not rel.confirmed:
            pending.append(rel.source)
            continue
        kind = Status.SUPERSEDED if rel.kind is RelationKind.SUPERSEDES else Status.REPEALED
        ending.append((src.effective_from, kind, rel.source))
    if doc.valid_until is not None and as_of > doc.valid_until:
        ending.append((doc.valid_until + dt.timedelta(days=1), Status.EXPIRED, cid))

    if not ending:
        return TemporalStatus(
            canonical_id=cid, as_of=as_of, status=Status.IN_FORCE, pending_review=tuple(pending)
        )
    since, status, by = min(ending)
    return TemporalStatus(
        canonical_id=cid,
        as_of=as_of,
        status=status,
        by=None if status is Status.EXPIRED else by,
        since=since,
        pending_review=tuple(pending),
    )


def supersession_chain(
    cid: str, instruments: Instruments, relations: Iterable[TemporalRelation]
) -> list[str]:
    """`cid` → … → latest successor, following confirmed SUPERSEDES edges (plan §6.1).

    Raises TemporalError on a cycle or when two instruments both supersede the same one.
    """
    rels = [r for r in relations if r.kind is RelationKind.SUPERSEDES and r.confirmed]
    _get(instruments, cid)
    chain = [cid]
    while True:
        successors = sorted({r.source for r in rels if r.target == chain[-1]})
        if not successors:
            return chain
        if len(successors) > 1:
            raise TemporalError(f"branching supersession at {chain[-1]}: {successors}")
        nxt = successors[0]
        if nxt in chain:
            raise TemporalError(f"supersession cycle at {nxt}")
        _get(instruments, nxt)
        chain.append(nxt)


def applicable_version(
    cid: str,
    as_of: dt.date,
    instruments: Instruments,
    relations: Iterable[TemporalRelation],
) -> str | None:
    """The version of `cid`'s chain in force on `as_of`, or None (plan §6.1 as-of-date queries).

    Not "latest document wins": a successor only counts once it is effective on `as_of`, and an
    expired or repealed version yields None.
    """
    rels = list(relations)
    for version in reversed(supersession_chain(cid, instruments, rels)):
        st = status_as_of(version, as_of, instruments, rels)
        if st.status is Status.IN_FORCE:
            return version
        if st.status is Status.NOT_YET_EFFECTIVE:
            continue
        return None
    return None


class PrecedenceReason(StrEnum):
    HIGHER_LEVEL = "higher_level"
    LATER_EFFECTIVE = "later_effective"
    EARLIER_SAVED = "earlier_saved"
    UNDETERMINED = "undetermined"


class Precedence(_Frozen):
    prevails: str | None
    reason: PrecedenceReason
    hierarchy_version: str


def resolve_precedence(
    a: Instrument,
    b: Instrument,
    hierarchy: Hierarchy,
    relations: Iterable[TemporalRelation] = (),
) -> Precedence:
    """Which of two active instruments prevails (plan §6.3; working rule, [To confirm]).

    Higher level (lower number) wins; at the same level the later effective one wins unless the
    later one confirms it SAVES the earlier. Missing facts → UNDETERMINED (officer decides).
    Reported as context, never as a ruling (§6.4).
    """
    levels = {lv.level for lv in hierarchy.levels}

    def out(winner: str | None, reason: PrecedenceReason) -> Precedence:
        return Precedence(prevails=winner, reason=reason, hierarchy_version=hierarchy.version)

    if a.hierarchy_level not in levels or b.hierarchy_level not in levels:
        return out(None, PrecedenceReason.UNDETERMINED)
    if a.hierarchy_level != b.hierarchy_level:
        winner = a if a.hierarchy_level < b.hierarchy_level else b
        return out(winner.canonical_id, PrecedenceReason.HIGHER_LEVEL)
    if a.effective_from is None or b.effective_from is None or a.effective_from == b.effective_from:
        return out(None, PrecedenceReason.UNDETERMINED)
    later, earlier = (a, b) if a.effective_from > b.effective_from else (b, a)
    saved = any(
        r.confirmed
        and r.kind is RelationKind.SAVES
        and r.source == later.canonical_id
        and r.target == earlier.canonical_id
        for r in relations
    )
    if saved:
        return out(earlier.canonical_id, PrecedenceReason.EARLIER_SAVED)
    return out(later.canonical_id, PrecedenceReason.LATER_EFFECTIVE)
