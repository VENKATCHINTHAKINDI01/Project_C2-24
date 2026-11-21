"""Unit tests for L2 Calibrated Confidence Policy (plan §3.2, §13.2; ADR-0061)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.auth.models import DocumentAccessTags
from app.config import REPO_ROOT
from app.graph.repository import InMemoryGraphRepository
from app.retrieval.calibration import (
    QueryPrediction,
    ValidationDataset,
    calibrate_threshold,
    evaluate_predictions_at_threshold,
)
from app.retrieval.confidence_policy import (
    CalibrationMetadata,
    L2ConfidencePolicy,
    ThresholdCalibrationState,
)
from app.retrieval.ladder import (
    InMemoryKeywordIndex,
    LadderConfig,
    LadderRequest,
    LadderRung,
    run_ladder,
)
from app.retrieval.scoped import IndexedDocument, InMemoryScopedIndex
from app.tracking.monitor import l2_monitoring_metrics
from app.tracking.query_log import QueryRecord
from tests.unit.mock_access import CLASSES, POLICY, new_store


@pytest.fixture
def dummy_meta() -> CalibrationMetadata:
    return CalibrationMetadata(
        calibrated_at="2026-11-20T08:00:00Z",
        dataset_version="v1.0",
        sample_size=20,
        precision=0.92,
        recall=0.88,
        f1=0.90,
        target_min_precision=0.85,
        optimal_threshold=0.75,
        termination_rate=0.75,
        unnecessary_escalation_rate=0.10,
        false_termination_rate=0.00,
    )


def test_state_not_configured() -> None:
    policy = L2ConfidencePolicy.create(threshold=None)
    assert policy.state is ThresholdCalibrationState.NOT_CONFIGURED
    assert not policy.is_calibrated
    assert not policy.can_terminate

    res = policy.evaluate([0.95, 0.82])
    assert not res.can_exit
    assert res.state is ThresholdCalibrationState.NOT_CONFIGURED
    assert res.escalated_to_l3
    assert "threshold not configured" in res.note


def test_state_configured_invalid() -> None:
    # Zero or negative
    p_zero = L2ConfidencePolicy.create(threshold=0.0)
    assert p_zero.state is ThresholdCalibrationState.CONFIGURED_INVALID
    assert not p_zero.can_terminate
    res_zero = p_zero.evaluate([0.80])
    assert not res_zero.can_exit
    assert "invalid" in res_zero.note

    p_neg = L2ConfidencePolicy.create(threshold=-0.5)
    assert p_neg.state is ThresholdCalibrationState.CONFIGURED_INVALID
    assert not p_neg.can_terminate


def test_state_configured_uncalibrated_cannot_terminate() -> None:
    """An uncalibrated threshold must never terminate retrieval alone, even with high scores."""
    policy = L2ConfidencePolicy.create(threshold=0.70, calibrated=False)
    assert policy.state is ThresholdCalibrationState.CONFIGURED_UNCALIBRATED
    assert not policy.is_calibrated
    assert not policy.can_terminate

    # Score of 0.95 would otherwise pass, but uncalibrated policy forbids termination
    res = policy.evaluate([0.95])
    assert not res.can_exit
    assert res.state is ThresholdCalibrationState.CONFIGURED_UNCALIBRATED
    assert res.escalated_to_l3
    assert "lacks calibration metadata" in res.note


def test_state_configured_calibrated(dummy_meta: CalibrationMetadata) -> None:
    policy = L2ConfidencePolicy.create(threshold=0.75, calibrated=True, metadata=dummy_meta)
    assert policy.state is ThresholdCalibrationState.CONFIGURED_CALIBRATED
    assert policy.is_calibrated
    assert policy.can_terminate

    # Score >= threshold passes and terminates
    res_pass = policy.evaluate([0.85, 0.70])
    assert res_pass.can_exit
    assert not res_pass.escalated_to_l3
    assert "passes calibrated threshold" in res_pass.note
    assert "P=0.92" in res_pass.note

    # Score < threshold fails to terminate and escalates
    res_fail = policy.evaluate([0.62])
    assert not res_fail.can_exit
    assert res_fail.escalated_to_l3
    assert "below calibrated threshold" in res_fail.note


def test_ladder_behavior_uncalibrated_vs_calibrated(dummy_meta: CalibrationMetadata) -> None:
    """Compare ladder execution: uncalibrated escalates to L3; calibrated exits at L2."""
    store = new_store()
    doc = IndexedDocument(
        canonical_id="AP-FIN01-GOMS-45-2023",
        subject="Transfer guidelines 2023",
        doc_type="G.O.Ms.",
        issue_date=dt.date(2023, 5, 10),
        tags=DocumentAccessTags(
            doc_id="D01", department="FIN01", section="ESTT", classification="UNCLASSIFIED"
        ),
    )
    index = InMemoryScopedIndex([doc])
    l2 = InMemoryKeywordIndex([(doc, "transfer guidelines for government employees")])
    graph = InMemoryGraphRepository()

    # 1. Uncalibrated config: score passes numerically, but policy prevents early exit
    cfg_uncal = LadderConfig(
        l2_top_k=5,
        l2_min_score=0.1,
        l3_max_hops=1,
        confidence_policy=L2ConfidencePolicy.create(threshold=0.1, calibrated=False),
    )
    req = LadderRequest(user_id="U01", text_query="transfer guidelines")
    res_uncal = run_ladder(
        req,
        index=index,
        l2=l2,
        graph=graph,
        cfg=cfg_uncal,
        store=store,
        policy=POLICY,
        classification=CLASSES,
    )

    l2_trace_uncal = next(t for t in res_uncal.trace if t.rung is LadderRung.L2)
    assert not l2_trace_uncal.exited
    assert l2_trace_uncal.calibration_state == "configured_uncalibrated"
    assert res_uncal.answered_by is None  # did not exit at L2!

    # 2. Calibrated config: score passes and policy authorizes early exit
    cfg_cal = LadderConfig(
        l2_top_k=5,
        l2_min_score=0.1,
        l3_max_hops=1,
        confidence_policy=L2ConfidencePolicy.create(
            threshold=0.1, calibrated=True, metadata=dummy_meta
        ),
    )
    res_cal = run_ladder(
        req,
        index=index,
        l2=l2,
        graph=graph,
        cfg=cfg_cal,
        store=store,
        policy=POLICY,
        classification=CLASSES,
    )

    l2_trace_cal = next(t for t in res_cal.trace if t.rung is LadderRung.L2)
    assert l2_trace_cal.exited
    assert l2_trace_cal.calibration_state == "configured_calibrated"
    assert res_cal.answered_by is LadderRung.L2  # confidently terminates at L2!


def test_calibration_dataset_sweep() -> None:
    dataset_path = REPO_ROOT / "evaluation" / "data" / "l2_validation_dataset.json"
    dataset = ValidationDataset.load(dataset_path)
    assert len(dataset.queries) >= 10

    predictions = [
        QueryPrediction(
            query_id="VAL-01",
            top_score=0.88,
            top_canonical_id="AP-FIN01-GOMS-45-2023",
            is_relevant_hit=True,
            expected_l2_termination=True,
        ),
        QueryPrediction(
            query_id="VAL-02",
            top_score=0.82,
            top_canonical_id="AP-FIN01-GOMS-15-2022",
            is_relevant_hit=True,
            expected_l2_termination=True,
        ),
        QueryPrediction(
            query_id="VAL-10",
            top_score=0.35,
            top_canonical_id="AP-FIN01-GOMS-45-2023",
            is_relevant_hit=False,
            expected_l2_termination=False,
        ),
        QueryPrediction(
            query_id="VAL-11",
            top_score=0.42,
            top_canonical_id="AP-FIN01-GOMS-15-2022",
            is_relevant_hit=False,
            expected_l2_termination=False,
        ),
    ]

    # Evaluate at threshold 0.70: relevant hits (0.88, 0.82) pass (TP=2); distractors fail (TN=2)
    eval_70 = evaluate_predictions_at_threshold(predictions, 0.70)
    assert eval_70.tp == 2
    assert eval_70.fp == 0
    assert eval_70.tn == 2
    assert eval_70.fn == 0
    assert eval_70.precision == 1.0
    assert eval_70.recall == 1.0
    assert eval_70.termination_rate == 0.50

    # Calibrate across candidates
    candidates = [0.40, 0.60, 0.75, 0.90]
    cal_res = calibrate_threshold(predictions, candidates, min_precision=0.85)
    assert cal_res.optimal_threshold in candidates
    assert cal_res.metadata.precision >= 0.85
    assert cal_res.metadata.optimal_threshold == cal_res.optimal_threshold


def test_monitoring_metrics_calculation() -> None:
    now = dt.datetime.now(dt.UTC)
    records = [
        # Query 1: Terminated at L2
        QueryRecord(
            query_id="Q1",
            ts=now,
            session_id="S1",
            turn=1,
            user_id="U01",
            department="FIN01",
            section="ESTT",
            role="Section Officer",
            query_hash="hash1",
            intent="precedent",
            entities=(),
            ladder_level="L2",
            retrieved_ids=("D01",),
            evidence_ids=("D01",),
            cited_ids=("D01",),
            conflicts_found=0,
            conflict_types=(),
            scope_signature="sig1",
            latency_ms=120,
            cache_hit=False,
            answer_status="answered",
        ),
        # Query 2: Escalated to L3 due to uncalibrated L2
        QueryRecord(
            query_id="Q2",
            ts=now,
            session_id="S2",
            turn=1,
            user_id="U01",
            department="FIN01",
            section="ESTT",
            role="Section Officer",
            query_hash="hash2",
            intent="precedent",
            entities=(),
            ladder_level="L2+L3",
            retrieved_ids=("D01", "D02"),
            evidence_ids=("D01",),
            cited_ids=("D01",),
            conflicts_found=0,
            conflict_types=(),
            scope_signature="sig1",
            latency_ms=350,
            cache_hit=False,
            answer_status="answered",
            flags=("uncalibrated",),
        ),
        # Query 3: Escalated to L3 because score was below calibrated threshold
        QueryRecord(
            query_id="Q3",
            ts=now,
            session_id="S3",
            turn=1,
            user_id="U01",
            department="FIN01",
            section="ESTT",
            role="Section Officer",
            query_hash="hash3",
            intent="precedent",
            entities=(),
            ladder_level="L2+L3",
            retrieved_ids=("D03",),
            evidence_ids=("D03",),
            cited_ids=(),
            conflicts_found=0,
            conflict_types=(),
            scope_signature="sig1",
            latency_ms=280,
            cache_hit=False,
            answer_status="answered",
        ),
    ]

    metrics = l2_monitoring_metrics(records)
    assert metrics.total_queries == 3
    assert metrics.l2_evaluated == 3
    assert metrics.l2_terminated == 1
    assert metrics.l2_escalated_to_l3 == 2
    assert metrics.termination_rate == round(1 / 3, 4)
    assert metrics.uncalibrated_escalations == 1
    assert metrics.below_threshold_escalations == 1
