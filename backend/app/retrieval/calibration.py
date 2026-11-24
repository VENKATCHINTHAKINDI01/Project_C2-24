"""Empirical calibration engine for L2 hybrid search (plan §3.2, §13.2; ADR-0061).

Provides:
- Representative validation dataset loading.
- Precision, recall, F1, termination rate, false termination rate, and unnecessary
  escalation rate calculations across candidate thresholds.
- Determination of the optimal calibrated confidence threshold subject to target precision.
- Generation of CalibrationMetadata for storage in configuration and runtime.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.auth.models import Scope
from app.graph.repository import WalkableGraph
from app.retrieval.confidence_policy import CalibrationMetadata
from app.retrieval.ladder import HybridRetriever, ScoredDocument
from app.retrieval.safeguards import verify_cross_candidate_graph, verify_entity_attributes

log = logging.getLogger(__name__)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class QueryJudgment(_Frozen):
    """A labelled query in the validation dataset."""

    id: str
    query: str
    user_id: str = "U01"
    relevant_canonical_ids: tuple[str, ...]
    distractor_canonical_ids: tuple[str, ...] = ()
    expected_l2_termination: bool = True
    category: str = "general"


class ValidationDataset(_Frozen):
    """Collection of representative queries used to calibrate L2."""

    version: str
    description: str
    queries: tuple[QueryJudgment, ...]

    @classmethod
    def load(cls, path: Path) -> ValidationDataset:
        data = json.loads(path.read_text(encoding="utf-8"))
        queries = tuple(
            QueryJudgment(
                id=q["id"],
                query=q["query"],
                user_id=q.get("user_id", "U01"),
                relevant_canonical_ids=tuple(q["relevant_canonical_ids"]),
                distractor_canonical_ids=tuple(q.get("distractor_canonical_ids", ())),
                expected_l2_termination=q.get("expected_l2_termination", True),
                category=q.get("category", "general"),
            )
            for q in data["queries"]
        )
        return cls(
            version=data.get("version", "v1.0"),
            description=data.get("description", "L2 Hybrid Search Validation Set"),
            queries=queries,
        )


class QueryPrediction(_Frozen):
    """Raw retriever scores for a single query."""

    query_id: str
    top_score: float
    top_canonical_id: str | None
    is_relevant_hit: bool  # True if top_canonical_id is in query's relevant_canonical_ids
    expected_l2_termination: bool
    category: str = "general"
    # as the ladder decides (24 Nov 2026): gap to the best *other* order (None = only one order
    # found) and whether the exit safeguards let this top hit end the ladder
    runner_up_gap: float | None = None
    gates_ok: bool = True
    gate_note: str | None = None


class CandidateEvaluation(_Frozen):
    """Evaluation metrics for a candidate threshold."""

    threshold: float
    tp: int
    fp: int
    fn: int
    tn: int
    precision: float
    recall: float
    f1: float
    termination_rate: float
    unnecessary_escalation_rate: float
    false_termination_rate: float
    precision_ci_low: float = 0.0  # 95% Wilson lower bound of the precision


def wilson_low(successes: int, total: int, z: float = 1.96) -> float:
    """Lower bound of the Wilson score interval (95% by default); 0 when nothing exited."""
    if total == 0:
        return 0.0
    p = successes / total
    denom = 1 + z * z / total
    centre = p + z * z / (2 * total)
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return max(0.0, (centre - spread) / denom)


def exits(p: QueryPrediction, threshold: float, min_margin: float | None = None) -> bool:
    """Would the ladder end at L2 on this query? Same rule as L2ConfidencePolicy + the gates."""
    if p.top_score < threshold or not p.gates_ok:
        return False
    return min_margin is None or p.runner_up_gap is None or p.runner_up_gap >= min_margin


class CalibrationResult(_Frozen):
    """Complete outcome of threshold calibration."""

    dataset_version: str
    sample_size: int
    optimal_threshold: float
    metadata: CalibrationMetadata
    selected_candidate: CandidateEvaluation
    candidates: tuple[CandidateEvaluation, ...]


def evaluate_predictions_at_threshold(
    predictions: Sequence[QueryPrediction],
    threshold: float,
    min_margin: float | None = None,
) -> CandidateEvaluation:
    """Compute precision, recall, F1, and termination metrics at a specific candidate threshold.

    Definitions:
    - TP: Top score >= threshold AND hit is relevant (terminated early on correct document).
    - FP: Top score >= threshold AND hit is NOT relevant (false positive early exit).
    - FN: Hit is relevant, BUT top score < threshold (unnecessary escalation to L3).
    - TN: Hit is not relevant, AND top score < threshold (correctly escalated to L3/no early exit).
    """
    tp = 0
    fp = 0
    fn = 0
    tn = 0
    total = len(predictions)

    for p in predictions:
        terminated = exits(p, threshold, min_margin)
        if terminated:
            if p.is_relevant_hit:
                tp += 1
            else:
                fp += 1
        else:
            if p.is_relevant_hit:
                fn += 1
            else:
                tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    termination_rate = (tp + fp) / total if total > 0 else 0.0
    unnecessary_escalation_rate = fn / total if total > 0 else 0.0
    false_termination_rate = fp / total if total > 0 else 0.0

    return CandidateEvaluation(
        threshold=round(threshold, 4),
        tp=tp,
        fp=fp,
        fn=fn,
        tn=tn,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        termination_rate=round(termination_rate, 4),
        unnecessary_escalation_rate=round(unnecessary_escalation_rate, 4),
        false_termination_rate=round(false_termination_rate, 4),
        precision_ci_low=round(wilson_low(tp, tp + fp), 4),
    )


def collect_predictions(
    dataset: ValidationDataset,
    retriever: HybridRetriever,
    scope_fn: Any,
    top_k: int = 10,
    *,
    graph: WalkableGraph | None = None,
) -> list[QueryPrediction]:
    """Run each validation query on the retriever and record what the ladder would see: hits
    reduced to one per order (best passage), the gap to the runner-up order, and the attribute
    gate and (when `graph` is given) the graph gate, exactly as `run_ladder` applies them."""
    preds: list[QueryPrediction] = []
    total = len(dataset.queries)
    for i, q in enumerate(dataset.queries):
        scope: Scope = scope_fn(q.user_id)
        hits: list[ScoredDocument] = retriever.search(q.query, scope, top_k)
        best: dict[str, ScoredDocument] = {}
        for h in hits:
            cid = h.doc.canonical_id
            if cid not in best or h.score > best[cid].score:
                best[cid] = h
        ranked = sorted(best.values(), key=lambda h: (-h.score, h.doc.canonical_id))
        top = ranked[0] if ranked else None
        top_cid = top.doc.canonical_id if top else None
        is_rel = top_cid in q.relevant_canonical_ids if top_cid else False
        gap = round(ranked[0].score - ranked[1].score, 6) if len(ranked) >= 2 else None
        ok, note = True, None
        if top is not None:
            ok, note = verify_entity_attributes(q.query, top.doc.subject)
            if ok and graph is not None and len(ranked) >= 2:
                ok, note = verify_cross_candidate_graph(
                    [h.doc.canonical_id for h in ranked], graph, scope
                )
        top_score = top.score if top else 0.0
        log.info(
            "[%03d/%03d] %s (%s): score=%.4f relevant=%s hit=%s gates=%s",
            i + 1, total, q.id, q.category, top_score, is_rel, top_cid, ok,
        )  # fmt: skip
        preds.append(
            QueryPrediction(
                query_id=q.id,
                top_score=top_score,
                top_canonical_id=top_cid,
                is_relevant_hit=is_rel,
                expected_l2_termination=q.expected_l2_termination,
                category=q.category,
                runner_up_gap=gap,
                gates_ok=ok,
                gate_note=note,
            )
        )
    return preds


def calibrate_threshold(
    predictions: Sequence[QueryPrediction],
    candidate_thresholds: Sequence[float],
    *,
    min_precision: float = 0.85,
    dataset_version: str = "1.0",
    retriever: str,
    min_margin: float | None = None,
    safeguards: Sequence[str] = (),
) -> CalibrationResult:
    """`retriever` names the retriever whose REAL scores `predictions` hold (ADR-0061 addendum):
    a policy built from this result is calibrated only if they were measured and the selected
    threshold meets `min_precision`."""
    if not candidate_thresholds:
        raise ValueError("candidate_thresholds cannot be empty")
    if not predictions:
        raise ValueError("predictions cannot be empty")

    evals = [
        evaluate_predictions_at_threshold(predictions, t, min_margin) for t in candidate_thresholds
    ]

    # A threshold qualifies only if its precision clears the target at the low end of its 95%
    # interval (24 Nov 2026), so a handful of lucky exits cannot qualify
    qualifying = [c for c in evals if c.precision_ci_low >= min_precision]

    if qualifying:
        # Choose qualifying candidate with highest F1 score (ties broken by higher precision)
        best = max(qualifying, key=lambda c: (c.f1, c.precision, -c.threshold))
    else:
        # Fallback: candidate closest to min_precision with highest precision
        best = max(evals, key=lambda c: (c.precision, c.f1, -c.threshold))

    metadata = CalibrationMetadata(
        calibrated_at=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        retriever=retriever,
        dataset_version=dataset_version,
        sample_size=len(predictions),
        precision=best.precision,
        recall=best.recall,
        f1=best.f1,
        target_min_precision=min_precision,
        optimal_threshold=best.threshold,
        termination_rate=best.termination_rate,
        unnecessary_escalation_rate=best.unnecessary_escalation_rate,
        false_termination_rate=best.false_termination_rate,
        precision_ci_low=best.precision_ci_low,
        min_margin=min_margin,
        safeguards=tuple(safeguards),
    )

    return CalibrationResult(
        dataset_version=dataset_version,
        sample_size=len(predictions),
        optimal_threshold=best.threshold,
        metadata=metadata,
        selected_candidate=best,
        candidates=tuple(evals),
    )
