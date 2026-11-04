"""Department-less references: cross-department lookup inside the scope (plan §3.2; Q18 gap)."""

from __future__ import annotations

import datetime as dt
import json

from app.auth.models import DocumentAccessTags
from app.config import REPO_ROOT
from app.identifiers.resolver import load_departments, reference_candidates
from app.retrieval.ladder import LadderRequest, LadderRung, ladder_label
from app.retrieval.references import LookupStatus, lookup_reference
from app.retrieval.scoped import IndexedDocument, InMemoryScopedIndex
from tests.unit.mock_access import CLASSES, CORPUS, POLICY, doc_tags, new_store, rows

DEPTS = load_departments(REPO_ROOT / "data" / "ontology" / "departments.yaml")
TAGS = doc_tags()
CORPUS_INDEX = InMemoryScopedIndex(
    IndexedDocument(
        canonical_id=r["canonical_id"],
        tags=TAGS[r["id"]],
        doc_type=r["doc_type"],
        issue_date=dt.datetime.strptime(r["date"], "%d-%m-%Y").date(),
        subject=r["subject"],
    )
    for r in rows("documents_index.csv")
)
GOLDEN = {
    q["id"]: q
    for q in json.loads((CORPUS / "ground_truth" / "golden_questions.json").read_text("utf-8"))
}


def _lookup(uid: str, text: str, index: InMemoryScopedIndex = CORPUS_INDEX):  # type: ignore[no-untyped-def]
    return lookup_reference(
        uid,
        text,
        departments=DEPTS,
        retriever=index,
        store=new_store(),
        policy=POLICY,
        classification=CLASSES,
    )


def test_candidates_span_departments_only_when_none_is_named() -> None:
    assert reference_candidates("GO Ms 88/2022", DEPTS) == tuple(
        f"AP-{d}-GOMS-88-2022" for d in ("ESE01", "FIN01", "GAD01", "USD01")
    )
    named = "G.O.Ms.No.88, Finance (HR.I-Plg. & Policy) Department, Dt.03-06-2022"
    assert reference_candidates(named, DEPTS) == ("AP-FIN01-GOMS-88-2022",)
    assert reference_candidates("G.O.Ms.No.7, Revenue Department, Dt.01-01-2020", DEPTS) == ()
    assert reference_candidates("G.O.Ms.No.62 read above", DEPTS) == ()  # no year


def test_q18_department_less_reference_now_found() -> None:
    q = GOLDEN["Q18"]
    res = _lookup(q["user"], q["question"])
    assert res.status is LookupStatus.FOUND and res.canonical_id == "AP-FIN01-GOMS-88-2022"
    assert res.candidates_tried == 4


def _two_departments(gad_classification: str) -> InMemoryScopedIndex:
    def doc(dept: str, cls: str) -> IndexedDocument:
        return IndexedDocument(
            canonical_id=f"AP-{dept}-GOMS-88-2022",
            tags=DocumentAccessTags(doc_id=dept, department=dept, section="X", classification=cls),
            doc_type="Government Order",
            issue_date=dt.date(2022, 6, 3),
            subject="synthetic",
        )

    return InMemoryScopedIndex([doc("FIN01", "UNCLASSIFIED"), doc("GAD01", gad_classification)])


def test_two_visible_matches_ask_the_officer() -> None:
    res = _lookup("U01", "GO Ms 88/2022", _two_departments("UNCLASSIFIED"))
    assert res.status is LookupStatus.AMBIGUOUS and res.canonical_id is None
    assert res.choices == ("AP-FIN01-GOMS-88-2022", "AP-GAD01-GOMS-88-2022")


def test_a_restricted_match_is_never_offered_as_a_choice() -> None:
    """U01 (USD01) cannot see a RESTRICTED GAD01 order, so only the Finance one exists for them."""
    res = _lookup("U01", "GO Ms 88/2022", _two_departments("RESTRICTED"))
    assert res.status is LookupStatus.FOUND and res.canonical_id == "AP-FIN01-GOMS-88-2022"


def test_named_department_is_not_widened() -> None:
    res = _lookup(
        "U01",
        "G.O.Ms.No.88, General Administration Department, Dt.03-06-2022",
        _two_departments("UNCLASSIFIED"),
    )
    assert res.status is LookupStatus.FOUND and res.canonical_id == "AP-GAD01-GOMS-88-2022"


def test_not_found_and_unresolved() -> None:
    assert _lookup("U01", "GO Ms 999/2022").status is LookupStatus.NOT_FOUND
    assert _lookup("U01", "the G.O. read above").status is LookupStatus.UNRESOLVED


def test_q18_runs_through_the_ladder_at_l0() -> None:
    from tests.unit.test_ladder import _run

    found = _lookup("U01", GOLDEN["Q18"]["question"])
    res = _run(LadderRequest(user_id="U01", canonical_ids=(found.canonical_id or "",)))
    assert (
        res.answered_by is LadderRung.L0
        and ladder_label(res) == GOLDEN["Q18"]["expected_ladder_level"]
    )
