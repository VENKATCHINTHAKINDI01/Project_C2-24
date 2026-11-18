"""Human review queue (plan §9.1 checkpoint 5, §4.2, §7.3; CLAUDE.md §8).

Uncertain ingestion decisions wait here for a human before becoming citable "truth": low-
confidence extractions, unsupported files, inferred supersessions, unresolvable references,
ID collisions and date mismatches. Every decision records the reviewer, action, time, affected
record/version and reason. Items are never deleted; a decision is final and itself auditable.
Feedback is evaluation data in the PoC; it never silently changes policy (CLAUDE.md §8).
In-memory reference store; a Cloud SQL table replaces it with the same behaviour.
"""

from __future__ import annotations

import datetime as dt
import itertools
import threading
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ReviewKind(StrEnum):
    LOW_CONFIDENCE_EXTRACTION = "low_confidence_extraction"
    UNSUPPORTED_FILE = "unsupported_file"
    INFERRED_SUPERSESSION = "inferred_supersession"
    UNRESOLVED_REFERENCE = "unresolved_reference"
    ID_COLLISION = "id_collision"
    DATE_MISMATCH = "date_mismatch"
    CLASSIFICATION_MISMATCH = "classification_mismatch"
    DEPARTMENT_MISMATCH = "department_mismatch"  # text names another department (ADR-0011)


class ReviewState(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ReviewItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str
    kind: ReviewKind
    subject: str  # document / relation / reference the item is about (IDs only, no text)
    version: str  # record version the decision applies to (e.g. extraction run, sha256)
    reason: str = Field(max_length=500)
    created_at: dt.datetime
    state: ReviewState = ReviewState.PENDING
    reviewer: str | None = None
    decided_at: dt.datetime | None = None
    decision_reason: str | None = None


class ReviewError(Exception):
    pass


class ReviewQueue:
    def __init__(self) -> None:
        self._items: dict[str, ReviewItem] = {}
        self._seq = itertools.count(1)
        self._lock = threading.RLock()  # submits and decisions race with listings (ADR-0039)

    def _all(self) -> list[ReviewItem]:
        with self._lock:
            return list(self._items.values())

    def submit(
        self, kind: ReviewKind, subject: str, version: str, reason: str, at: dt.datetime
    ) -> ReviewItem:
        """Idempotent per (kind, subject, version): re-ingesting the same file adds no duplicate."""
        with self._lock:
            return self._submit(kind, subject, version, reason, at)

    def _submit(
        self, kind: ReviewKind, subject: str, version: str, reason: str, at: dt.datetime
    ) -> ReviewItem:
        for item in self._items.values():
            if (item.kind, item.subject, item.version) == (kind, subject, version):
                return item
        item = ReviewItem(
            item_id=f"RV-{next(self._seq):06d}",
            kind=kind,
            subject=subject,
            version=version,
            reason=reason,
            created_at=at,
        )
        self._items[item.item_id] = item
        return item

    def decide(
        self, item_id: str, *, reviewer: str, confirm: bool, reason: str, at: dt.datetime
    ) -> ReviewItem:
        with self._lock:
            return self._decide(item_id, reviewer=reviewer, confirm=confirm, reason=reason, at=at)

    def _decide(
        self, item_id: str, *, reviewer: str, confirm: bool, reason: str, at: dt.datetime
    ) -> ReviewItem:
        item = self._items.get(item_id)
        if item is None:
            raise ReviewError("unknown review item")
        if item.state is not ReviewState.PENDING:
            raise ReviewError("already decided; submit a new item to revisit")
        if not reviewer.strip() or not reason.strip():
            raise ReviewError("reviewer identity and reason are required")
        decided = item.model_copy(
            update={
                "state": ReviewState.CONFIRMED if confirm else ReviewState.REJECTED,
                "reviewer": reviewer,
                "decided_at": at,
                "decision_reason": reason,
            }
        )
        self._items[item_id] = decided
        return decided

    def pending(self, kind: ReviewKind | None = None) -> tuple[ReviewItem, ...]:
        return tuple(
            i
            for i in self._all()
            if i.state is ReviewState.PENDING and (kind is None or i.kind is kind)
        )

    def blocks(self, subject: str, version: str) -> bool:
        """True while any item for this record version is pending or was rejected."""
        return any(
            i.subject == subject and i.version == version and i.state is not ReviewState.CONFIRMED
            for i in self._all()
        )

    def history(self) -> tuple[ReviewItem, ...]:
        return tuple(self._all())
