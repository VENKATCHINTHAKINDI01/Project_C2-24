"""Typed AgentState: the one state object every agent reads and writes (plan §3.4, §8.1, §8.3).

No agent keeps private workflow state (CLAUDE.md §2.1). Each field maps to a query-log column and
an evaluation trace. Pydantic model (LangGraph accepts Pydantic state); frozen, so a node returns
an updated copy via `advance`, which validates the transition.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.intents import Intent, IntentSlots
from app.citation.verifier import AnswerStatus, Claim, Verification
from app.conflict.deterministic import ConflictFlag
from app.retrieval.evidence import EvidencePackage


class HitlFlag(StrEnum):
    """Plan §9.1 checkpoints raised during a request."""

    LOW_CONFIDENCE_EXTRACTION = "low_confidence_extraction"
    UNCONFIRMED_SUPERSESSION = "unconfirmed_supersession"
    CONFLICT_FLAGGED = "conflict_flagged"
    REVIEW_NEEDED_CLAIMS = "review_needed_claims"
    AMBIGUOUS_REFERENCE = "ambiguous_reference"
    NOTING_APPROVAL = "noting_approval"


class AgentState(BaseModel):
    """Plan §3.4. Holds IDs, metadata and the evidence package — never unfiltered documents."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    user: str = Field(min_length=1)  # user_id; grants are always re-read from the access store
    scope_signature: str | None = None
    raw_query: str = Field(min_length=1, max_length=4000)
    canonical_query: str | None = None
    intent: Intent | None = None
    slots: IntentSlots | None = None
    entities: tuple[str, ...] = ()  # resolved canonical IDs / file numbers
    as_of_date: dt.date
    ladder_level: str | None = None  # e.g. "L0+L3" (ladder_label)
    authorized_candidates: tuple[str, ...] = ()  # canonical IDs after scope + re-check
    evidence_package: EvidencePackage | None = None
    temporal_status: dict[str, str] = {}  # canonical_id → status as of as_of_date
    hierarchy_resolution: dict[str, str] = {}  # "A|B" → prevailing canonical_id
    conflicts: tuple[ConflictFlag, ...] = ()
    draft: tuple[Claim, ...] = ()  # structured claims, each with evidence_ids
    citations: tuple[str, ...] = ()  # evidence_ids cited by the draft
    verification: Verification | None = None
    answer_status: AnswerStatus | None = None  # answered | review_needed | no_answer
    hitl_flags: frozenset[HitlFlag] = frozenset()
    audit_ref: str | None = None

    @model_validator(mode="after")
    def _consistent(self) -> AgentState:
        pkg = self.evidence_package
        if pkg is not None:
            if pkg.user_id != self.user or pkg.request_id != self.request_id:
                raise ValueError("evidence package belongs to another request or user")
            if self.scope_signature != pkg.scope_signature:
                raise ValueError("evidence package built under a different scope")
            if not set(self.authorized_candidates) >= pkg.canonical_ids:
                raise ValueError("evidence package holds IDs that were not authorised candidates")
            known = {i.evidence_id for i in pkg.items}
            if not set(self.citations) <= known:
                raise ValueError("draft cites evidence outside the package")
        elif self.citations:
            raise ValueError("citations without an evidence package")
        if self.answer_status is not None and self.verification is None:
            raise ValueError("answer status is set only by citation verification")
        if self.verification is not None and self.answer_status != self.verification.answer_status:
            raise ValueError("answer status must equal the verification outcome")
        return self

    def advance(self, **changes: Any) -> AgentState:
        """Return the next state; re-validates the whole object (no silent invalid transitions)."""
        return AgentState.model_validate({**self.model_dump(), **changes})
