"""Retrieval ladder: rung order, early exit, L2 stand-in, leakage, golden ladder levels (plan §3.2,
§13.2 'ladder-level accuracy', §13.3)."""

from __future__ import annotations

import datetime as dt
import json

import pytest

from app.config import REPO_ROOT, load_runtime_config
from app.graph.repository import Direction, EdgeKind, GraphEdge, GraphNode, InMemoryGraphRepository
from app.identifiers.resolver import load_departments, resolve_reference
from app.retrieval.graph_expansion import NotCalibratedError
from app.retrieval.ladder import (
    InMemoryKeywordIndex,
    LadderConfig,
    LadderRequest,
    LadderResult,
    LadderRung,
    ladder_label,
    run_ladder,
)
from app.retrieval.scoped import IndexedDocument, InMemoryScopedIndex, L1Criteria
from tests.unit.mock_access import (
    CLASSES,
    CORPUS,
    MATRIX,
    POLICY,
    USER_IDS,
    doc_tags,
    new_store,
    rows,
)

TAGS = doc_tags()
IDX = {r["id"]: r for r in rows("documents_index.csv")}
CID = {d: r["canonical_id"] for d, r in IDX.items()}
DOC = {v: k for k, v in CID.items()}
DOCS = [
    IndexedDocument(
        canonical_id=r["canonical_id"],
        tags=TAGS[d],
        doc_type=r["doc_type"],
        issue_date=dt.datetime.strptime(r["date"], "%d-%m-%Y").date(),
        subject=r["subject"],
    )
    for d, r in IDX.items()
]
TEXT = {d: (CORPUS / "ground_truth" / "text" / f"{d}.txt").read_text("utf-8") for d in IDX}
INDEX = InMemoryScopedIndex(DOCS)
L2 = InMemoryKeywordIndex((doc, TEXT[DOC[doc.canonical_id]]) for doc in DOCS)
GRAPH = InMemoryGraphRepository()
for doc in DOCS:
    GRAPH.upsert_node(GraphNode(canonical_id=doc.canonical_id, tags=doc.tags))
for r in rows("ground_truth/relations.csv"):
    if r["to_id"]:
        GRAPH.upsert_edge(
            GraphEdge(
                source=r["from_canonical"],
                kind=EdgeKind(r["relation"]),
                target=r["to_canonical_or_raw"],
                confirmed=r["explicit_in_text"] == "True",
            )
        )
CFG = LadderConfig(l2_top_k=10, l2_min_score=1.0, l3_max_hops=2)  # test values, not calibration
DEPTS = load_departments(REPO_ROOT / "data" / "ontology" / "departments.yaml")
GOLDEN = {
    q["id"]: q
    for q in json.loads((CORPUS / "ground_truth" / "golden_questions.json").read_text("utf-8"))
}
RELATED = frozenset({EdgeKind.SUPERSEDES, EdgeKind.REFERENCES, EdgeKind.AMENDS, EdgeKind.CLARIFIES})


def _run(req: LadderRequest, store=None) -> LadderResult:  # type: ignore[no-untyped-def]
    return run_ladder(
        req,
        index=INDEX,
        l2=L2,
        graph=GRAPH,
        cfg=CFG,
        store=store or new_store(),
        policy=POLICY,
        classification=CLASSES,
    )


def _docs(res: LadderResult) -> set[str]:
    return {DOC[d.canonical_id] for d in res.documents} | {DOC[c] for c in res.graph_hits}


def _golden(qid: str, res: LadderResult) -> None:
    q = GOLDEN[qid]
    got = _docs(res)
    assert set(q["expected_docs"]) <= got, (qid, got)
    assert not set(q["forbidden_docs"]) & got, qid
    assert ladder_label(res) == q["expected_ladder_level"], (qid, res.trace)


def test_q05_exact_reference_then_graph() -> None:
    """'Is Circular Memo No.USD01-WRKS0/9/2023 still valid?' → L0, then L3 to related G.O.s."""
    ref = resolve_reference(GOLDEN["Q05"]["question"], DEPTS, default_dept="USD01")
    assert ref.canonical_id is not None
    res = _run(LadderRequest(user_id="U03", canonical_ids=(ref.canonical_id,), relations=RELATED))
    _golden("Q05", res)
    assert [t.rung for t in res.trace if t.fired] == [LadderRung.L0, LadderRung.L3]


def test_q03_structured_filter_exits_at_l1() -> None:
    crit = L1Criteria(department="FIN01", subject_terms=("transfers", "2025"))
    res = _run(
        LadderRequest(user_id="U01", criteria=crit, text_query="current transfer guidelines")
    )
    _golden("Q03", res)
    l2 = next(t for t in res.trace if t.rung is LadderRung.L2)
    assert not l2.fired and l2.note == "skipped: answered at L1"  # early exit


@pytest.mark.parametrize("qid", ["Q01", "Q02"])
def test_q01_q02_same_question_different_officers(qid: str) -> None:
    q = GOLDEN[qid]
    res = _run(
        LadderRequest(user_id=q["user"], text_query="spouse grounds transfer request decided")
    )
    _golden(qid, res)


def test_q15_q14_secret_report_only_for_secretary() -> None:
    query = "Vigilance Enforcement report drain contracts"
    _golden("Q15", _run(LadderRequest(user_id="U06", text_query=query)))
    res = _run(LadderRequest(user_id="U05", text_query=query))
    assert "D23" not in _docs(res)


def test_missing_reference_falls_through_to_l2() -> None:
    res = _run(
        LadderRequest(
            user_id="U01",
            canonical_ids=("AP-FIN01-GOMS-999-2025",),
            text_query="transfer guidelines 2025",
        )
    )
    l0 = res.trace[0]
    assert l0.fired and not l0.exited and l0.note == "reference(s) not found"
    assert res.answered_by is LadderRung.L2


def test_officer_default_department_alone_does_not_find_q18() -> None:
    """Q18 'GO Ms 88/2022': the officer's own department alone gives a non-existent ID and L0 finds
    nothing (never a wrong order). The fix is `lookup_reference` (test_reference_lookup.py)."""
    ref = resolve_reference(GOLDEN["Q18"]["question"], DEPTS, default_dept="USD01")
    assert ref.canonical_id == "AP-USD01-GOMS-88-2022"
    res = _run(LadderRequest(user_id="U01", canonical_ids=(ref.canonical_id,)))
    assert res.documents == () and res.answered_by is None


@pytest.mark.parametrize("uid", USER_IDS)
def test_ladder_never_returns_forbidden_documents(uid: str) -> None:
    for req in (
        LadderRequest(
            user_id=uid, text_query="vigilance enquiry drain tenders report contractors charges"
        ),
        LadderRequest(user_id=uid, criteria=L1Criteria(), relations=frozenset(EdgeKind)),
        LadderRequest(
            user_id=uid, canonical_ids=tuple(CID.values()), relations=frozenset(EdgeKind)
        ),
    ):
        res = _run(req)
        assert all(MATRIX[(d, uid)] for d in _docs(res)), (uid, req)


def test_unknown_user_and_uncalibrated_config() -> None:
    res = _run(LadderRequest(user_id="U99", text_query="anything"))
    assert res.scope_signature is None and res.documents == () and res.trace == ()
    with pytest.raises(NotCalibratedError):
        LadderConfig.from_runtime(
            load_runtime_config(REPO_ROOT / "backend" / "config" / "runtime.yaml")
        )


def test_l3_needs_seeds_and_direction_matters() -> None:
    res = _run(LadderRequest(user_id="U01", relations=RELATED))
    assert res.trace[-1].note == "no seeds" and res.graph_hits == ()
    down = _run(
        LadderRequest(
            user_id="U01",
            canonical_ids=(CID["D01"],),
            relations=frozenset({EdgeKind.SUPERSEDES}),
            direction=Direction.IN,
        )
    )
    assert {DOC[c] for c in down.graph_hits} == {"D03", "D04"}


def test_telugu_words_are_search_terms() -> None:
    """Golden Q19 (ADR-0050): a Telugu question produced no terms at all, so it never reached
    a Telugu record. Telugu words are whole terms (vowel signs kept); English is unchanged."""
    from app.conflict.judgment import _terms as passage_terms
    from app.retrieval.ladder import _terms

    q = "అత్యవసర పనులకు కమిషనర్ ఇవ్వగల పరిపాలనా అనుమతి పరిమితి ఎంత? G.O.Ms.No.27"
    got = _terms(q)
    assert {"అత్యవసర", "పనులకు", "కమిషనర్", "పరిపాలనా", "అనుమతి"} <= set(got)
    assert {"ms", "no.27"} <= set(got)
    assert _terms("Transfer of the Senior Assistant") == ["transfer", "senior", "assistant"]
    assert "అత్యవసర పనులకు" in passage_terms(q)
