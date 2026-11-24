"""Retrieval ladder orchestration: L0 → L1 → L2 with early exit, then L3 (plan §3.2).

The orchestrator fills a `LadderRequest` from fixed template slots (canonical IDs, structured
criteria, text query, whether relations are needed); the LLM never writes queries. Every rung runs
inside the officer's scope (read from the access store) and re-checks its hits. The trace records
which rung fired, what it found and why it stopped, for the ladder-level accuracy suite (§13.2).

L2 here is a deterministic keyword stand-in (`InMemoryKeywordIndex`), clearly NOT semantic search:
Vertex AI Search implements the same `HybridRetriever` Protocol later.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from collections.abc import Iterable
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.auth.models import AccessPolicy, Scope
from app.auth.policy import ScopeError, check, scope_for
from app.auth.store import AuthzStore
from app.config import Classification, RuntimeConfig
from app.graph.repository import Direction, EdgeKind, WalkableGraph
from app.retrieval.confidence_policy import (
    L2ConfidencePolicy,
)
from app.retrieval.graph_expansion import NotCalibratedError, expand
from app.retrieval.safeguards import (
    verify_cross_candidate_graph,
    verify_entity_attributes,
)
from app.retrieval.scoped import IndexedDocument, L1Criteria, Rung, ScopedRetriever, retrieve

log = logging.getLogger(__name__)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class LadderRung(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


# ---- L2 ---------------------------------------------------------------------------------------


class ScoredDocument(_Frozen):
    doc: IndexedDocument
    score: float


class HybridRetriever(Protocol):
    def search(self, query: str, scope: Scope, top_k: int) -> list[ScoredDocument]:
        """Scope is applied BEFORE scoring; only in-scope documents are ever candidates."""
        ...


# Latin words and numbers, and Telugu words (plan §4.1 Telugu/English): a Telugu question must
# reach Telugu records (golden Q19, ADR-0050). Telugu vowel signs are in the block, so a word stays
# whole; no stemming ("పనులకు" and "పనులు" are different terms)
_WORD = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?|[\u0c00-\u0c7f]+")
_STOP = frozenset(
    "a an and are as at be by for from has have in is it of on or the to was were with what who "
    "which been any this that".split()
)


def _terms(text: str) -> list[str]:
    return [t for t in _WORD.findall(text.lower()) if t not in _STOP and len(t) > 1]


class InMemoryKeywordIndex:
    """Reference L2: BM25-style keyword scoring over subject + body text. NOT semantic."""

    def __init__(self, docs: Iterable[tuple[IndexedDocument, str]]) -> None:
        self._docs = [(d, Counter(_terms(f"{d.subject} {text}"))) for d, text in docs]
        n = len(self._docs) or 1
        df: Counter[str] = Counter()
        for _, tf in self._docs:
            df.update(tf.keys())
        self._idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self._avg = sum(sum(tf.values()) for _, tf in self._docs) / n

    def search(self, query: str, scope: Scope, top_k: int) -> list[ScoredDocument]:
        q = set(_terms(query))
        out = []
        for d, tf in self._docs:
            if not scope.admits(d.tags):
                continue  # pre-retrieval filter: restricted documents are never scored
            length = sum(tf.values()) or 1
            score = sum(
                self._idf.get(t, 0.0)
                * tf[t]
                * 2.2
                / (tf[t] + 1.2 * (0.25 + 0.75 * length / self._avg))
                for t in q
                if t in tf
            )
            if score > 0:
                out.append(ScoredDocument(doc=d, score=round(score, 6)))
        out.sort(key=lambda s: (-s.score, s.doc.canonical_id))
        return out[:top_k]


# ---- request / result -------------------------------------------------------------------------


class LadderConfig(_Frozen):
    l2_top_k: int = Field(ge=1)
    l2_min_score: float
    l3_max_hops: int = Field(ge=1)
    l3_max_nodes: int | None = Field(default=50, ge=1)
    l3_max_edges: int | None = Field(default=100, ge=1)
    confidence_policy: L2ConfidencePolicy | None = None

    @model_validator(mode="after")
    def _ensure_confidence_policy(self) -> LadderConfig:
        # A config built directly (sandbox.yaml, tests, harnesses) carries the in-memory keyword
        # stand-in's TEST threshold: labelled as such, never a calibration (ADR-0061 addendum).
        if self.confidence_policy is None:
            object.__setattr__(
                self, "confidence_policy", L2ConfidencePolicy.stand_in(self.l2_min_score)
            )
        return self

    @classmethod
    def from_runtime(cls, runtime: RuntimeConfig) -> LadderConfig:
        r = runtime.retrieval
        if r.l2_top_k is None or r.l2_rerank_min_score is None or r.l3_max_hops is None:
            raise NotCalibratedError("retrieval thresholds are not calibrated (runtime.yaml)")
        if r.l3_max_nodes is None or r.l3_max_edges is None:
            raise NotCalibratedError("retrieval.l3_max_nodes / l3_max_edges are not set")
        policy = L2ConfidencePolicy.create(
            threshold=r.l2_rerank_min_score,
            calibrated=r.l2_calibrated,
            metadata=r.l2_calibration_metadata,
            margin=r.l2_min_margin,
        )
        return cls(
            l2_top_k=r.l2_top_k,
            l2_min_score=r.l2_rerank_min_score,
            l3_max_hops=r.l3_max_hops,
            l3_max_nodes=r.l3_max_nodes,
            l3_max_edges=r.l3_max_edges,
            confidence_policy=policy,
        )


class LadderRequest(_Frozen):
    """Template slots filled by the orchestrator (plan §3.2 'Templates')."""

    user_id: str
    canonical_ids: tuple[str, ...] = ()  # from the reference resolver (L0)
    criteria: L1Criteria | None = None  # structured slots (L1)
    text_query: str | None = None  # meaning-based question (L2)
    relations: frozenset[EdgeKind] = frozenset()  # non-empty → L3 after the early-exit rungs
    direction: Direction = Direction.BOTH


class RungTrace(_Frozen):
    rung: LadderRung
    fired: bool
    hits: tuple[str, ...] = ()
    exited: bool = False
    note: str = ""
    calibration_state: str | None = None
    truncated: bool = False
    truncation_reason: str | None = None


class LadderResult(_Frozen):
    scope_signature: str | None
    documents: tuple[IndexedDocument, ...]  # authorised, deduplicated, rung order
    answered_by: LadderRung | None
    graph_hits: tuple[str, ...] = ()
    trace: tuple[RungTrace, ...]
    # rungs whose store failed this time (plan §14.4): L2 → the other rungs still answer;
    # L3 → no relations were walked, so supersession found by the walk is unverified
    unavailable: tuple[LadderRung, ...] = ()
    truncated: bool = False
    truncation_reason: str | None = None
    disclaimer: str | None = None


def run_ladder(
    req: LadderRequest,
    *,
    index: ScopedRetriever,
    l2: HybridRetriever,
    graph: WalkableGraph,
    cfg: LadderConfig,
    store: AuthzStore,
    policy: AccessPolicy,
    classification: Classification,
) -> LadderResult:
    """Plan §3.2. Fail closed: no valid scope → empty result, nothing unscoped is ever tried."""
    try:
        scope = scope_for(req.user_id, store, policy, classification)
    except ScopeError:
        return LadderResult(scope_signature=None, documents=(), answered_by=None, trace=())

    def rung(r: Rung, q: str | L1Criteria) -> list[IndexedDocument]:
        res = retrieve(
            req.user_id,
            r,
            q,
            retriever=index,
            store=store,
            policy=policy,
            classification=classification,
        )
        return list(res.documents)

    trace: list[RungTrace] = []
    found: dict[str, IndexedDocument] = {}
    answered: LadderRung | None = None

    def keep(docs: Iterable[IndexedDocument]) -> tuple[str, ...]:
        ids = []
        for d in docs:
            found.setdefault(d.canonical_id, d)
            ids.append(d.canonical_id)
        return tuple(ids)

    # L0 · exact reference
    if req.canonical_ids:
        hits: list[IndexedDocument] = []
        for cid in req.canonical_ids:
            hits += rung(Rung.L0, cid)
        ids = keep(hits)
        done = bool(hits) and len({h.canonical_id for h in hits}) >= len(req.canonical_ids)
        trace.append(
            RungTrace(
                rung=LadderRung.L0,
                fired=True,
                hits=ids,
                exited=done,
                note="all references found" if done else "reference(s) not found",
            )
        )
        answered = LadderRung.L0 if done else None
    else:
        trace.append(RungTrace(rung=LadderRung.L0, fired=False, note="no exact reference"))

    # L1 · structured filter
    if answered is None and req.criteria is not None:
        hits = rung(Rung.L1, req.criteria)
        ids = keep(hits)
        trace.append(
            RungTrace(
                rung=LadderRung.L1,
                fired=True,
                hits=ids,
                exited=bool(hits),
                note="authorised matches" if hits else "no authorised matches",
            )
        )
        answered = LadderRung.L1 if hits else None
    else:
        note = "no structured slots" if answered is None else f"skipped: answered at {answered}"
        trace.append(RungTrace(rung=LadderRung.L1, fired=False, note=note))

    down: list[LadderRung] = []

    # L2 · hybrid search (reference: keyword)
    scored: list[ScoredDocument] | None = None
    if answered is None and req.text_query:
        try:
            scored = l2.search(req.text_query, scope, cfg.l2_top_k)
        except Exception as exc:  # noqa: BLE001 — plan §14.4: L0/L1/L3 still answer
            log.error("L2 unavailable user=%s: %s", req.user_id, type(exc).__name__)
            down.append(LadderRung.L2)
            trace.append(
                RungTrace(rung=LadderRung.L2, fired=False, note="unavailable: search store failed")
            )
    if scored is not None:
        ok = [
            s
            for s in scored
            if check(req.user_id, s.doc.tags, store, policy, classification).allowed
        ]
        if len(ok) != len(scored):
            log.error(
                "L2 re-check removed %d in-scope hits user=%s", len(scored) - len(ok), req.user_id
            )
        ids = keep(s.doc for s in ok)

        # 1. Canonical document deduplication: ensure runner-up scoring compares distinct documents,
        # not multiple passages belonging to the top document.
        canonical_map: dict[str, ScoredDocument] = {}
        for s in ok:
            cid = s.doc.canonical_id
            if cid not in canonical_map or s.score > canonical_map[cid].score:
                canonical_map[cid] = s
        deduped_hits = sorted(canonical_map.values(), key=lambda s: (-s.score, s.doc.canonical_id))
        deduped_scores = [s.score for s in deduped_hits]

        assert cfg.confidence_policy is not None
        eval_res = cfg.confidence_policy.evaluate(deduped_scores)

        # Safeguards apply when policy is calibrated (ADR-0061 addendum)
        if cfg.confidence_policy.is_calibrated:
            # 2. Safeguard C: Exact entity / attribute verification gate (e.g. KI-106 B.P.Ed vs
            # M.P.Ed)
            if eval_res.can_exit and deduped_hits and req.text_query:
                attr_ok, attr_note = verify_entity_attributes(
                    req.text_query, deduped_hits[0].doc.subject
                )
                if not attr_ok:
                    eval_res = eval_res.model_copy(
                        update={
                            "can_exit": False,
                            "escalated_to_l3": True,
                            "note": f"attribute mismatch: {attr_note}; escalating to next rung",
                        }
                    )

            # 3. Safeguard B: Cross-candidate temporal relationship graph gate (AMENDS / SUPERSEDES)
            if eval_res.can_exit and len(deduped_hits) >= 2 and graph is not None:
                graph_ok, graph_note = verify_cross_candidate_graph(
                    [h.doc.canonical_id for h in deduped_hits], graph, scope
                )
                if not graph_ok:
                    eval_res = eval_res.model_copy(
                        update={
                            "can_exit": False,
                            "escalated_to_l3": True,
                            "note": f"temporal ambiguity: {graph_note}; escalating to next rung",
                        }
                    )

        trace.append(
            RungTrace(
                rung=LadderRung.L2,
                fired=True,
                hits=ids,
                exited=eval_res.can_exit,
                note=eval_res.note,
                calibration_state=eval_res.state.value,
            )
        )
        answered = LadderRung.L2 if eval_res.can_exit else None
    elif LadderRung.L2 not in down:
        note = "no text query" if answered is None else f"skipped: answered at {answered}"
        trace.append(RungTrace(rung=LadderRung.L2, fired=False, note=note))

    # L3 · graph expansion — always last, only when relations are needed
    graph_ids: tuple[str, ...] = ()
    l3_disclaimer: str | None = None
    if req.relations and found:
        try:
            exp = expand(
                req.user_id,
                list(found),
                graph=graph,
                kinds=req.relations,
                direction=req.direction,
                max_hops=cfg.l3_max_hops,
                store=store,
                policy=policy,
                classification=classification,
                max_nodes=cfg.l3_max_nodes,
                max_edges=cfg.l3_max_edges,
            )
        except Exception as exc:  # noqa: BLE001 — plan §14.4: answer, supersession unverified
            # nothing from the walk is used: the records already found were checked rung by rung
            log.error("L3 unavailable user=%s: %s", req.user_id, type(exc).__name__)
            down.append(LadderRung.L3)
            trace.append(
                RungTrace(rung=LadderRung.L3, fired=False, note="unavailable: graph store failed")
            )
        else:
            if exp.unavailable:
                down.append(LadderRung.L3)
            graph_ids = tuple(h.canonical_id for h in exp.hits)
            if exp.truncated:
                note = f"graph expansion (truncated: {exp.truncation_reason})"
                l3_disclaimer = (
                    f"The relations lookup reached its limit ({exp.truncation_reason}); "
                    f"{len(graph_ids)} related record(s) are listed. Later orders that replace or "
                    "amend these records may not all be listed."
                )
            else:
                note = "unavailable: graph store failed" if exp.unavailable else "graph expansion"
            trace.append(
                RungTrace(
                    rung=LadderRung.L3,
                    fired=not exp.unavailable,
                    hits=graph_ids,
                    note=note,
                    truncated=exp.truncated,
                    truncation_reason=exp.truncation_reason,
                )
            )
            if answered is None and graph_ids:
                answered = LadderRung.L3
    else:
        trace.append(
            RungTrace(
                rung=LadderRung.L3,
                fired=False,
                note="no relations requested" if not req.relations else "no seeds",
            )
        )

    is_truncated = any(t.truncated for t in trace)
    trunc_reason = next((t.truncation_reason for t in trace if t.truncated), None)

    return LadderResult(
        scope_signature=scope.signature,
        documents=tuple(found.values()),
        answered_by=answered,
        graph_hits=graph_ids,
        trace=tuple(trace),
        unavailable=tuple(down),
        truncated=is_truncated,
        truncation_reason=trunc_reason,
        disclaimer=l3_disclaimer,
    )


def ladder_label(result: LadderResult) -> str:
    """Golden-dataset form of the rungs that answered, e.g. "L0+L3" (plan §13.2)."""
    rungs = [result.answered_by.value] if result.answered_by else []
    if result.graph_hits and "L3" not in rungs:
        rungs.append("L3")
    return "+".join(rungs) or "—"
