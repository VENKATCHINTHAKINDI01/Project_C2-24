"""Calibrated confidence policy for L2 Hybrid Search (plan §3.2, §13.2; ADR-0061).

Distinguishes between four explicit states:
- NOT_CONFIGURED: Threshold is null / omitted. L2 hits cannot terminate retrieval alone.
- CONFIGURED_INVALID: Threshold is outside valid range (must be 0 < threshold <= 1) or non-numeric.
- CONFIGURED_UNCALIBRATED: Threshold is configured (e.g. arbitrary test stand-in), but lacks
  empirical validation against a representative dataset. An uncalibrated score MUST NOT silently
  be treated as a reliable confidence score.
- CONFIGURED_CALIBRATED: Threshold is empirically calibrated against a validation dataset with
  documented precision, recall, and false-positive metrics. Can terminate retrieval when score
  meets or exceeds threshold.
- SANDBOX_STAND_IN: a documented TEST value for the in-memory keyword stand-in (sandbox.yaml, unit
  tests). It ends the ladder exactly as the stand-in always has, is labelled as a stand-in in every
  trace, and is never a calibration: the cloud L2 can never be in this state.

Calibrated requires evidence (ADR-0061 addendum, 24 Nov 2026): `calibrated=True` without
calibration metadata, or with metadata whose threshold differs from the configured one, is
CONFIGURED_UNCALIBRATED. No metadata is ever filled in.

When L2 cannot confidently terminate, retrieval safely escalates to L3 without guessing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# scores that were not measured on a real retriever never calibrate anything
_NOT_MEASURED = ("simulat", "synthetic", "stand-in", "stand_in", "hard-coded", "mock")


class ThresholdCalibrationState(StrEnum):
    NOT_CONFIGURED = "not_configured"
    CONFIGURED_INVALID = "configured_invalid"
    CONFIGURED_UNCALIBRATED = "configured_uncalibrated"
    CONFIGURED_CALIBRATED = "configured_calibrated"
    SANDBOX_STAND_IN = "sandbox_stand_in"


class CalibrationMetadata(_Frozen):
    """Empirical calibration evidence supporting a configured threshold."""

    calibrated_at: str = Field(description="ISO 8601 timestamp of calibration")
    retriever: str = Field(
        min_length=1,
        description="Retriever whose real scores were measured, e.g. bigquery-hybrid@asia-south1",
    )
    dataset_version: str = Field(description="Validation dataset version/identifier")
    sample_size: int = Field(ge=1, description="Number of validation queries evaluated")
    precision: float = Field(ge=0.0, le=1.0, description="Precision achieved at threshold")
    recall: float = Field(ge=0.0, le=1.0, description="Recall achieved at threshold")
    f1: float = Field(ge=0.0, le=1.0, description="F1 score achieved at threshold")
    target_min_precision: float = Field(ge=0.0, le=1.0, description="Minimum acceptable precision")
    optimal_threshold: float = Field(gt=0.0, le=1.0, description="Selected confidence threshold")
    termination_rate: float = Field(
        ge=0.0, le=1.0, description="Proportion of queries terminating at L2"
    )
    unnecessary_escalation_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Relevant queries that failed to terminate at L2",
    )
    false_termination_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Irrelevant queries that incorrectly terminated at L2",
    )
    precision_ci_low: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Lower bound of the 95% Wilson interval of the precision (24 Nov 2026)",
    )
    min_margin: float | None = Field(
        default=None,
        ge=0.0,
        description="Score gap to the runner-up that was in force when measured",
    )
    safeguards: tuple[str, ...] = Field(
        default=(), description="Exit safeguards in force when measured (see SAFEGUARDS)"
    )


# The gates the ladder applies before a calibrated L2 exit (ladder.py; safeguards.py). A
# calibration counts only if it was measured with exactly these in force.
SAFEGUARDS: tuple[str, ...] = ("canonical_dedup", "attribute_gate", "graph_gate")


class L2EvaluationResult(_Frozen):
    """The outcome of evaluating an L2 candidate score set against the policy."""

    can_exit: bool
    max_score: float
    state: ThresholdCalibrationState
    threshold: float | None
    note: str
    escalated_to_l3: bool


class L2ConfidencePolicy(_Frozen):
    """Immutable policy governing whether L2 hybrid search can terminate retrieval early."""

    threshold: float | None = None
    margin: float | None = None
    state: ThresholdCalibrationState = ThresholdCalibrationState.NOT_CONFIGURED
    metadata: CalibrationMetadata | None = None

    @property
    def is_calibrated(self) -> bool:
        return self.state is ThresholdCalibrationState.CONFIGURED_CALIBRATED

    @property
    def can_terminate(self) -> bool:
        """Only a calibrated threshold (or the labelled sandbox stand-in) can end the ladder."""
        return self.threshold is not None and self.state in (
            ThresholdCalibrationState.CONFIGURED_CALIBRATED,
            ThresholdCalibrationState.SANDBOX_STAND_IN,
        )

    @classmethod
    def stand_in(cls, threshold: float) -> L2ConfidencePolicy:
        """The in-memory keyword stand-in's documented TEST threshold (sandbox.yaml, tests)."""
        val = float(threshold)
        if val <= 0.0:
            return cls(threshold=val, state=ThresholdCalibrationState.CONFIGURED_INVALID)
        return cls(threshold=val, state=ThresholdCalibrationState.SANDBOX_STAND_IN)

    def evaluate(self, scores: Sequence[float]) -> L2EvaluationResult:
        """Evaluate candidate scores against the confidence policy.

        Returns an L2EvaluationResult detailing whether early termination is authorized,
        the calibration state, and clear diagnostic explanations.
        """
        max_score = round(max(scores), 6) if scores else 0.0
        has_hits = len(scores) > 0

        # State 1: NOT_CONFIGURED
        if self.state is ThresholdCalibrationState.NOT_CONFIGURED or self.threshold is None:
            note = (
                "uncalibrated: threshold not configured (cannot terminate at L2 alone)"
                if has_hits
                else "no text query / no hits"
            )
            return L2EvaluationResult(
                can_exit=False,
                max_score=max_score,
                state=ThresholdCalibrationState.NOT_CONFIGURED,
                threshold=None,
                note=note,
                escalated_to_l3=has_hits,
            )

        # State 2: CONFIGURED_INVALID
        if self.state is ThresholdCalibrationState.CONFIGURED_INVALID:
            note = (
                f"uncalibrated: threshold {self.threshold} is invalid "
                f"(must be in (0, 1]; cannot terminate at L2)"
            )
            return L2EvaluationResult(
                can_exit=False,
                max_score=max_score,
                state=ThresholdCalibrationState.CONFIGURED_INVALID,
                threshold=self.threshold,
                note=note,
                escalated_to_l3=has_hits,
            )

        # State 3: CONFIGURED_UNCALIBRATED
        if self.state is ThresholdCalibrationState.CONFIGURED_UNCALIBRATED:
            note = (
                f"uncalibrated: threshold {self.threshold} lacks calibration metadata; "
                f"score {max_score:.4f} cannot be trusted to terminate (escalating to next rung)"
            )
            return L2EvaluationResult(
                can_exit=False,
                max_score=max_score,
                state=ThresholdCalibrationState.CONFIGURED_UNCALIBRATED,
                threshold=self.threshold,
                note=note,
                escalated_to_l3=has_hits,
            )

        # State 5: SANDBOX_STAND_IN (labelled TEST value; never the cloud L2)
        if self.state is ThresholdCalibrationState.SANDBOX_STAND_IN:
            ok = has_hits and max_score >= self.threshold
            return L2EvaluationResult(
                can_exit=ok,
                max_score=max_score,
                state=ThresholdCalibrationState.SANDBOX_STAND_IN,
                threshold=self.threshold,
                note=(
                    f"sandbox stand-in threshold {self.threshold} (test value, not a calibration): "
                    + ("passes" if ok else "below; escalating to next rung")
                ),
                escalated_to_l3=has_hits and not ok,
            )

        # State 4: CONFIGURED_CALIBRATED
        if self.metadata is None:  # unreachable through create(); never trusted without evidence
            raise ValueError("a calibrated policy needs its calibration metadata")
        if max_score >= self.threshold:
            if self.margin is not None and len(scores) >= 2:
                runner_up = round(scores[1], 6)
                delta = round(max_score - runner_up, 6)
                if delta < self.margin:
                    note = (
                        f"ambiguous candidate scores (top={max_score:.4f}, runner_up={runner_up:.4f}, "  # noqa: E501
                        f"delta={delta:.4f} < margin={self.margin:.4f}; escalating to next rung)"
                    )
                    return L2EvaluationResult(
                        can_exit=False,
                        max_score=max_score,
                        state=ThresholdCalibrationState.CONFIGURED_CALIBRATED,
                        threshold=self.threshold,
                        note=note,
                        escalated_to_l3=True,
                    )
            note = (
                f"passes calibrated threshold ({max_score:.4f} >= {self.threshold:.4f}, "
                f"P={self.metadata.precision:.2f}, R={self.metadata.recall:.2f})"
            )
            return L2EvaluationResult(
                can_exit=True,
                max_score=max_score,
                state=ThresholdCalibrationState.CONFIGURED_CALIBRATED,
                threshold=self.threshold,
                note=note,
                escalated_to_l3=False,
            )

        note = (
            f"below calibrated threshold ({max_score:.4f} < {self.threshold:.4f}; "
            f"escalating to next rung)"
        )
        return L2EvaluationResult(
            can_exit=False,
            max_score=max_score,
            state=ThresholdCalibrationState.CONFIGURED_CALIBRATED,
            threshold=self.threshold,
            note=note,
            escalated_to_l3=has_hits,
        )

    @classmethod
    def create(
        cls,
        threshold: float | None = None,
        *,
        calibrated: bool = False,
        metadata: CalibrationMetadata | Mapping[str, Any] | None = None,
        margin: float | None = None,
    ) -> L2ConfidencePolicy:
        """Factory enforcing state transitions and input validation."""
        m_val = float(margin) if margin is not None else None
        if threshold is None:
            return cls(
                threshold=None,
                margin=m_val,
                state=ThresholdCalibrationState.NOT_CONFIGURED,
                metadata=None,
            )

        try:
            val = float(threshold)
        except (TypeError, ValueError):
            return cls(
                threshold=None,
                margin=m_val,
                state=ThresholdCalibrationState.CONFIGURED_INVALID,
                metadata=None,
            )

        # In normalized hybrid scoring, thresholds must sit in (0, 1]
        # (For BM25 keyword stand-ins in legacy tests, values > 1.0 are allowed if calibrated=True)
        if val <= 0.0:
            return cls(
                threshold=val,
                margin=m_val,
                state=ThresholdCalibrationState.CONFIGURED_INVALID,
                metadata=None,
            )

        if not calibrated:
            return cls(
                threshold=val,
                margin=m_val,
                state=ThresholdCalibrationState.CONFIGURED_UNCALIBRATED,
                metadata=None,
            )

        # evidence or nothing: no metadata is ever invented (ADR-0061 addendum)
        meta_obj: CalibrationMetadata | None
        try:
            if isinstance(metadata, CalibrationMetadata):
                meta_obj = metadata
            elif isinstance(metadata, Mapping):
                meta_obj = CalibrationMetadata.model_validate(metadata)
            else:
                meta_obj = None
        except ValueError:
            meta_obj = None
        if (
            meta_obj is None
            or abs(meta_obj.optimal_threshold - val) > 1e-9
            or any(w in meta_obj.retriever.lower() for w in _NOT_MEASURED)
        ):
            return cls(
                threshold=val,
                margin=m_val,
                state=ThresholdCalibrationState.CONFIGURED_UNCALIBRATED,
                metadata=None,
            )
        # The exit must be measured under the conditions it will run with, and its precision
        # must clear the target at the low end of its 95% interval, not just on average
        # (agreed with the owner, 24 Nov 2026).
        if (
            meta_obj.precision < meta_obj.target_min_precision
            or meta_obj.precision_ci_low is None
            or meta_obj.precision_ci_low < meta_obj.target_min_precision
            or meta_obj.min_margin != m_val
            or set(meta_obj.safeguards) != set(SAFEGUARDS)
        ):
            return cls(
                threshold=val,
                margin=m_val,
                state=ThresholdCalibrationState.CONFIGURED_UNCALIBRATED,
                metadata=None,
            )

        return cls(
            threshold=val,
            margin=m_val,
            state=ThresholdCalibrationState.CONFIGURED_CALIBRATED,
            metadata=meta_obj,
        )
