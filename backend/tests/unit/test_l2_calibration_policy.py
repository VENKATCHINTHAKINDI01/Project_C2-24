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
        retriever="bigquery-hybrid@asia-south1",
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
            threshold=0.1,
            calibrated=True,
            metadata=dummy_meta.model_copy(update={"optimal_threshold": 0.1}),
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
    cal_res = calibrate_threshold(
        predictions, candidates, min_precision=0.85, retriever="test predictions"
    )
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


# ---- calibrated needs evidence (ADR-0061 addendum, 24 Nov 2026) -------------------------------


def test_calibrated_without_evidence_is_uncalibrated(dummy_meta: CalibrationMetadata) -> None:
    """No metadata is ever filled in; evidence that does not match is not evidence."""
    unc = ThresholdCalibrationState.CONFIGURED_UNCALIBRATED
    assert L2ConfidencePolicy.create(threshold=0.75, calibrated=True).state is unc
    assert L2ConfidencePolicy.create(0.5, calibrated=True, metadata=dummy_meta).state is unc
    for fake in ("simulated scores", "synthetic-v1", "keyword stand-in", "hard-coded map"):
        meta = dummy_meta.model_copy(update={"retriever": fake})
        assert L2ConfidencePolicy.create(0.75, calibrated=True, metadata=meta).state is unc
    weak = dummy_meta.model_copy(update={"precision": 0.80})  # below its own target
    assert L2ConfidencePolicy.create(0.75, calibrated=True, metadata=weak).state is unc
    assert L2ConfidencePolicy.create(0.75, calibrated=True, metadata={"x": 1}).state is unc
    with pytest.raises(ValueError):
        CalibrationMetadata.model_validate({**dummy_meta.model_dump(), "retriever": ""})


def test_a_direct_ladder_config_is_a_labelled_stand_in_never_calibrated() -> None:
    cfg = LadderConfig(l2_top_k=5, l2_min_score=1.0, l3_max_hops=1)
    p = cfg.confidence_policy
    assert p is not None and p.state is ThresholdCalibrationState.SANDBOX_STAND_IN
    assert not p.is_calibrated and p.metadata is None and p.can_terminate
    res = p.evaluate([1.4])
    assert res.can_exit and "stand-in" in res.note and "not a calibration" in res.note
    assert not p.evaluate([0.6]).can_exit


def test_the_shipped_runtime_config_is_not_calibrated() -> None:
    """runtime.yaml is uncalibrated until a measured calibration replaces it (no fake evidence)."""
    from app.config import load_runtime_config
    from app.retrieval.graph_expansion import NotCalibratedError

    rt = load_runtime_config(REPO_ROOT / "backend" / "config" / "runtime.yaml")
    assert rt.retrieval.l2_rerank_min_score is None and not rt.retrieval.l2_calibrated
    assert rt.retrieval.l2_calibration_metadata is None
    with pytest.raises(NotCalibratedError):
        LadderConfig.from_runtime(rt)


def test_a_dataset_naming_records_that_do_not_exist_is_refused() -> None:
    import sys

    sys.path.insert(0, str(REPO_ROOT))
    from evaluation.calibrate_l2 import missing_ids

    ds = ValidationDataset.load(REPO_ROOT / "evaluation" / "data" / "l2_validation_dataset.json")
    known = {"AP-FIN01-GOMS-45-2023", "AP-FIN01-GOMS-31-2025"}
    gone = missing_ids(ds, lambda uid, cid: cid in known)
    assert gone and all(c.split(": ")[1] not in known for c in gone)
    assert not missing_ids(ds, lambda uid, cid: True)


def test_known_item_set_is_built_from_the_corpus_itself() -> None:
    import sys

    sys.path.insert(0, str(REPO_ROOT))
    from evaluation.build_l2_validation import build, query_of

    assert query_of("Transfers – Ban relaxed – Orders – G.O.Ms.No.31, Dt.12-05-2025 [Read]") == (
        "Transfers – Ban relaxed"
    )
    metas = [
        {"canonical_id": f"AP-FIN01-GOMS-{i}-2024", "department_code": "FIN01",
         "classification": "UNCLASSIFIED",
         "subject": f"Revision of pay scales for category {i} employees in the department"}
        for i in range(1, 6)
    ] + [
        {"canonical_id": "AP-GAZ-GAZETTE-WI-1-2024", "department_code": "GAZ",
         "classification": "UNCLASSIFIED", "subject": "Gazette copy of the revision of pay scales",
         "republishes_id": "AP-FIN01-GOMS-1-2024"},
        {"canonical_id": "AP-GAD01-GOMS-9-2024", "department_code": "GAD01",
         "classification": "RESTRICTED", "subject": "A restricted order is never a query item"},
    ]  # fmt: skip
    ds = build(metas, n=10, user="V14", seed=7)
    ids = [q["relevant_canonical_ids"] for q in ds["queries"]]
    assert len(ids) == 5 and all(i[0].startswith("AP-FIN01-GOMS-") for i in ids)
    assert ["AP-FIN01-GOMS-1-2024", "AP-GAZ-GAZETTE-WI-1-2024"] in ids  # its Gazette copy counts
    assert build(metas, n=10, user="V14", seed=7) == ds  # reproducible
