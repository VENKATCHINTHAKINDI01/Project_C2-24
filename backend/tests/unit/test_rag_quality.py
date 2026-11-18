"""RAG answer quality scoring (plan §13.2 "RAG"; ADR-0050): the no-judge metrics and the RAGAS
runner's plumbing. RAGAS itself is not installed here; the judge is replaced by plain functions."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from evaluation import ragas_score as rs
from evaluation.harness import rag_metrics as rm

SPANS = {"EV-1": "NOTE\n1. Leave sanctioned on 18-09-\n2026 for ten days.", "EV-2": "Rejected."}


def st(quote: str | None, *ev: str, source: str = "evidence") -> dict[str, Any]:
    return {
        "text": "t",
        "quote": quote,
        "source": source,
        "citations": [{"evidence_id": e} for e in ev],
    }


def test_citation_correct_needs_the_quote_in_a_cited_package_item() -> None:
    assert rm.citation_correct(st("leave SANCTIONED on 18-09-2026", "EV-1"), SPANS)
    assert not rm.citation_correct(st("Leave sanctioned", "EV-2"), SPANS)  # wrong item
    assert not rm.citation_correct(st("Leave sanctioned", "EV-9"), SPANS)  # not in the package
    assert not rm.citation_correct(st("Leave sanctioned", "EV-1", "EV-9"), SPANS)
    assert not rm.citation_correct(st(None, "EV-1"), SPANS)
    assert not rm.citation_correct(st("Rejected."), SPANS)  # no citation


def test_record_scores_and_empty_cases_are_none_not_zero() -> None:
    s = rm.record_scores({"D1", "D2", "D3", "D4"}, {"D1"}, {"D1", "D2", "D9"})
    assert s == {
        "context_precision_by_record": 0.5,
        "context_recall_by_record": pytest.approx(2 / 3),
        "citation_completeness": 0.5,
    }
    empty = rm.record_scores(set(), set(), {"D1"})
    assert empty["context_precision_by_record"] is None
    assert empty["citation_completeness"] is None
    assert empty["context_recall_by_record"] == 0.0
    assert rm.mean([None, 1.0, 0.0]) == 0.5 and rm.mean([None]) is None


SAMPLE = {
    "id": "Q1",
    "question": "Was it decided?",
    "answer_key": "Approved in 2025.",
    "contexts": [{"evidence_id": "EV-1", "text": "Approved."}],
    "statements": [st("Approved.", "EV-1"), st(None, source="order records")],
}


def test_inputs_score_model_statements_for_faithfulness() -> None:
    x = rs.inputs(SAMPLE)
    assert x is not None
    assert x["model_response"] == "t" and x["response"] == "t\nt"
    assert x["retrieved_contexts"] == ["Approved."] and x["reference"] == "Approved in 2025."
    assert rs.inputs({**SAMPLE, "statements": []}) is None
    assert rs.inputs({**SAMPLE, "contexts": []}) is None


def test_score_all_records_a_failed_metric_as_none_and_goes_on() -> None:
    async def ok(x: dict[str, Any]) -> float:
        return 0.75

    async def broken(x: dict[str, Any]) -> float:
        raise TimeoutError

    fns = {m: ok for m in rs.METRICS} | {"answer_relevancy": broken}
    no_ref = {**SAMPLE, "id": "Q2", "answer_key": ""}
    rows = asyncio.run(rs.score_all([SAMPLE, no_ref, {**SAMPLE, "id": "Q3", "contexts": []}], fns))
    assert rows[0]["faithfulness"] == 0.75 and rows[0]["answer_relevancy"] is None
    assert rows[0]["errors"] == {"answer_relevancy": "TimeoutError"}
    assert rows[1]["context_recall"] is None and rows[1]["faithfulness"] == 0.75  # no answer key
    assert all(rows[2][m] is None for m in rs.METRICS)  # nothing to score
    means = rs.means(rows)
    assert means["faithfulness"] == 0.75 and means["answer_relevancy"] is None
