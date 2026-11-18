"""How an order changed over time: its lineage, in date order (plan §6.1, §12.3; ADR-0056).

A pure function over temporal facts, never a model guess (CLAUDE.md §6.1). The lineage of an order
is every instrument joined to it by a CONFIRMED amending, clarifying, superseding or repealing link,
in either direction (the 2019 guidelines, their amendment, the 2022 order that replaced both, …).
Each instrument is one event on the date it took effect; unconfirmed links are listed for review
and never change the story. Callers pass only the facts the officer may see (`visible_facts`), so
a restricted order never appears, never joins two parts of a lineage and is never counted.
"""

from __future__ import annotations

import datetime as dt
from collections import deque
from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.temporal.engine import Instruments, RelationKind, Status, TemporalRelation, status_as_of

LINEAGE = frozenset(
    {RelationKind.SUPERSEDES, RelationKind.REPEALS, RelationKind.AMENDS, RelationKind.CLARIFIES}
)
MAX_MEMBERS = 40  # a lineage larger than this is cut at the members nearest the order asked about


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Change(StrEnum):
    ISSUED = "issued"  # no earlier instrument of the lineage is touched by it
    AMENDED = "amended"
    CLARIFIED = "clarified"
    SUPERSEDED = "superseded"
    REPEALED = "repealed"


_VERB = {
    RelationKind.AMENDS: Change.AMENDED,
    RelationKind.CLARIFIES: Change.CLARIFIED,
    RelationKind.SUPERSEDES: Change.SUPERSEDED,
    RelationKind.REPEALS: Change.REPEALED,
}


class HistoryEvent(_Frozen):
    on: dt.date  # the day the instrument took effect
    canonical_id: str  # the instrument that made the change
    change: Change
    targets: tuple[str, ...] = ()  # what it amended / superseded / … (empty for ISSUED)


class History(_Frozen):
    seed: str
    as_of: dt.date
    events: tuple[HistoryEvent, ...]  # date order; only instruments in effect by `as_of`
    in_force: tuple[str, ...]  # members in force on `as_of`
    undated: tuple[str, ...] = ()  # members with no effective date: placed nowhere, never guessed
    pending_review: tuple[tuple[str, str, str], ...] = ()  # (source, kind, target), unconfirmed
    cut: bool = False  # the lineage was larger than MAX_MEMBERS
    lineage: tuple[str, ...] = ()  # every member, dated or not, in effect yet or not

    @property
    def members(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(e.canonical_id for e in self.events))


def lineage(
    seed: str, relations: Iterable[TemporalRelation], *, limit: int = MAX_MEMBERS
) -> tuple[list[str], bool]:
    """Members joined to `seed` by confirmed lineage links, nearest first; and whether cut."""
    adj: dict[str, set[str]] = {}
    for r in relations:
        if r.kind in LINEAGE and r.confirmed:
            adj.setdefault(r.source, set()).add(r.target)
            adj.setdefault(r.target, set()).add(r.source)
    seen, queue = [seed], deque([seed])
    while queue:
        cid = queue.popleft()
        for nxt in sorted(adj.get(cid, ())):
            if nxt in seen:
                continue
            if len(seen) == limit:
                return seen, True
            seen.append(nxt)
            queue.append(nxt)
    return seen, False


def history(
    seed: str,
    as_of: dt.date,
    instruments: Instruments,
    relations: Iterable[TemporalRelation],
) -> History:
    """The lineage of `seed` as dated events up to `as_of`, and what is in force on that day.

    An instrument that takes effect after `as_of` is left out (as-of questions see the past as it
    was). An instrument with no effective date is reported as undated, never placed by guess.
    """
    rels = [r for r in relations if r.source in instruments and r.target in instruments]
    members, cut = lineage(seed, rels)
    members = [m for m in members if m in instruments]
    inside = set(members)
    dated = [m for m in members if (f := instruments[m].effective_from) is not None and f <= as_of]
    undated = tuple(sorted(m for m in members if instruments[m].effective_from is None))
    shown = set(dated)
    events: list[HistoryEvent] = []
    for m in dated:
        on = instruments[m].effective_from
        assert on is not None
        made = False
        for kind in (
            RelationKind.AMENDS,
            RelationKind.CLARIFIES,
            RelationKind.SUPERSEDES,
            RelationKind.REPEALS,
        ):
            targets = tuple(
                sorted(
                    r.target
                    for r in rels
                    if r.confirmed and r.kind is kind and r.source == m and r.target in shown
                )
            )
            if targets:
                events.append(
                    HistoryEvent(on=on, canonical_id=m, change=_VERB[kind], targets=targets)
                )
                made = True
        if not made:
            events.append(HistoryEvent(on=on, canonical_id=m, change=Change.ISSUED))
    events.sort(key=lambda e: (e.on, e.canonical_id, e.change.value))
    in_force = tuple(
        m
        for m in sorted(dated, key=lambda c: (instruments[c].effective_from, c))
        if status_as_of(m, as_of, instruments, rels).status is Status.IN_FORCE
    )
    pending = tuple(
        sorted(
            (r.source, r.kind.value, r.target)
            for r in rels
            if r.kind in LINEAGE and not r.confirmed and (r.source in inside or r.target in inside)
        )
    )
    return History(
        seed=seed,
        as_of=as_of,
        events=tuple(events),
        in_force=in_force,
        undated=undated,
        pending_review=pending,
        cut=cut,
        lineage=tuple(members),
    )
