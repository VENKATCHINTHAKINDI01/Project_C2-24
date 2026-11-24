"""The L2 calibration measures the exit as the ladder runs it (ADR-0061 addendum, 24 Nov 2026):
one hit per order, the score gap to the runner-up order, the attribute and graph gates, and a
threshold that qualifies only if the low end of its precision interval clears the target."""

from __future__ import annotations

from app.graph.repository import EdgeKind, GraphEdge, InMemoryGraphRepository
from app.retrieval.calibration import (
    QueryJudgment,
    QueryPrediction,
    ValidationDataset,
    calibrate_threshold,
    collect_predictions,
    evaluate_predictions_at_threshold,
    exits,
    wilson_low,
)
from app.retrieval.confidence_policy import SAFEGUARDS, L2ConfidencePolicy
from app.retrieval.ladder import ScoredDocument
from app.retrieval.scoped import IndexedDocument
from tests.unit.test_graph_postgres import node, scope


def _p(score: float, rel: bool, gap: float | None = None, ok: bool = True) -> QueryPrediction:
    return QueryPrediction(
        query_id="q", top_score=score, top_canonical_id="X", is_relevant_hit=rel,
        expected_l2_termination=rel, runner_up_gap=gap, gates_ok=ok,
    )  # fmt: skip


def test_exit_rule_matches_the_ladder() -> None:
    assert exits(_p(0.9, True), 0.88)
    assert not exits(_p(0.87, True), 0.88)
    assert not exits(_p(0.9, True, ok=False), 0.88)  # a gate blocked it
    assert not exits(_p(0.9, True, gap=0.01), 0.88, min_margin=0.03)  # too close to the runner-up
    assert exits(_p(0.9, True, gap=None), 0.88, min_margin=0.03)  # only one order found


def test_a_few_lucky_exits_do_not_qualify() -> None:
    assert round(wilson_low(13, 13), 3) == 0.772  # the 24 Nov holdout: 13 / 13
    preds = [_p(0.95, True) for _ in range(13)] + [_p(0.5, False) for _ in range(50)]
    res = calibrate_threshold(preds, [0.9], min_precision=0.9, retriever="bigquery-hybrid@x")
    assert res.selected_candidate.precision == 1.0
    assert res.selected_candidate.precision_ci_low < 0.9
    policy = L2ConfidencePolicy.create(
        threshold=0.9, calibrated=True, metadata=res.metadata.model_copy(
            update={"safeguards": SAFEGUARDS}))  # fmt: skip
    assert not policy.is_calibrated  # lower bound under target → never trusted


def test_enough_exits_qualify_and_record_how_they_were_measured() -> None:
    preds = [_p(0.95, True, gap=0.1) for _ in range(120)] + [_p(0.95, True, gap=0.01)] * 5
    res = calibrate_threshold(
        preds, [0.9], min_precision=0.9, retriever="bigquery-hybrid@x", min_margin=0.03,
        safeguards=SAFEGUARDS,
    )  # fmt: skip
    m = res.metadata
    assert m.precision_ci_low >= 0.9 and m.min_margin == 0.03 and m.safeguards == SAFEGUARDS
    assert evaluate_predictions_at_threshold(preds, 0.9, 0.03).tp == 120  # 5 ties escalated
    policy = L2ConfidencePolicy.create(threshold=0.9, calibrated=True, metadata=m, margin=0.03)
    assert policy.is_calibrated


class _Retriever:
    def __init__(self, hits: list[ScoredDocument]) -> None:
        self.hits = hits

    def search(self, query: str, scope: object, top_k: int) -> list[ScoredDocument]:
        return self.hits[:top_k]


def _doc(cid: str, subject: str) -> IndexedDocument:
    n = node(cid)
    return IndexedDocument(
        canonical_id=cid, tags=n.tags, doc_type="GO", issue_date=None, subject=subject
    )


def test_predictions_use_one_hit_per_order_and_both_gates() -> None:
    a, b = _doc("A", "B.P.Ed admissions"), _doc("B", "M.P.Ed admissions")
    qs = (("1", "B.P.Ed admissions", "A"), ("2", "M.P.Ed admissions", "B"))
    ds = ValidationDataset(version="t", description="t", queries=tuple(
        QueryJudgment(id=i, query=q, user_id="U", relevant_canonical_ids=(r,)) for i, q, r in qs
    ))  # fmt: skip
    hits = [ScoredDocument(doc=a, score=0.95), ScoredDocument(doc=a, score=0.94),
            ScoredDocument(doc=b, score=0.80)]  # fmt: skip
    g = InMemoryGraphRepository()
    for d in (a, b):
        g.upsert_node(node(d.canonical_id))
    g.upsert_edge(GraphEdge(source="B", kind=EdgeKind.AMENDS, target="A"))
    sc = scope("FIN", rank=1)
    p1, p2 = collect_predictions(ds, _Retriever(hits), lambda _u: sc, graph=g)
    assert p1.runner_up_gap == 0.15  # A's second passage is not the runner-up; B is
    assert not p1.gates_ok and "AMENDS" in (p1.gate_note or "").upper()  # linked orders
    assert not p2.gates_ok and "m.p.ed" in (p2.gate_note or "")  # wrong course on top
    q1, _ = collect_predictions(ds, _Retriever(hits), lambda _u: sc)  # no graph: attribute only
    assert q1.gates_ok


def _meta(cid: str, subject: str, rid: str | None = None) -> dict[str, object]:
    return {"canonical_id": cid, "classification": "UNCLASSIFIED", "department_code": "FIN01",
            "subject": subject, "republishes_id": rid}  # fmt: skip


def test_dataset_builder_keeps_families_apart_and_finds_no_answer_questions() -> None:
    from evaluation.build_l2_validation import build, families_of, family_graph, no_answer

    s = "Revision of pay scales for the staff of the treasury department"
    metas = [_meta(c, f"{s} {c}") for c in ("A", "A2", "B", "C", "C2")]
    relations = [
        {"type": "AMENDS", "from": "A2", "to": "A"},
        {"type": "SUPERSEDES", "from": "C2", "to": "C"},
    ]
    adj = family_graph(metas, relations)
    holdout = {"queries": [{"relevant_canonical_ids": ["A"]}]}
    exclude = families_of([holdout], adj)
    assert exclude == {"A", "A2"}
    items = {
        q["relevant_canonical_ids"][0]
        for q in build(metas, n=10, user="U", seed=1, exclude=exclude)["queries"]
    }
    assert items == {"B", "C", "C2"}
    # loaded: A, A2, B, C. C2 is not loaded but its family is (C); D and its family are not
    metas.append(_meta("D", f"{s} D"))
    na = no_answer(
        metas, family_graph(metas, relations), {"A", "A2", "B", "C"}, n=10, user="U", seed=1
    )
    assert [q["source_not_loaded"] for q in na] == ["D"]
    assert na[0]["relevant_canonical_ids"] == [] and na[0]["expected_l2_termination"] is False
