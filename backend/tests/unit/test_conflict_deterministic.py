"""Deterministic conflict types A, E, F on the three live mock proposals (plan §6.2, §13.2).

Expected outcomes are read from ground_truth/ (tests only). Types B, C, D, G need rule metadata or
grounded LLM judgment and are out of scope here.
"""

from __future__ import annotations

import csv
import datetime as dt
import json

import pytest

from app.config import REPO_ROOT
from app.conflict.deterministic import Citation, ConflictType, check_citations
from app.identifiers.resolver import load_departments, resolve_reference
from app.temporal.engine import Instrument, RelationKind, TemporalRelation

CORPUS = REPO_ROOT / "data" / "synthetic" / "mock_v1"
GT = CORPUS / "ground_truth"
DEPTS = load_departments(REPO_ROOT / "data" / "ontology" / "departments.yaml")
DETERMINISTIC = {ConflictType.A, ConflictType.E, ConflictType.F}


def _csv(path: str) -> list[dict[str, str]]:
    with (CORPUS / path).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _iso(s: str) -> dt.date | None:
    return dt.date.fromisoformat(s) if s else None


ROWS = _csv("documents_index.csv")
BY_ID = {r["id"]: r for r in ROWS}
RELROWS = _csv("ground_truth/relations.csv")
RELS = [
    TemporalRelation(
        source=r["from_canonical"],
        kind=RelationKind(r["relation"]),
        target=r["to_canonical_or_raw"],
    )
    for r in RELROWS
    if r["relation"] in {"SUPERSEDES", "REPEALS"}
]
SUPERSEDED = {r.target for r in RELS}
KNOWN = {
    r["canonical_id"]: Instrument(
        canonical_id=r["canonical_id"],
        hierarchy_level=int(r["hierarchy_level"]),
        effective_from=_iso(r["effective_from"]),
        valid_until=None if r["canonical_id"] in SUPERSEDED else _iso(r["effective_to"]),
    )
    for r in ROWS
}
EXPECTED = json.loads((GT / "conflicts.json").read_text(encoding="utf-8"))


def _citations(doc_id: str) -> list[Citation]:
    out = []
    for r in RELROWS:
        if r["from_id"] != doc_id:
            continue
        if r["relation"] == "CITES":
            out.append(
                Citation(raw=r["to_canonical_or_raw"], canonical_id=r["to_canonical_or_raw"])
            )
        elif r["relation"] == "CITES_UNRESOLVED":
            res = resolve_reference(r["to_canonical_or_raw"], DEPTS, BY_ID[doc_id]["department"])
            out.append(Citation(raw=res.raw, canonical_id=res.canonical_id))
    return out


def _run(doc_id: str) -> set[ConflictType]:
    action = dt.datetime.strptime(BY_ID[doc_id]["date"], "%d-%m-%Y").date()
    return {f.type for f in check_citations(_citations(doc_id), action, KNOWN, RELS)}


@pytest.mark.parametrize("doc_id", ["D27", "D28", "D29"])
def test_no_false_positives_on_live_proposals(doc_id: str) -> None:
    expected = {ConflictType(c["type"]) for c in EXPECTED if c["in"] == doc_id}
    assert _run(doc_id) <= expected & DETERMINISTIC


def test_d27_superseded_reference_and_missing_authority() -> None:
    action = dt.date(2026, 9, 22)
    flags = check_citations(_citations("D27"), action, KNOWN, RELS)
    a = next(f for f in flags if f.type is ConflictType.A)
    assert a.evidence_ids == ("AP-FIN01-GOMS-88-2022", "AP-FIN01-GOMS-31-2025")
    assert a.explanation.startswith("Potential conflict") and "Review recommended" in a.explanation
    e = next(f for f in flags if f.type is ConflictType.E)
    assert e.cited == "AP-FIN01-GOMS-104-2026"
    assert "not found in the records available to you" in e.explanation


def test_d29_relies_on_expired_order() -> None:
    flags = check_citations(_citations("D29"), dt.date(2026, 8, 12), KNOWN, RELS)
    assert [(f.type, f.cited) for f in flags] == [(ConflictType.F, "AP-FIN01-GORT-1184-2025")]
    assert flags[0].dates["valid_until"] == dt.date(2026, 3, 31)


def test_d28_cites_active_circular_so_no_reference_flags() -> None:
    assert _run("D28") == set()


def test_unresolvable_raw_reference_is_type_e_uncertain() -> None:
    flags = check_citations(
        [Citation(raw="the G.O. read above", canonical_id=None)], dt.date(2026, 1, 1), KNOWN, RELS
    )
    assert flags[0].type is ConflictType.E and not flags[0].certain


def test_same_citation_before_supersession_is_clean() -> None:
    cite = [Citation(raw="G.O.Ms.No.88", canonical_id="AP-FIN01-GOMS-88-2022")]
    assert check_citations(cite, dt.date(2024, 1, 1), KNOWN, RELS) == []


def test_flags_never_name_documents_outside_known_set() -> None:
    """Leakage guard: evidence IDs come only from the authorised `known` set."""
    for doc_id in ("D27", "D28", "D29"):
        action = dt.datetime.strptime(BY_ID[doc_id]["date"], "%d-%m-%Y").date()
        for f in check_citations(_citations(doc_id), action, KNOWN, RELS):
            assert set(f.evidence_ids) <= set(KNOWN)
