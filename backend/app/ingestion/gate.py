"""Extraction-confidence gate (plan §4.2; CLAUDE.md §5.3).

A bad extraction means a bad citation, so low-confidence extractions are held out of the index in
the review queue until a human confirms. Native text (a real text layer, DOCX, TXT) is exact and
passes. OCR'd pages are gated by `ingestion.extraction_confidence_min` (runtime.yaml). While that
threshold is uncalibrated (`null`), EVERY OCR'd extraction goes to review — the safe default, no
guessed number. Unsupported files always go to review.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.hitl.queue import ReviewItem, ReviewKind, ReviewQueue
from app.ingestion.detect import Detection, Route


class GateOutcome(StrEnum):
    INDEX = "index"  # trusted evidence
    HOLD = "hold"  # held out of the index pending review


class Extraction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    doc_id: str
    version: str  # e.g. sha256 of the file + extractor version
    detection: Detection
    page_confidence: dict[int, float] = {}  # OCR pages only: 1-based page → [0, 1]
    native_pages: tuple[int, ...] = ()


class GateDecision(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: GateOutcome
    reason: str
    min_confidence: float | None = Field(default=None, ge=0, le=1)
    review_item: ReviewItem | None = None


def gate(
    ex: Extraction, threshold: float | None, queue: ReviewQueue, at: dt.datetime
) -> GateDecision:
    """Plan §4.2. Re-gating the same version is idempotent (no duplicate review items)."""

    def hold(kind: ReviewKind, reason: str, low: float | None = None) -> GateDecision:
        item = queue.submit(kind, ex.doc_id, ex.version, reason, at)
        return GateDecision(
            outcome=GateOutcome.HOLD, reason=reason, min_confidence=low, review_item=item
        )

    route = ex.detection.route
    if route is Route.UNSUPPORTED:
        return hold(ReviewKind.UNSUPPORTED_FILE, ex.detection.reason or "unsupported file")
    needs_ocr: set[int] = set()
    if route in (Route.OCR, Route.OCR_PREPROCESS, Route.PER_PAGE):
        needs_ocr = set(ex.detection.ocr_pages) or {1}  # a photo is one page
    if not needs_ocr:
        return GateDecision(outcome=GateOutcome.INDEX, reason="native text")
    missing = needs_ocr - set(ex.page_confidence)
    if missing:
        return hold(
            ReviewKind.LOW_CONFIDENCE_EXTRACTION, f"no OCR confidence for pages {sorted(missing)}"
        )
    low = min(ex.page_confidence[p] for p in needs_ocr)
    if threshold is None:
        return hold(
            ReviewKind.LOW_CONFIDENCE_EXTRACTION, "confidence threshold not calibrated", low
        )
    if low < threshold:
        return hold(
            ReviewKind.LOW_CONFIDENCE_EXTRACTION, f"OCR confidence {low:.2f} < {threshold:.2f}", low
        )
    if queue.blocks(ex.doc_id, ex.version):
        return GateDecision(
            outcome=GateOutcome.HOLD, reason="earlier review not confirmed", min_confidence=low
        )
    return GateDecision(
        outcome=GateOutcome.INDEX, reason="OCR confidence passes", min_confidence=low
    )


def indexable(ex: Extraction, decision: GateDecision, queue: ReviewQueue) -> bool:
    """A held extraction becomes indexable only after a human CONFIRMS its review item."""
    if decision.outcome is GateOutcome.INDEX:
        return True
    return not queue.blocks(ex.doc_id, ex.version)
