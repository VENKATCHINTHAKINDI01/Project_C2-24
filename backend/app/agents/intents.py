"""Intent templates: intent + validated slots → a fixed, parameterised LadderRequest (plan §3.2
'Templates', §5.6, CLAUDE.md §3).

The orchestrator (later, Gemini) only classifies the intent and fills slots. Slots are validated
here — canonical IDs must parse, terms are bounded words, free text is length-capped — and the
template, not the model, decides which rungs and relations are used. The model never writes
SQL, graph queries or retrieval queries.
"""

from __future__ import annotations

import datetime as dt
import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.graph.repository import Direction, EdgeKind
from app.identifiers.canonical import InvalidCanonicalIdError, parse_canonical_id
from app.retrieval.ladder import LadderRequest
from app.retrieval.scoped import L1Criteria


class Intent(StrEnum):
    PRECEDENT_LOOKUP = "precedent_lookup"  # "has this been decided before?"
    CURRENT_RULE = "current_rule"  # "what are the current guidelines on X?"
    DOCUMENT_STATUS = "document_status"  # "is G.O./circular X still valid?"
    CLAUSE_LOOKUP = "clause_lookup"  # "what does para 2(v) of G.O. X say?"
    SUPERSESSION_CHAIN = "supersession_chain"  # "what replaced X, and what did X replace?"
    DECISION_HISTORY = "decision_history"  # "what was decided on this file?"
    CONFLICT_CHECK = "conflict_check"  # "check this file against the current orders"


SUPERSESSION = frozenset(
    {EdgeKind.SUPERSEDES, EdgeKind.REPEALS, EdgeKind.AMENDS, EdgeKind.CLARIFIES}
)
RELATED = SUPERSESSION | {EdgeKind.REFERENCES}
ORDER_TYPES = frozenset(
    {"Government Order", "Amendment", "Circular", "Clarification", "Standing Order"}
)
NOTE_TYPES = frozenset({"Noting"})
_TERM = re.compile(r"^[\w.\-/()]{1,40}$", re.UNICODE)


class SlotError(ValueError):
    """Slots failed validation; the orchestrator must re-ask, never fall back to free text."""


class IntentSlots(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical_ids: tuple[str, ...] = Field(default=(), max_length=10)
    department: str | None = Field(default=None, pattern=r"^[A-Z]{2,6}\d{2}$")
    terms: tuple[str, ...] = Field(default=(), max_length=8)
    issued_from: dt.date | None = None
    issued_to: dt.date | None = None
    text: str | None = Field(default=None, max_length=500)  # only ever used as an L2 query

    @field_validator("canonical_ids")
    @classmethod
    def _ids_parse(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for cid in v:
            try:
                parse_canonical_id(cid)
            except InvalidCanonicalIdError as exc:
                raise ValueError(f"not a canonical ID: {cid!r}") from exc
        return v

    @field_validator("terms")
    @classmethod
    def _terms_are_words(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        bad = [t for t in v if not _TERM.match(t)]
        if bad:
            raise ValueError(f"terms must be single words: {bad!r}")
        return v


def _need(cond: bool, msg: str) -> None:
    if not cond:
        raise SlotError(msg)


def build_request(intent: Intent, slots: IntentSlots, user_id: str) -> LadderRequest:
    """The template table (plan §3.2). One fixed shape per intent; tested against golden levels."""
    s = slots
    if intent is Intent.PRECEDENT_LOOKUP:
        _need(bool(s.text or s.terms), "precedent lookup needs a description of the case")
        return LadderRequest(user_id=user_id, text_query=s.text or " ".join(s.terms))
    if intent is Intent.CURRENT_RULE:
        _need(bool(s.terms), "current rule needs subject terms")
        crit = L1Criteria(
            department=s.department,
            doc_types=ORDER_TYPES,
            subject_terms=s.terms,
            issued_from=s.issued_from,
            issued_to=s.issued_to,
        )
        return LadderRequest(user_id=user_id, criteria=crit)
    if intent in (Intent.DOCUMENT_STATUS, Intent.SUPERSESSION_CHAIN):
        _need(bool(s.canonical_ids), "needs the document's canonical ID")
        return LadderRequest(
            user_id=user_id,
            canonical_ids=s.canonical_ids,
            relations=RELATED,
            direction=Direction.BOTH,
        )
    if intent is Intent.CLAUSE_LOOKUP:
        _need(len(s.canonical_ids) == 1, "clause lookup needs exactly one canonical ID")
        return LadderRequest(user_id=user_id, canonical_ids=s.canonical_ids)
    if intent is Intent.DECISION_HISTORY:
        _need(bool(s.terms), "decision history needs subject terms")
        crit = L1Criteria(department=s.department, doc_types=NOTE_TYPES, subject_terms=s.terms)
        return LadderRequest(
            user_id=user_id, criteria=crit, relations=frozenset({EdgeKind.SAME_FILE})
        )
    if intent is Intent.CONFLICT_CHECK:
        _need(bool(s.canonical_ids), "conflict check needs the cited references' IDs")
        return LadderRequest(
            user_id=user_id,
            canonical_ids=s.canonical_ids,
            relations=SUPERSESSION | {EdgeKind.CITES},
            direction=Direction.IN,
        )
    raise SlotError(f"no template for intent {intent!r}")
