"""Unit tests for L2 Calibrated Confidence Policy (plan §3.2, §13.2; ADR-0061)."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app.auth.models import DocumentAccessTags
from app.auth.policy import scope_for
from app.config import REPO_ROOT
from app.graph.repository import (
    EdgeKind,
    GraphEdge,
    GraphNode,
    InMemoryGraphRepository,
)
from app.retrieval.calibration import (
    QueryPrediction,
    ValidationDataset,
    calibrate_threshold,
    evaluate_predictions_at_threshold,
)
from app.retrieval.confidence_policy import (
    SAFEGUARDS,
    CalibrationMetadata,
    L2ConfidencePolicy,
    ThresholdCalibrationState,
)
from app.retrieval.ladder import (
    InMemoryKeywordIndex,
    LadderConfig,
    LadderRequest,
    LadderRung,
    ScoredDocument,
    run_ladder,
)
from app.retrieval.safeguards import (
    verify_cross_candidate_graph,
    verify_entity_attributes,
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
        precision_ci_low=0.86,
        safeguards=SAFEGUARDS,
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


def test_ambiguity_margin_blocks_closely_tied_candidates(dummy_meta: CalibrationMetadata) -> None:
    """Safeguard A: When top hit and runner-up are tied within margin, forbid early exit (force L3)."""  # noqa: E501
    # KI-046 scenario: top hit is 0.8925, runner-up is 0.8873 (delta = 0.0052 < margin 0.030)
    p = L2ConfidencePolicy.create(
        threshold=0.88,
        calibrated=True,
        metadata=dummy_meta.model_copy(update={"optimal_threshold": 0.88, "min_margin": 0.030}),
        margin=0.030,
    )
    res_ki046 = p.evaluate([0.8925, 0.8873, 0.8306])
    assert not res_ki046.can_exit
    assert res_ki046.escalated_to_l3
    assert "ambiguous candidate scores" in res_ki046.note
    assert "delta=0.0052 < margin=0.0300" in res_ki046.note

    # KI-055 scenario: top hit is 0.8864, runner-up is 0.8841 (delta = 0.0023 < margin 0.030)
    res_ki055 = p.evaluate([0.8864, 0.8841, 0.8622])
    assert not res_ki055.can_exit
    assert res_ki055.escalated_to_l3
    assert "delta=0.0023 < margin=0.0300" in res_ki055.note


def test_ambiguity_margin_permits_unambiguous_early_exit(dummy_meta: CalibrationMetadata) -> None:
    """Clear separation (e.g. FIN01 / GAD01 sanctions) satisfies both threshold and margin."""
    p = L2ConfidencePolicy.create(
        threshold=0.88,
        calibrated=True,
        metadata=dummy_meta.model_copy(update={"optimal_threshold": 0.88, "min_margin": 0.030}),
        margin=0.030,
    )
    # Clear lead: top hit 0.9050, runner-up 0.8200 (delta = 0.0850 >= 0.030)
    res_clear = p.evaluate([0.9050, 0.8200, 0.7500])
    assert res_clear.can_exit
    assert not res_clear.escalated_to_l3
    assert "passes calibrated threshold" in res_clear.note


def test_single_canonical_candidate_permits_early_exit(dummy_meta: CalibrationMetadata) -> None:
    """Item 2: Single canonical candidate (len == 1) exits safely when score >= threshold without runner-up penalty."""  # noqa: E501
    p = L2ConfidencePolicy.create(
        threshold=0.88,
        calibrated=True,
        metadata=dummy_meta.model_copy(update={"optimal_threshold": 0.88, "min_margin": 0.030}),
        margin=0.030,
    )
    # Single candidate above threshold
    res_single = p.evaluate([0.9150])
    assert res_single.can_exit
    assert not res_single.escalated_to_l3
    assert "passes calibrated threshold" in res_single.note

    # Single candidate below threshold fails safely
    res_below = p.evaluate([0.8450])
    assert not res_below.can_exit
    assert res_below.escalated_to_l3


def test_canonical_document_deduplication_prevents_intra_document_margin_penalty(
    dummy_meta: CalibrationMetadata,
) -> None:
    """Item 1: Multiple passages from the same canonical document must be deduplicated before
    margin scoring.

    If passage 1 is 0.92 and passage 2 is 0.91 (both doc A), runner-up scoring must compare
    doc A against distinct doc B (0.82), NOT passage 2 of doc A.
    """
    store = new_store()
    doc_a = IndexedDocument(
        canonical_id="AP-FIN01-GOMS-1-2024",
        tags=DocumentAccessTags(
            doc_id="AP-FIN01-GOMS-1-2024", department="FIN01", classification="UNCLASSIFIED"
        ),
        doc_type="G.O.Ms.",
        issue_date=dt.date(2024, 1, 1),
        subject="Sanction of funds for computer equipment",
    )
    doc_b = IndexedDocument(
        canonical_id="AP-FIN01-GOMS-2-2024",
        tags=DocumentAccessTags(
            doc_id="AP-FIN01-GOMS-2-2024", department="FIN01", classification="UNCLASSIFIED"
        ),
        doc_type="G.O.Ms.",
        issue_date=dt.date(2024, 1, 2),
        subject="Office vehicle purchase authorization",
    )

    class MockMultiPassageRetriever:
        def search(self, query: str, scope: Any, top_k: int) -> list[ScoredDocument]:
            # Returns two passages from doc_a and one from doc_b
            return [
                ScoredDocument(doc=doc_a, score=0.9200),
                ScoredDocument(
                    doc=doc_a, score=0.9100
                ),  # Passage 2 of doc_a (delta=0.0100 < 0.030)
                ScoredDocument(
                    doc=doc_b, score=0.8200
                ),  # True distinct runner-up (delta=0.1000 >= 0.030)
            ]

    policy = L2ConfidencePolicy.create(
        threshold=0.88,
        calibrated=True,
        metadata=dummy_meta.model_copy(update={"optimal_threshold": 0.88, "min_margin": 0.030}),
        margin=0.030,
    )
    cfg = LadderConfig(
        l2_top_k=5,
        l2_min_score=0.88,
        l3_max_hops=1,
        confidence_policy=policy,
    )
    graph = InMemoryGraphRepository()
    for d in (doc_a, doc_b):
        graph.upsert_node(GraphNode(canonical_id=d.canonical_id, tags=d.tags))

    res = run_ladder(
        LadderRequest(user_id="U01", text_query="sanction of funds computer equipment"),
        index=InMemoryScopedIndex([doc_a, doc_b]),
        l2=MockMultiPassageRetriever(),
        graph=graph,
        cfg=cfg,
        store=store,
        policy=POLICY,
        classification=CLASSES,
    )

    # With deduplication, runner-up is doc_b (0.82), so delta is 0.10 >= 0.030 -> exits at L2!
    assert res.answered_by is LadderRung.L2
    l2_trace = [t for t in res.trace if t.rung is LadderRung.L2][0]
    assert l2_trace.exited
    assert "passes calibrated threshold" in l2_trace.note


def test_safeguard_c_exact_entity_attribute_blocks_ki106_mismatch() -> None:
    """Item 4 & 5: Safeguard C enforces discriminating attributes (B.P.Ed vs M.P.Ed) preventing KI-106 false exits."""  # noqa: E501
    ki106_query = (
        "School Education Department – The Andhra Pradesh Admission and Fee Regulatory Committee for "  # noqa: E501
        "professional courses offered in 15 Private Un-Aided Professional Colleges – Fixation of Fee "  # noqa: E501
        "structure and special fee for B.P.Ed course in the State of Andhra Pradesh for the block period "  # noqa: E501
        "2017 – 18 to 2019 – 20 – Notification"
    )
    mped_subject = (
        "School Education Department – The Andhra Pradesh Admission and Fee Regulatory Committee for "  # noqa: E501
        "professional courses offered in 15 Private Un-Aided Professional Colleges – Fixation of Fee "  # noqa: E501
        "structure and special fee for M.P.Ed course in the State of Andhra Pradesh for the block period "  # noqa: E501
        "2017 – 18 to 2019 – 20 – Notification"
    )
    bped_subject = (
        "School Education Department – The Andhra Pradesh Admission and Fee Regulatory Committee for "  # noqa: E501
        "professional courses offered in 15 Private Un-Aided Professional Colleges – Fixation of Fee "  # noqa: E501
        "structure and special fee for B.P.Ed course in the State of Andhra Pradesh for the block period "  # noqa: E501
        "2017 – 18 to 2019 – 20 – Notification"
    )

    # 1. Attribute mismatch: Query requests B.P.Ed, but candidate subject is M.P.Ed
    clean, reason = verify_entity_attributes(ki106_query, mped_subject)
    assert not clean
    assert "query specifies 'b.p.ed' but candidate specifies 'm.p.ed'" in str(reason)

    # 2. Matching attributes: Query requests B.P.Ed and candidate subject is B.P.Ed
    clean_match, reason_match = verify_entity_attributes(ki106_query, bped_subject)
    assert clean_match
    assert reason_match is None

    # 3. Other degree clusters: B.Ed vs M.Ed, Language Pandit vs B.Ed
    assert not verify_entity_attributes(
        "Fee structure for B.Ed colleges", "Fee structure for M.Ed colleges"
    )[0]
    assert not verify_entity_attributes(
        "Fee structure for Language Pandit course", "Fee structure for B.Ed course"
    )[0]

    # 4. Cadre / category discriminators (gazetted vs non-gazetted, assistant secretary vs section
    # officer)
    cadre_clean, cadre_reason = verify_entity_attributes(
        "Transfers of gazetted officers in School Education",
        "Transfers of non-gazetted officers in School Education",
    )
    assert not cadre_clean
    assert "query specifies cadre 'gazetted' but candidate specifies 'non-gazetted'" in str(
        cadre_reason
    )

    as_so_clean, as_so_reason = verify_entity_attributes(
        "Promotion of Section Officer to Assistant Secretary",
        "Promotion of Assistant Secretary to Deputy Secretary",
    )
    assert not as_so_clean

    # 5. Block period discriminators (2017-18 to 2019-20 vs 2016-17 to 2018-19)
    period_clean, period_reason = verify_entity_attributes(
        "Fixation of fee for block period 2017 – 18 to 2019 – 20",
        "Fixation of fee for block period 2016 – 17 to 2018 – 19",
    )
    assert not period_clean
    assert "block period" in str(period_reason)

    # 6. Explicit standalone year mismatch (2023 vs 2025)
    yr_clean, yr_reason = verify_entity_attributes(
        "Transfers ban relaxed orders 2023",
        "Transfers ban relaxed orders 2025",
    )
    assert not yr_clean
    assert "query specifies year '2023' but candidate specifies '2025'" in str(yr_reason)


def test_safeguard_b_cross_candidate_amends_supersedes_blocks_exit(
    dummy_meta: CalibrationMetadata,
) -> None:
    """Item 6 & 7: Top candidates linked by AMENDS or SUPERSEDES must NOT exit early at L2 (force L3)."""  # noqa: E501
    store = new_store()
    scope = scope_for("U01", store, POLICY, CLASSES)

    # Graph with Candidate A (original) and Candidate B (amending order)
    graph = InMemoryGraphRepository()
    for cid in ("AP-ESE01-GOMS-111-2016", "AP-ESE01-GOMS-119-2016"):
        graph.upsert_node(
            GraphNode(
                canonical_id=cid,
                tags=DocumentAccessTags(
                    doc_id=cid, department="ESE01", classification="UNCLASSIFIED"
                ),
            )
        )
    graph.upsert_edge(
        GraphEdge(
            source="AP-ESE01-GOMS-119-2016",
            target="AP-ESE01-GOMS-111-2016",
            kind=EdgeKind.AMENDS,
        )
    )

    # When both candidates are in the candidate set, AMENDS edge blocks early exit
    ok, note = verify_cross_candidate_graph(
        ["AP-ESE01-GOMS-119-2016", "AP-ESE01-GOMS-111-2016"],
        graph,
        scope,
    )
    assert not ok
    assert "linked by AMENDS" in str(note)

    # SUPERSEDES edge also blocks early exit
    graph_sup = InMemoryGraphRepository()
    for cid in ("AP-GAD01-GOMS-10-2020", "AP-GAD01-GOMS-20-2021"):
        graph_sup.upsert_node(
            GraphNode(
                canonical_id=cid,
                tags=DocumentAccessTags(
                    doc_id=cid, department="GAD01", classification="UNCLASSIFIED"
                ),
            )
        )
    graph_sup.upsert_edge(
        GraphEdge(
            source="AP-GAD01-GOMS-20-2021",
            target="AP-GAD01-GOMS-10-2020",
            kind=EdgeKind.SUPERSEDES,
        )
    )
    ok_sup, note_sup = verify_cross_candidate_graph(
        ["AP-GAD01-GOMS-20-2021", "AP-GAD01-GOMS-10-2020"],
        graph_sup,
        scope,
    )
    assert not ok_sup
    assert "linked by SUPERSEDES" in str(note_sup)


def test_safeguard_b_references_and_cites_do_not_block_exit() -> None:
    """Item 6: Non-binding contextual citations (REFERENCES / CITES) must NOT block L2 exit."""
    store = new_store()
    scope = scope_for("U01", store, POLICY, CLASSES)

    graph_ref = InMemoryGraphRepository()
    for cid in ("AP-FIN01-GOMS-10-2022", "AP-FIN01-GOMS-05-2020"):
        graph_ref.upsert_node(
            GraphNode(
                canonical_id=cid,
                tags=DocumentAccessTags(
                    doc_id=cid, department="FIN01", classification="UNCLASSIFIED"
                ),
            )
        )
    graph_ref.upsert_edge(
        GraphEdge(
            source="AP-FIN01-GOMS-10-2022",
            target="AP-FIN01-GOMS-05-2020",
            kind=EdgeKind.REFERENCES,
        )
    )

    # REFERENCES relation does NOT block exit
    ok_ref, note_ref = verify_cross_candidate_graph(
        ["AP-FIN01-GOMS-10-2022", "AP-FIN01-GOMS-05-2020"],
        graph_ref,
        scope,
    )
    assert ok_ref
    assert note_ref is None


def test_safeguard_b_graph_failure_fails_closed_escalating_to_l3() -> None:
    """Item 7: If graph inspection fails or is unavailable, retrieval must fail closed (escalate to L3)."""  # noqa: E501
    store = new_store()
    scope = scope_for("U01", store, POLICY, CLASSES)

    class BrokenGraph:
        def walk(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("Database connection lost during graph walk")

    ok_fail, note_fail = verify_cross_candidate_graph(
        ["AP-ESE01-GOMS-1-2020", "AP-ESE01-GOMS-2-2020"],
        BrokenGraph(),  # type: ignore[arg-type]
        scope,
    )
    assert not ok_fail
    assert "graph inspection unavailable" in str(note_fail)


def test_ladder_full_integration_with_attribute_and_graph_safeguards(
    dummy_meta: CalibrationMetadata,
) -> None:
    """Comprehensive test: verifies ladder integration of Safeguards A, B, and C."""
    store = new_store()
    doc_goms57 = IndexedDocument(
        canonical_id="AP-ESE01-GOMS-57-2017",
        tags=DocumentAccessTags(
            doc_id="AP-ESE01-GOMS-57-2017", department="ESE01", classification="UNCLASSIFIED"
        ),
        doc_type="G.O.Ms.",
        issue_date=dt.date(2017, 7, 25),
        subject="Fee structure for M.P.Ed course in Private Colleges for block period 2017-18 to 2019-20",  # noqa: E501
    )
    doc_goms58 = IndexedDocument(
        canonical_id="AP-ESE01-GOMS-58-2017",
        tags=DocumentAccessTags(
            doc_id="AP-ESE01-GOMS-58-2017", department="ESE01", classification="UNCLASSIFIED"
        ),
        doc_type="G.O.Ms.",
        issue_date=dt.date(2017, 7, 25),
        subject="Fee structure for B.P.Ed course in Private Colleges for block period 2017-18 to 2019-20",  # noqa: E501
    )

    class MockL2KI106Retriever:
        def search(self, query: str, scope: Any, top_k: int) -> list[ScoredDocument]:
            # Mismatched M.P.Ed order ranks #1 with high score 0.9200
            # Relevant B.P.Ed order ranks #2 with score 0.8850
            return [
                ScoredDocument(doc=doc_goms57, score=0.9200),
                ScoredDocument(doc=doc_goms58, score=0.8850),
            ]

    policy = L2ConfidencePolicy.create(
        threshold=0.88,
        calibrated=True,
        metadata=dummy_meta.model_copy(update={"optimal_threshold": 0.88, "min_margin": 0.030}),
        margin=0.030,
    )
    cfg = LadderConfig(
        l2_top_k=5,
        l2_min_score=0.88,
        l3_max_hops=1,
        confidence_policy=policy,
    )
    graph = InMemoryGraphRepository()
    for d in (doc_goms57, doc_goms58):
        graph.upsert_node(GraphNode(canonical_id=d.canonical_id, tags=d.tags))

    # Query explicitly asks for B.P.Ed:
    res = run_ladder(
        LadderRequest(
            user_id="U01",
            text_query="Fee structure for B.P.Ed course in Private Colleges for block period 2017-18 to 2019-20",  # noqa: E501
            relations=frozenset({EdgeKind.AMENDS, EdgeKind.SUPERSEDES}),
        ),
        index=InMemoryScopedIndex([doc_goms57, doc_goms58]),
        l2=MockL2KI106Retriever(),
        graph=graph,
        cfg=cfg,
        store=store,
        policy=POLICY,
        classification=CLASSES,
    )

    # Safeguard C catches the B.P.Ed vs M.P.Ed attribute mismatch on rank 1!
    # L2 early exit is BLOCKED and escalated to L3!
    l2_trace = [t for t in res.trace if t.rung is LadderRung.L2][0]
    assert not l2_trace.exited
    assert "attribute mismatch" in l2_trace.note
    assert "query specifies 'b.p.ed' but candidate specifies 'm.p.ed'" in l2_trace.note
    assert res.answered_by is not LadderRung.L2


# --- 24 Nov 2026 (owner): an exit counts only if measured as it will run, with a safe lower bound


@pytest.mark.parametrize(
    ("update", "margin"),
    [
        ({"precision_ci_low": None}, None),  # no interval recorded
        ({"precision_ci_low": 0.77}, None),  # point estimate fine, lower bound under target
        ({"min_margin": 0.03}, None),  # measured with a margin the app does not run
        ({}, 0.03),  # app runs a margin that was not measured
        ({"safeguards": ("canonical_dedup",)}, None),  # measured without the ladder's gates
    ],
)
def test_calibration_must_match_how_the_exit_runs(
    dummy_meta: CalibrationMetadata, update: dict[str, object], margin: float | None
) -> None:
    meta = dummy_meta.model_copy(update={"optimal_threshold": 0.75, **update})
    p = L2ConfidencePolicy.create(threshold=0.75, calibrated=True, metadata=meta, margin=margin)
    assert p.state is ThresholdCalibrationState.CONFIGURED_UNCALIBRATED
    assert not p.is_calibrated


def test_calibration_measured_as_it_runs_is_accepted(dummy_meta: CalibrationMetadata) -> None:
    meta = dummy_meta.model_copy(update={"optimal_threshold": 0.75, "min_margin": 0.03})
    p = L2ConfidencePolicy.create(threshold=0.75, calibrated=True, metadata=meta, margin=0.03)
    assert p.state is ThresholdCalibrationState.CONFIGURED_CALIBRATED


def test_attribute_gate_reads_spaced_and_hyphenated_terms_alike() -> None:
    """Config-driven gate (24 Nov 2026): "Non Gazetted" was read as "gazetted" before."""
    from app.retrieval.safeguards import verify_entity_attributes

    assert verify_entity_attributes("Non Gazetted staff transfers", "non-gazetted employees")[0]
    ok, note = verify_entity_attributes("Non Gazetted staff transfers", "Gazetted officers")
    assert not ok and "non-gazetted" in (note or "")
    assert not verify_entity_attributes("BPEd admissions", "M.P.Ed admissions")[0]
