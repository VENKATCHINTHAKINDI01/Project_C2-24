"""Retrieval rung L3: scope-constrained graph expansion from L0–L2 hits (plan §3.2, §5.2).

Always the last rung. Seeds are re-checked, the walk is constrained by the officer's CURRENT scope
(read from the access store), and every hit is re-checked again before it can reach an evidence
package. Hop depth comes from `backend/config/runtime.yaml` (`retrieval.l3_max_hops`) and is never
guessed: while it is uncalibrated (`null`) callers must pass it explicitly.

Graph-Guided Hybrid Evidence Retrieval (Fault 3 Guardrails):
1. Graph Relationship Resolver: discovers connected documents within max_nodes/max_edges.
2. Intent-Based Relationship Selector: prioritizes legally critical edges (AMENDS, SUPERSEDES).
3. Scoped Hybrid Retriever: runs hybrid search restricted to discovered candidate IDs.
4. Evidence Consolidator: preserves structural relationships so semantic ranking never overrides
   a legally binding supersession/amendment, and issues non-silent truncation notices.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.auth.models import AccessPolicy
from app.auth.policy import ScopeError, check, scope_for
from app.auth.store import AuthzStore
from app.config import Classification, RuntimeConfig
from app.graph.repository import (
    Direction,
    EdgeKind,
    GraphHit,
    WalkableGraph,
)

log = logging.getLogger(__name__)

SUPERSESSION = frozenset(
    {EdgeKind.SUPERSEDES, EdgeKind.REPEALS, EdgeKind.AMENDS, EdgeKind.CLARIFIES}
)
CITATION = frozenset({EdgeKind.CITES, EdgeKind.REFERENCES})
HIGH_LEGAL_FORCE = frozenset(
    {
        EdgeKind.SUPERSEDES,
        EdgeKind.AMENDS,
        EdgeKind.REPEALS,
        EdgeKind.CLARIFIES,
        EdgeKind.CONFLICTS_WITH,
    }
)


class NotCalibratedError(Exception):
    """A threshold is still `null` in runtime config; do not substitute a default."""


def configured_max_hops(runtime: RuntimeConfig) -> int:
    hops = runtime.retrieval.l3_max_hops
    if hops is None:
        raise NotCalibratedError("retrieval.l3_max_hops is not calibrated")
    return hops


class GraphExpansion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    scope_signature: str | None
    seeds: tuple[str, ...]  # authorised seeds actually used
    hits: tuple[GraphHit, ...] = Field(default_factory=tuple)
    # plan §14.4: the graph store failed — no relations were walked, so nothing here may be read
    # as "no later order exists"; callers say "supersession status unverified"
    unavailable: bool = False
    truncated: bool = False
    total_found: int = 0
    truncation_reason: str | None = None


# ---- Graph-Guided Hybrid Evidence Retrieval Components -----------------------------------------


class StructuralRelationshipAnchor(BaseModel):
    """Legally binding structural relation preserved regardless of semantic search score."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical_id: str
    target_id: str
    kind: EdgeKind
    hops: int = Field(ge=1)
    legal_force: Literal["HIGH", "MEDIUM", "INFORMATIONAL"]
    path: tuple[str, ...]


class ScopedChunkMatch(BaseModel):
    """A relevant chunk or document hit found inside candidate documents by hybrid search."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical_id: str
    score: float
    matched_clause: str | None = None


class ConsolidatedEvidence(BaseModel):
    """Unified evidence package combining structural graph anchors and scoped semantic matches."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    graph_hits: tuple[GraphHit, ...]
    anchors: tuple[StructuralRelationshipAnchor, ...]
    scoped_matches: tuple[ScopedChunkMatch, ...] = Field(default_factory=tuple)
    truncated: bool = False
    truncation_reason: str | None = None
    disclaimer: str | None = None


def select_relationships_by_intent(
    kinds: frozenset[EdgeKind],
    *,
    is_conflict_or_amendment: bool = False,
) -> frozenset[EdgeKind]:
    """Intent-Based Relationship Selector: prioritizes statutory modification."""
    if is_conflict_or_amendment:
        statutory = kinds & HIGH_LEGAL_FORCE
        return statutory if statutory else kinds
    return kinds


def format_truncation_disclaimer(
    truncated: bool,
    truncation_reason: str | None,
    item_count: int,
) -> str | None:
    """Non-silent truncation notice informing officers that traversal bounds were reached."""
    if not truncated:
        return None
    reason_desc = truncation_reason or "operational limit"
    return (
        f"The relations lookup reached its limit ({reason_desc}); {item_count} related "
        "record(s) are listed. Later orders that replace or amend these records may not all be "
        "listed."
    )


def consolidate_evidence(
    hits: tuple[GraphHit, ...],
    scoped_matches: Sequence[ScopedChunkMatch] = (),
    *,
    truncated: bool = False,
    truncation_reason: str | None = None,
) -> ConsolidatedEvidence:
    """Evidence Consolidator: guarantees legally significant relations are never lost."""
    anchors: list[StructuralRelationshipAnchor] = []
    for h in hits:
        force: Literal["HIGH", "MEDIUM", "INFORMATIONAL"] = (
            "HIGH"
            if h.via in HIGH_LEGAL_FORCE
            else ("MEDIUM" if h.via in CITATION else "INFORMATIONAL")
        )
        target = h.path[-2] if len(h.path) >= 2 else (h.path[0] if h.path else h.canonical_id)
        anchors.append(
            StructuralRelationshipAnchor(
                canonical_id=h.canonical_id,
                target_id=target,
                kind=h.via,
                hops=h.hops,
                legal_force=force,
                path=h.path,
            )
        )
    disclaimer = format_truncation_disclaimer(truncated, truncation_reason, len(hits))
    return ConsolidatedEvidence(
        graph_hits=hits,
        anchors=tuple(anchors),
        scoped_matches=tuple(scoped_matches),
        truncated=truncated,
        truncation_reason=truncation_reason,
        disclaimer=disclaimer,
    )


# ---- Main Graph Expansion Entrypoint -----------------------------------------------------------


def expand(
    user_id: str,
    seeds: Iterable[str],
    *,
    graph: WalkableGraph,
    kinds: frozenset[EdgeKind],
    direction: Direction,
    max_hops: int,
    store: AuthzStore,
    policy: AccessPolicy,
    classification: Classification,
    include_unconfirmed: bool = False,
    max_nodes: int | None = None,
    max_edges: int | None = None,
) -> GraphExpansion:
    """L3 with both enforcement layers and operational bounds (plan §5.2, Fault 3 Guardrail)."""
    try:
        scope = scope_for(user_id, store, policy, classification)
    except ScopeError:
        return GraphExpansion(scope_signature=None, seeds=(), hits=())

    def allowed(cid: str) -> bool:
        node = graph.node(cid)
        return node is not None and check(user_id, node.tags, store, policy, classification).allowed

    if max_hops < 1:  # a caller's mistake, not an outage: raised, never reported as "unavailable"
        raise ValueError("max_hops must be >= 1")
    try:
        ok_seeds = tuple(s for s in dict.fromkeys(seeds) if allowed(s))
        raw = graph.walk(
            ok_seeds,
            scope,
            kinds=kinds,
            direction=direction,
            max_hops=max_hops,
            include_unconfirmed=include_unconfirmed,
            max_nodes=max_nodes,
            max_edges=max_edges,
        )
        truncated = getattr(raw, "truncated", False)
        total_found = getattr(raw, "total_found", len(raw))
        truncation_reason = getattr(raw, "truncation_reason", None)
        hits = tuple(h for h in raw if allowed(h.canonical_id) and all(allowed(p) for p in h.path))
    except ScopeError:
        return GraphExpansion(scope_signature=None, seeds=(), hits=())  # fail closed
    except Exception as exc:  # noqa: BLE001 — plan §14.4: no walk, said so; never a partial one
        log.error("L3 graph store unavailable user=%s: %s", user_id, type(exc).__name__)
        return GraphExpansion(scope_signature=scope.signature, seeds=(), hits=(), unavailable=True)
    if len(hits) != len(raw):  # scope and re-check disagree: a bug, never silently served
        log.error("L3 re-check removed %d in-scope hits user=%s", len(raw) - len(hits), user_id)
    return GraphExpansion(
        scope_signature=scope.signature,
        seeds=ok_seeds,
        hits=hits,
        truncated=truncated,
        total_found=total_found,
        truncation_reason=truncation_reason,
    )
