"""Retrieval rung L3: scope-constrained graph expansion from L0–L2 hits (plan §3.2, §5.2).

Always the last rung. Seeds are re-checked, the walk is constrained by the officer's CURRENT scope
(read from the access store), and every hit is re-checked again before it can reach an evidence
package. Hop depth comes from `backend/config/runtime.yaml` (`retrieval.l3_max_hops`) and is never
guessed: while it is uncalibrated (`null`) callers must pass it explicitly.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict

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
    hits: tuple[GraphHit, ...]
    # plan §14.4: the graph store failed — no relations were walked, so nothing here may be read
    # as "no later order exists"; callers say "supersession status unverified"
    unavailable: bool = False


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
) -> GraphExpansion:
    """L3 with both enforcement layers (plan §5.2). Scope failure → no expansion (fail closed)."""
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
        )
        hits = tuple(h for h in raw if allowed(h.canonical_id) and all(allowed(p) for p in h.path))
    except ScopeError:
        return GraphExpansion(scope_signature=None, seeds=(), hits=())  # fail closed
    except Exception as exc:  # noqa: BLE001 — plan §14.4: no walk, said so; never a partial one
        log.error("L3 graph store unavailable user=%s: %s", user_id, type(exc).__name__)
        return GraphExpansion(scope_signature=scope.signature, seeds=(), hits=(), unavailable=True)
    if len(hits) != len(raw):  # scope and re-check disagree: a bug, never silently served
        log.error("L3 re-check removed %d in-scope hits user=%s", len(raw) - len(hits), user_id)
    return GraphExpansion(scope_signature=scope.signature, seeds=ok_seeds, hits=hits)
