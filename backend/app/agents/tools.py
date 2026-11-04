"""Bounded agent tools (plan §5.6): a fixed set, each backed by a retrieval template and each
re-checking authorization internally. No tool accepts a free-form query; arguments are validated
slots or canonical IDs. Results carry IDs and metadata only — document text reaches the model
solely through the evidence package (plan §3.3).

Leakage rules (plan §5.4): "not available" is the same for absent and forbidden documents;
temporal facts are computed only over records the officer may see. Status coverage (owner
decision, 3 Nov 2026): a status or "current version" is reported ONLY when the officer's scope
covers every record that could change it (`Scope.covers_status_domain`, policy
`status_coverage`). Otherwise the generic STATUS_UNCONFIRMED message is returned — decided from
the scope alone, so it appears whether or not a hidden superseding order exists.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.agents.intents import Intent, IntentSlots, build_request
from app.auth.models import AccessPolicy, StatusCoverage
from app.auth.policy import ScopeError, check, scope_for
from app.auth.store import AuthzStore
from app.config import Classification, Hierarchy
from app.graph.repository import InMemoryGraphRepository
from app.retrieval.ladder import (
    HybridRetriever,
    LadderConfig,
    LadderResult,
    ladder_label,
    run_ladder,
)
from app.retrieval.scoped import IndexedDocument, Rung, ScopedRetriever, retrieve
from app.temporal.engine import (
    Instrument,
    Precedence,
    Status,
    TemporalRelation,
    applicable_version,
    resolve_precedence,
    status_as_of,
)

STATUS_UNCONFIRMED = (
    "I can't confirm this order's current status from the records available to you. "
    "Please check with the section."
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool needs for ONE request. `user_id` comes from the authenticated session,
    never from the model; grants are re-read from `store` on every call."""

    user_id: str
    as_of: dt.date
    index: ScopedRetriever
    l2: HybridRetriever
    graph: InMemoryGraphRepository
    cfg: LadderConfig
    store: AuthzStore
    policy: AccessPolicy
    classification: Classification
    hierarchy: Hierarchy
    instruments: Mapping[str, Instrument]  # temporal facts (BigQuery/Spanner later)
    relations: tuple[TemporalRelation, ...]


class DocRef(_Frozen):
    canonical_id: str
    doc_type: str
    subject: str
    issue_date: dt.date | None


class ToolResult(_Frozen):
    tool: str
    available: bool  # False is identical for "absent" and "not permitted"
    documents: tuple[DocRef, ...] = ()
    status: str | None = None
    current_version: str | None = None
    precedence: Precedence | None = None
    ladder_level: str | None = None
    status_unconfirmed: tuple[DocRef, ...] = ()  # found, but status not reportable (coverage)
    message: str | None = None


class ToolError(ValueError):
    """Unknown tool or invalid arguments; the orchestrator must re-plan, never improvise."""


def _ref(d: IndexedDocument) -> DocRef:
    return DocRef(
        canonical_id=d.canonical_id, doc_type=d.doc_type, subject=d.subject, issue_date=d.issue_date
    )


def _ladder(ctx: ToolContext, intent: Intent, slots: IntentSlots) -> LadderResult:
    return run_ladder(
        build_request(intent, slots, ctx.user_id),
        index=ctx.index,
        l2=ctx.l2,
        graph=ctx.graph,
        cfg=ctx.cfg,
        store=ctx.store,
        policy=ctx.policy,
        classification=ctx.classification,
    )


def _visible(ctx: ToolContext, cid: str) -> IndexedDocument | None:
    res = retrieve(
        ctx.user_id,
        Rung.L0,
        cid,
        retriever=ctx.index,
        store=ctx.store,
        policy=ctx.policy,
        classification=ctx.classification,
    )
    hit = next((d for d in res.documents if d.canonical_id == cid), None)
    if hit is None:
        return None
    ok = check(ctx.user_id, hit.tags, ctx.store, ctx.policy, ctx.classification).allowed
    return hit if ok else None


def _status_covered(ctx: ToolContext, doc: IndexedDocument) -> bool:
    """Scope-only test (no record lookups): could this officer see everything that might change
    the order's status? Fails closed on any scope problem."""
    try:
        scope = scope_for(ctx.user_id, ctx.store, ctx.policy, ctx.classification)
    except ScopeError:
        return False
    if ctx.policy.status_coverage is StatusCoverage.UP_TO_DOCUMENT:
        ceiling = doc.tags.classification
    else:
        ceiling = max(ctx.classification.levels, key=lambda lv: lv.rank).name
    return scope.covers_status_domain(doc.tags.department, ceiling)


def _visible_facts(
    ctx: ToolContext, ids: set[str]
) -> tuple[dict[str, Instrument], list[TemporalRelation]]:
    """Temporal facts restricted to what this officer may see (no restricted successor leaks)."""
    seen = {
        cid
        for cid in ids | {r.source for r in ctx.relations} | {r.target for r in ctx.relations}
        if cid in ctx.instruments and _visible(ctx, cid) is not None
    }
    inst = {cid: ctx.instruments[cid] for cid in seen}
    rels = [r for r in ctx.relations if r.source in seen and r.target in seen]
    return inst, rels


# ---- the tool set (plan §5.6) -----------------------------------------------------------------


def search_authorized_documents(ctx: ToolContext, slots: IntentSlots) -> ToolResult:
    intent = Intent.PRECEDENT_LOOKUP if slots.text else Intent.CURRENT_RULE
    res = _ladder(ctx, intent, slots)
    return ToolResult(
        tool="search_authorized_documents",
        available=bool(res.documents),
        documents=tuple(_ref(d) for d in res.documents),
        ladder_level=ladder_label(res),
    )


def get_document(ctx: ToolContext, canonical_id: str) -> ToolResult:
    doc = _visible(ctx, canonical_id)
    if doc is None:
        return ToolResult(tool="get_document", available=False)
    return ToolResult(
        tool="get_document", available=True, documents=(_ref(doc),), ladder_level="L0"
    )


def find_precedents(ctx: ToolContext, slots: IntentSlots) -> ToolResult:
    res = _ladder(ctx, Intent.PRECEDENT_LOOKUP, slots)
    notes = tuple(_ref(d) for d in res.documents if d.doc_type.startswith("Noting"))
    return ToolResult(
        tool="find_precedents", available=bool(notes), documents=notes, ladder_level="L2"
    )


def get_current_rules(ctx: ToolContext, slots: IntentSlots) -> ToolResult:
    """Rules in force on `ctx.as_of`, each replaced by its applicable visible version."""
    res = _ladder(ctx, Intent.CURRENT_RULE, slots)
    inst, rels = _visible_facts(ctx, {d.canonical_id for d in res.documents})
    current: dict[str, IndexedDocument] = {}
    unconfirmed: dict[str, IndexedDocument] = {}
    for d in res.documents:
        if d.canonical_id not in inst:
            continue
        if not _status_covered(ctx, d):
            unconfirmed.setdefault(d.canonical_id, d)
            continue
        version = applicable_version(d.canonical_id, ctx.as_of, inst, rels)
        if version is not None and (doc := _visible(ctx, version)) is not None:
            current.setdefault(version, doc)
    return ToolResult(
        tool="get_current_rules",
        available=bool(current or unconfirmed),
        documents=tuple(_ref(d) for d in current.values()),
        status_unconfirmed=tuple(_ref(d) for d in unconfirmed.values()),
        message=STATUS_UNCONFIRMED if unconfirmed else None,
        ladder_level="L1",
    )


def check_document_status(ctx: ToolContext, canonical_id: str) -> ToolResult:
    doc = _visible(ctx, canonical_id)
    if doc is None or canonical_id not in ctx.instruments:
        return ToolResult(tool="check_document_status", available=False)
    if not _status_covered(ctx, doc):
        return ToolResult(
            tool="check_document_status",
            available=True,
            status_unconfirmed=(_ref(doc),),
            message=STATUS_UNCONFIRMED,
        )
    inst, rels = _visible_facts(ctx, {canonical_id})
    st = status_as_of(canonical_id, ctx.as_of, inst, rels)
    current = applicable_version(canonical_id, ctx.as_of, inst, rels)
    return ToolResult(
        tool="check_document_status",
        available=True,
        documents=(_ref(doc),),
        status=st.status.value,
        current_version=current if st.status is not Status.IN_FORCE else canonical_id,
        ladder_level="L0+L3",
    )


def compare_documents(ctx: ToolContext, first: str, second: str) -> ToolResult:
    a, b = _visible(ctx, first), _visible(ctx, second)
    if a is None or b is None or first not in ctx.instruments or second not in ctx.instruments:
        return ToolResult(tool="compare_documents", available=False)  # a yes/no could leak
    p = resolve_precedence(
        ctx.instruments[first], ctx.instruments[second], ctx.hierarchy, ctx.relations
    )
    return ToolResult(
        tool="compare_documents",
        available=True,
        documents=(_ref(a), _ref(b)),
        precedence=p,
        ladder_level="L0",
    )


class ToolName(StrEnum):
    SEARCH_AUTHORIZED_DOCUMENTS = "search_authorized_documents"
    GET_DOCUMENT = "get_document"
    FIND_PRECEDENTS = "find_precedents"
    GET_CURRENT_RULES = "get_current_rules"
    CHECK_DOCUMENT_STATUS = "check_document_status"
    COMPARE_DOCUMENTS = "compare_documents"


def call_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> ToolResult:
    """The only entry point the orchestrator uses. Validates the name and the argument shape."""
    try:
        tool = ToolName(name)
    except ValueError as exc:
        raise ToolError(f"unknown tool {name!r}") from exc
    dispatch: dict[ToolName, Callable[[], ToolResult]] = {
        ToolName.SEARCH_AUTHORIZED_DOCUMENTS: lambda: search_authorized_documents(
            ctx, IntentSlots.model_validate(args)
        ),
        ToolName.FIND_PRECEDENTS: lambda: find_precedents(ctx, IntentSlots.model_validate(args)),
        ToolName.GET_CURRENT_RULES: lambda: get_current_rules(
            ctx, IntentSlots.model_validate(args)
        ),
        ToolName.GET_DOCUMENT: lambda: get_document(ctx, _one_id(args)),
        ToolName.CHECK_DOCUMENT_STATUS: lambda: check_document_status(ctx, _one_id(args)),
        ToolName.COMPARE_DOCUMENTS: lambda: compare_documents(ctx, *_two_ids(args)),
    }
    try:
        return dispatch[tool]()
    except ValueError as exc:  # pydantic ValidationError is a ValueError
        raise ToolError(f"invalid arguments for {name}: {exc}") from exc


def _one_id(args: dict[str, Any]) -> str:
    slots = IntentSlots.model_validate(args)
    if len(slots.canonical_ids) != 1 or set(args) != {"canonical_ids"}:
        raise ToolError("exactly one canonical ID expected")
    return slots.canonical_ids[0]


def _two_ids(args: dict[str, Any]) -> tuple[str, str]:
    slots = IntentSlots.model_validate(args)
    if len(slots.canonical_ids) != 2 or set(args) != {"canonical_ids"}:
        raise ToolError("exactly two canonical IDs expected")
    return slots.canonical_ids[0], slots.canonical_ids[1]
