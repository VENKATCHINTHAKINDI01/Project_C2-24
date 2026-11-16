"""The conversational assistant as a LangGraph graph over the one typed `AgentState`
(plan §3.4, §8.1, §10.1, §10.6; ADR-0029).

One turn = one run of the graph. Every node reads and writes `AgentState`; nothing is kept between
turns except the session memory (IDs only) and the scoped answer cache.

    scope → recall → understand → cache ─hit─→ remember
                                   └─miss→ answer → remember

- scope:      compute_scope for THIS turn (permissions are never carried over); fail closed.
- recall:     a follow-up ("that order", "the same file") uses what earlier turns found — only the
              entities the officer may still see now (session memory re-checks them).
- understand: named orders / e-Files, the intent (fixed rules, no model), the canonical query.
- cache:      scoped answer cache: key = canonical query + scope signature + as-of date.
- answer:     the cited-answer path (ADR-0024): evidence package → model → citation check.
- remember:   session memory (IDs), query log (IDs and metadata), cache (confirmed answers only).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from langgraph.graph import END, StateGraph

from app.agents.answer import AskStatus, AskTrace, ask, named_orders
from app.agents.intents import Intent
from app.agents.state import AgentState
from app.agents.streaming import Emit
from app.agents.tools import ToolContext
from app.auth.models import AccessPolicy, DocumentAccessTags
from app.auth.policy import ScopeError, scope_for
from app.auth.store import AuthzStore
from app.cache.answers import AnswerCache
from app.config import Classification
from app.connectors.eoffice import OfficerContext
from app.identifiers.resolver import DepartmentTable, reference_candidates
from app.memory.session import Turn
from app.tracking.query_log import QueryLog, QueryRecord, query_hash
from app.tracking.signals import SignalConfig, question_flags

DENIED = "The assistant is not available to you right now."
_FOLLOW_UP = re.compile(
    r"\b(that|this|these|those|same|above|previous|earlier|it|its|them|the order|the file)\b",
    re.I,
)
_FILE_NO = re.compile(r"\b[A-Z]{2,6}\d{2}-[A-Z0-9]+/\d+/\d{4}-[A-Z0-9.]+")


class Memory(Protocol):
    def append(self, user_id: str, session_id: str, turn: Turn) -> None: ...

    def turns(self, user_id: str, session_id: str) -> tuple[Turn, ...]: ...

    def recall(
        self,
        user_id: str,
        session_id: str,
        *,
        locations: Mapping[str, DocumentAccessTags],
        store: AuthzStore,
        policy: AccessPolicy,
        classification: Classification,
    ) -> tuple[str, ...]: ...


class _Locations(Mapping[str, DocumentAccessTags]):
    """Tags looked up one ID at a time (never a listing)."""

    def __init__(self, tags_of: Callable[[str], DocumentAccessTags | None]) -> None:
        self._of = tags_of

    def __getitem__(self, cid: str) -> DocumentAccessTags:
        t = self._of(cid)
        if t is None:
            raise KeyError(cid)
        return t

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(())

    def __len__(self) -> int:
        return 0


@dataclass
class TurnServices:
    """Per-turn wiring: the officer's tool context and the shared stores."""

    officer: OfficerContext
    ctx: ToolContext
    memory: Memory
    cache: AnswerCache
    query_log: QueryLog
    texts: Mapping[str, str]
    llm: Any
    departments: DepartmentTable
    file_papers: Callable[[str], Sequence[str]]
    tags_of: Callable[[str], DocumentAccessTags | None]
    emit: Emit | None = None  # streaming (ADR-0033): progress and checked statements
    log_question: bool = False  # keep the question text in the query log (ADR-0035)
    signals: SignalConfig | None = None  # unusual-activity signal codes (ADR-0036)


def classify(question: str, named: Sequence[str], file_nos: Sequence[str]) -> Intent:
    """Intent by fixed rules (plan §5.6: the model never chooses a retrieval template)."""
    q = question.lower()
    if file_nos:
        return Intent.CONFLICT_CHECK
    if named and re.search(r"\b(valid|in force|still|superseded|repealed|status)\b", q):
        return Intent.DOCUMENT_STATUS
    if named and re.search(r"\b(replaced|supersed\w*|amend\w*)\b", q):
        return Intent.SUPERSESSION_CHAIN
    if named and re.search(r"\b(para|clause|say|says|provide|provides)\b", q):
        return Intent.CLAUSE_LOOKUP
    if re.search(r"\b(how many|decided|decisions|rejected|approved)\b", q):
        return Intent.DECISION_HISTORY
    if re.search(r"\b(current|guidelines|rules|who can|limit|ceiling)\b", q):
        return Intent.CURRENT_RULE
    return Intent.PRECEDENT_LOOKUP


def canonical_query(question: str, entities: Sequence[str]) -> str:
    base = " ".join(question.lower().split())
    return f"{base} | {' '.join(sorted(entities))}" if entities else base


def build_graph(svc: TurnServices) -> Any:
    ctx = svc.ctx
    started = time.monotonic()
    scope_holder: dict[str, Any] = {}
    mention: dict[str, bool] = {}  # signals only (ADR-0036)

    def scope_node(state: AgentState) -> dict[str, Any]:
        s = state
        try:
            scope = scope_for(s.user, ctx.store, ctx.policy, ctx.classification)
        except ScopeError:
            return {"outcome": "denied", "result": {"status": "denied", "message": DENIED}}
        scope_holder["scope"] = scope
        return {"scope_signature": scope.signature}

    def recall_node(state: AgentState) -> dict[str, Any]:
        s = state
        if not _FOLLOW_UP.search(s.raw_query):
            return {}
        got = svc.memory.recall(
            s.user,
            s.session_id,
            locations=_Locations(svc.tags_of),
            store=ctx.store,
            policy=ctx.policy,
            classification=ctx.classification,
        )
        return {"recalled": got[:3]}

    def understand_node(state: AgentState) -> dict[str, Any]:
        s = state
        named = named_orders(ctx, s.raw_query, svc.departments)
        files = list(dict.fromkeys(_FILE_NO.findall(s.raw_query)))
        entities = tuple(dict.fromkeys([*named, *files, *s.recalled]))
        # for the signals only (ADR-0036): did the question cite an order at all, and did any
        # reading of it resolve to one this officer may open? Never changes the answer.
        refs = bool(svc.departments and reference_candidates(s.raw_query, svc.departments))
        mention["references"], mention["named"] = refs, bool(named)
        return {
            "entities": entities,
            "intent": classify(s.raw_query, named, files),
            "canonical_query": canonical_query(s.raw_query, entities),
        }

    def key(s: AgentState) -> str:
        return f"{s.canonical_query}\x1f{s.as_of_date.isoformat()}"

    def cache_node(state: AgentState) -> dict[str, Any]:
        s = state
        hit = svc.cache.get(key(s), scope_holder.get("scope"))
        if hit is None:
            return {}
        result = json.loads(hit)
        return {"cache_hit": True, "result": result, "outcome": result.get("status")}

    def answer_node(state: AgentState) -> dict[str, Any]:
        s = state
        trace = AskTrace()
        if svc.emit is not None:
            svc.emit({"type": "stage", "stage": "searching"})
        ans = ask(
            ctx,
            s.raw_query,
            texts=svc.texts,
            llm=svc.llm,
            request_id=s.request_id,
            departments=svc.departments,
            file_papers=svc.file_papers,
            recalled=s.recalled,
            trace=trace,
            on_event=svc.emit,
        )
        pkg, v = trace.package, trace.verification
        known = {i.evidence_id for i in pkg.items} if pkg else set()
        cited = tuple(
            dict.fromkeys(
                c.evidence_id
                for st in ans.statements
                for c in st.citations
                if c.evidence_id in known
            )
        )
        out: dict[str, Any] = {
            "outcome": ans.status.value,
            "result": ans.model_dump(mode="json"),
            "ladder_level": ans.ladder_level,
            "authorized_candidates": tuple(sorted(pkg.canonical_ids)) if pkg else (),
            "temporal_status": {i.canonical_id: i.status for i in pkg.items} if pkg else {},
        }
        if pkg is not None and pkg.items:
            out |= {"evidence_package": pkg, "citations": cited}
            if v is not None:
                out |= {"verification": v, "answer_status": v.answer_status}
        return out

    def remember_node(state: AgentState) -> dict[str, Any]:
        s = state
        result = s.result or {}
        cited_cids = tuple(
            dict.fromkeys(
                c["canonical_id"]
                for st in result.get("statements", [])
                for c in st.get("citations", [])
            )
        )
        if s.outcome != "denied":
            svc.memory.append(
                s.user,
                s.session_id,
                Turn(
                    request_id=s.request_id,
                    at=dt.datetime.now(dt.UTC),
                    canonical_query=(s.canonical_query or s.raw_query)[:1000],
                    entity_ids=tuple(dict.fromkeys([*s.entities, *cited_cids]))[:20],
                    scope_signature=s.scope_signature,
                ),
            )
        cacheable = (
            not s.cache_hit
            and s.outcome == AskStatus.ANSWERED.value
            and not result.get("review_needed")
        )
        if cacheable:
            svc.cache.put(
                key(s), scope_holder.get("scope"), json.dumps(result), frozenset(cited_cids)
            )
        o = svc.officer
        svc.query_log.write(
            QueryRecord(
                query_id=s.request_id,
                ts=dt.datetime.now(dt.UTC),
                session_id=s.session_id,
                turn=s.turn,
                user_id=s.user,
                department=o.department,
                section=o.section,
                role=o.post,
                query_hash=query_hash(s.raw_query),
                intent=s.intent.value if s.intent else None,
                entities=s.entities,
                ladder_level=s.ladder_level,
                retrieved_ids=s.authorized_candidates,
                evidence_ids=tuple(i.evidence_id for i in s.evidence_package.items)
                if s.evidence_package
                else (),
                cited_ids=cited_cids,
                scope_signature=s.scope_signature,
                latency_ms=int((time.monotonic() - started) * 1000),
                cache_hit=s.cache_hit,
                answer_status=s.outcome or "no_answer",
                question=" ".join(s.raw_query.split())[:500] if svc.log_question else None,
                clearance_rank=ctx.classification.rank_of(o.clearance)
                if svc.log_question
                else None,
                flags=question_flags(
                    svc.signals,
                    s.raw_query,
                    references=mention.get("references", False),
                    named=mention.get("named", False),
                    entities=bool(s.entities),
                    outcome=s.outcome,
                    found=bool(s.authorized_candidates),
                )
                if svc.signals is not None and s.outcome != "denied"
                else (),
            )
        )
        return {}

    g = StateGraph(AgentState)
    g.add_node("scope", scope_node)
    g.add_node("recall", recall_node)
    g.add_node("understand", understand_node)
    g.add_node("cache", cache_node)
    g.add_node("answer", answer_node)
    g.add_node("remember", remember_node)
    g.set_entry_point("scope")
    g.add_conditional_edges("scope", lambda s: END if s.outcome == "denied" else "recall")
    g.add_edge("recall", "understand")
    g.add_edge("understand", "cache")
    g.add_conditional_edges("cache", lambda s: "remember" if s.cache_hit else "answer")
    g.add_edge("answer", "remember")
    g.add_edge("remember", END)
    return g.compile()


def run_turn(svc: TurnServices, *, session_id: str, message: str, request_id: str) -> AgentState:
    """One conversational turn. Returns the final `AgentState` (its `result` is the response)."""
    turn = len(svc.memory.turns(svc.officer.user_id, session_id)) + 1
    state = AgentState(
        request_id=request_id,
        session_id=session_id,
        user=svc.officer.user_id,
        raw_query=message,
        as_of_date=svc.ctx.as_of,
        turn=turn,
    )
    final = build_graph(svc).invoke(state)
    return final if isinstance(final, AgentState) else AgentState.model_validate(final)
