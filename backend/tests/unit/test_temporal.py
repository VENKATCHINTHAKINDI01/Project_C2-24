"""Temporal engine on the mock corpus (plan §6.1, §6.3, §13.2 'Temporal + hierarchy').

Facts come from documents_index.csv and the SUPERSEDES rows of ground_truth/relations.csv
(tests may read ground truth; app code may not).
"""

from __future__ import annotations

import csv
import datetime as dt

import pytest

from app.config import REPO_ROOT, load_hierarchy
from app.temporal.engine import (
    Instrument,
    PrecedenceReason,
    RelationKind,
    Status,
    TemporalError,
    TemporalRelation,
    applicable_version,
    resolve_precedence,
    status_as_of,
    supersession_chain,
)

CORPUS = REPO_ROOT / "data" / "synthetic" / "mock_v1"
HIERARCHY = load_hierarchy(REPO_ROOT / "data" / "ontology" / "hierarchy.yaml")
AS_OF = dt.date(2026, 10, 2)  # corpus as-of date (manifest)
INSTRUMENT_LEVELS = range(1, 9)  # notes (level 9) are case records, not rules


def _csv(name: str) -> list[dict[str, str]]:
    with (CORPUS / name).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _iso(s: str) -> dt.date | None:
    return dt.date.fromisoformat(s) if s else None


ROWS = {r["canonical_id"]: r for r in _csv("documents_index.csv")}
RELS = [
    TemporalRelation(
        source=r["from_canonical"],
        kind=RelationKind(r["relation"]),
        target=r["to_canonical_or_raw"],
    )
    for r in _csv("ground_truth/relations.csv")
    if r["relation"] in {"SUPERSEDES", "REPEALS"}
]
SUPERSEDED = {r.target for r in RELS}
DOCS = {
    cid: Instrument(
        canonical_id=cid,
        hierarchy_level=int(r["hierarchy_level"]),
        effective_from=_iso(r["effective_from"]),
        # own validity end only; an end caused by supersession is derived by the engine
        valid_until=None if cid in SUPERSEDED else _iso(r["effective_to"]),
    )
    for cid, r in ROWS.items()
}
EXPECTED = {"active": Status.IN_FORCE, "superseded": Status.SUPERSEDED, "expired": Status.EXPIRED}


@pytest.mark.parametrize(
    "cid", [c for c, r in ROWS.items() if int(r["hierarchy_level"]) in INSTRUMENT_LEVELS]
)
def test_status_matches_corpus_as_of_date(cid: str) -> None:
    got = status_as_of(cid, AS_OF, DOCS, RELS)
    assert got.status is EXPECTED[ROWS[cid]["status_as_of_2026-10-02"]]


def test_superseded_by_and_since() -> None:
    st = status_as_of("AP-FIN01-GOMS-88-2022", AS_OF, DOCS, RELS)
    assert st.by == "AP-FIN01-GOMS-31-2025" and st.since == dt.date(2025, 5, 12)


def test_as_of_date_walks_back_in_time() -> None:
    cid = "AP-FIN01-GOMS-88-2022"
    assert status_as_of(cid, dt.date(2023, 1, 1), DOCS, RELS).status is Status.IN_FORCE
    assert status_as_of(cid, dt.date(2022, 6, 2), DOCS, RELS).status is Status.NOT_YET_EFFECTIVE
    assert status_as_of(cid, dt.date(2025, 5, 11), DOCS, RELS).status is Status.IN_FORCE
    assert status_as_of(cid, dt.date(2025, 5, 12), DOCS, RELS).status is Status.SUPERSEDED


def test_own_validity_end_is_inclusive() -> None:
    cid = "AP-FIN01-GORT-1184-2025"  # valid to 31-03-2026
    assert status_as_of(cid, dt.date(2026, 3, 31), DOCS, RELS).status is Status.IN_FORCE
    st = status_as_of(cid, dt.date(2026, 4, 1), DOCS, RELS)
    assert st.status is Status.EXPIRED and st.since == dt.date(2026, 4, 1) and st.by is None


def test_chain_and_amendment_follow_to_current() -> None:
    assert supersession_chain("AP-FIN01-GOMS-62-2019", DOCS, RELS) == [
        "AP-FIN01-GOMS-62-2019",
        "AP-FIN01-GOMS-88-2022",
        "AP-FIN01-GOMS-31-2025",
    ]
    assert supersession_chain("AP-FIN01-GOMS-71-2019", DOCS, RELS)[-1] == "AP-FIN01-GOMS-31-2025"


@pytest.mark.parametrize(
    ("as_of", "expected"),
    [
        (dt.date(2018, 1, 1), None),
        (dt.date(2020, 1, 1), "AP-FIN01-GOMS-62-2019"),
        (dt.date(2023, 1, 1), "AP-FIN01-GOMS-88-2022"),
        (AS_OF, "AP-FIN01-GOMS-31-2025"),
    ],
)
def test_applicable_version_as_of(as_of: dt.date, expected: str | None) -> None:
    assert applicable_version("AP-FIN01-GOMS-62-2019", as_of, DOCS, RELS) == expected


def test_expired_chain_has_no_applicable_version() -> None:
    assert applicable_version("AP-FIN01-GORT-1184-2025", AS_OF, DOCS, RELS) is None


def test_unknown_effective_date_is_never_in_force() -> None:
    docs = {"X": Instrument(canonical_id="X", hierarchy_level=4, effective_from=None)}
    assert status_as_of("X", AS_OF, docs, []).status is Status.UNKNOWN


def test_unconfirmed_supersession_goes_to_review_not_status() -> None:
    rel = TemporalRelation(
        source="AP-USD01-GOMS-27-2024",
        kind=RelationKind.SUPERSEDES,
        target="AP-USD01-CIRMEMO-USD01WRKS0-9-2023",
        confirmed=False,
    )
    st = status_as_of("AP-USD01-CIRMEMO-USD01WRKS0-9-2023", AS_OF, DOCS, [*RELS, rel])
    assert st.status is Status.IN_FORCE
    assert st.pending_review == ("AP-USD01-GOMS-27-2024",)


def test_cycle_and_branch_raise() -> None:
    a = Instrument(canonical_id="A", hierarchy_level=4, effective_from=dt.date(2020, 1, 1))
    b = a.model_copy(update={"canonical_id": "B"})
    c = a.model_copy(update={"canonical_id": "C"})
    docs = {"A": a, "B": b, "C": c}
    sup = RelationKind.SUPERSEDES
    with pytest.raises(TemporalError):
        supersession_chain(
            "A",
            docs,
            [
                TemporalRelation(source="B", kind=sup, target="A"),
                TemporalRelation(source="A", kind=sup, target="B"),
            ],
        )
    with pytest.raises(TemporalError):
        supersession_chain(
            "A",
            docs,
            [
                TemporalRelation(source="B", kind=sup, target="A"),
                TemporalRelation(source="C", kind=sup, target="A"),
            ],
        )
    with pytest.raises(TemporalError):
        status_as_of("Z", AS_OF, docs, [])


def test_go_prevails_over_circular_memo() -> None:
    """D28 planted conflict G: circular memo (level 7) vs G.O.Ms.27/2024 (level 4)."""
    p = resolve_precedence(
        DOCS["AP-USD01-CIRMEMO-USD01WRKS0-9-2023"], DOCS["AP-USD01-GOMS-27-2024"], HIERARCHY
    )
    assert p.prevails == "AP-USD01-GOMS-27-2024" and p.reason is PrecedenceReason.HIGHER_LEVEL
    assert p.hierarchy_version == HIERARCHY.version


def test_same_level_later_wins_unless_saved() -> None:
    early = DOCS["AP-FIN01-GOMS-40-2020"]
    late = DOCS["AP-FIN01-GOMS-31-2025"]
    p = resolve_precedence(early, late, HIERARCHY)
    assert p.prevails == late.canonical_id and p.reason is PrecedenceReason.LATER_EFFECTIVE
    saves = TemporalRelation(
        source=late.canonical_id, kind=RelationKind.SAVES, target=early.canonical_id
    )
    p2 = resolve_precedence(early, late, HIERARCHY, [saves])
    assert p2.prevails == early.canonical_id and p2.reason is PrecedenceReason.EARLIER_SAVED


def test_missing_facts_are_undetermined() -> None:
    a = DOCS["AP-FIN01-GOMS-40-2020"]
    assert (
        resolve_precedence(a, a.model_copy(update={"effective_from": None}), HIERARCHY).reason
        is PrecedenceReason.UNDETERMINED
    )
    odd = a.model_copy(update={"hierarchy_level": 42})
    assert resolve_precedence(a, odd, HIERARCHY).prevails is None
