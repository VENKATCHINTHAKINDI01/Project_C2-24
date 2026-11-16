"""Deterministic RBAC+ABAC: `compute_scope` and `can_access`, fail closed (plan §5.1, §5.2, §5.9).

The two functions encode the same policy along two independent code paths, so a test can prove
they agree for every officer × document. The LLM is never consulted here.

Department-wide reach needs BOTH a senior rank and a department/global e-Office search scope
(owner decision, 3 Nov 2026, ADR-0009). Request-time entry points (`scope_for`, `check`) read the
officer's grants from the access store on every call, so a revocation applies immediately.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

import yaml

from app.auth.models import (
    AccessDecision,
    AccessPolicy,
    DecisionReason,
    DocumentAccessTags,
    Principal,
    Scope,
)
from app.auth.store import AuthzStore, StoreError
from app.config import Classification

log = logging.getLogger(__name__)


class ScopeError(Exception):
    """Scope could not be computed. Callers must deny, never fall back to unscoped retrieval."""


def load_access_policy(path: Path) -> AccessPolicy:
    with path.open(encoding="utf-8") as fh:
        return AccessPolicy.model_validate(yaml.safe_load(fh))


def _ranks(classification: Classification) -> dict[str, int]:
    return {lv.name: lv.rank for lv in classification.levels}


def _department_wide(p: Principal, policy: AccessPolicy) -> bool:
    return p.role_rank >= policy.department_wide_min_role_rank and bool(
        p.search_scopes & policy.department_wide_scopes
    )


def _section_reach(p: Principal, policy: AccessPolicy) -> bool:
    return p.section is not None and bool(p.search_scopes & policy.section_scopes)


def _file_reach(p: Principal, policy: AccessPolicy) -> frozenset[str]:
    return p.assigned_files | (
        p.handled_files if policy.handled_files_grant_access else frozenset()
    )


def compute_scope(
    principal: Principal, policy: AccessPolicy, classification: Classification
) -> Scope:
    """Build the pre-retrieval filter for `principal` (plan §5.2); ScopeError on bad input."""
    ranks = _ranks(classification)
    if principal.clearance not in ranks:
        raise ScopeError("unknown clearance")
    if policy.public_classification not in ranks:
        raise ScopeError("policy public classification not in classification order")
    section = principal.section
    return Scope(
        user_id=principal.user_id,
        policy_version=policy.version,
        classification_ranks=ranks,
        public_rank=ranks[policy.public_classification],
        department=principal.department,
        max_rank=ranks[principal.clearance],
        department_wide=_department_wide(principal, policy),
        sections=frozenset({section})
        if section and _section_reach(principal, policy)
        else frozenset(),
        file_nos=_file_reach(principal, policy),
    )


def can_access(
    principal: Principal,
    doc: DocumentAccessTags,
    policy: AccessPolicy,
    classification: Classification,
) -> AccessDecision:
    """Re-check one candidate before it enters the evidence package (plan §5.2).

    Any unexpected error → DENY with reason ERROR (plan §5.9).
    """
    try:
        return _decide(principal, doc, policy, classification)
    except Exception:  # fail closed on anything unexpected; log IDs only, never content
        log.exception("can_access failed user=%s doc=%s", principal.user_id, doc.doc_id)
        return AccessDecision(allowed=False, reason=DecisionReason.ERROR, policy_version="")


def _decide(
    principal: Principal,
    doc: DocumentAccessTags,
    policy: AccessPolicy,
    classification: Classification,
) -> AccessDecision:
    ranks = _ranks(classification)

    def deny(reason: DecisionReason) -> AccessDecision:
        return AccessDecision(allowed=False, reason=reason, policy_version=policy.version)

    def allow(reason: DecisionReason) -> AccessDecision:
        return AccessDecision(allowed=True, reason=reason, policy_version=policy.version)

    doc_rank = ranks.get(doc.classification)
    user_rank = ranks.get(principal.clearance)
    if doc_rank is None or user_rank is None:
        return deny(DecisionReason.UNKNOWN_CLASSIFICATION)
    # "Public" means a published instrument (a G.O., a gazette). A paper inside an e-File — note
    # sheet, draft, correspondence — is never public, whatever its marking: it follows the
    # file's reach below (CLAUDE.md §2.4: never more than the officer's e-Office scope allows).
    if doc.classification == policy.public_classification and doc.file_no is None:
        return allow(DecisionReason.PUBLIC)
    if doc.department != principal.department:
        return deny(DecisionReason.OTHER_DEPARTMENT)
    if user_rank < doc_rank:
        return deny(DecisionReason.CLEARANCE_TOO_LOW)
    if _department_wide(principal, policy):
        return allow(DecisionReason.SENIOR_IN_DEPARTMENT)
    if _section_reach(principal, policy) and doc.section == principal.section:
        return allow(DecisionReason.SAME_SECTION)
    if doc.file_no is not None and doc.file_no in principal.assigned_files:
        return allow(DecisionReason.ASSIGNED_FILE)
    if (
        policy.handled_files_grant_access
        and doc.file_no is not None
        and doc.file_no in principal.handled_files
    ):
        return allow(DecisionReason.HANDLED_FILE)
    return deny(DecisionReason.NO_SECTION_OR_ASSIGNMENT)


# ---- request-time entry points: grants read from the access store on every call -------------


def scope_for(
    user_id: str, store: AuthzStore, policy: AccessPolicy, classification: Classification
) -> Scope:
    """Scope from the officer's CURRENT grants (plan §5.2). Raises ScopeError → caller denies."""
    try:
        principal = store.principal(user_id)
    except StoreError as exc:
        log.warning("scope denied user=%s reason=store", user_id)
        raise ScopeError("no valid grants") from exc
    return compute_scope(principal, policy, classification)


def check(
    user_id: str,
    doc: DocumentAccessTags,
    store: AuthzStore,
    policy: AccessPolicy,
    classification: Classification,
) -> AccessDecision:
    """Re-check against the officer's CURRENT grants; unknown/incomplete user → DENY."""
    try:
        principal = store.principal(user_id)
    except StoreError:
        return AccessDecision(
            allowed=False, reason=DecisionReason.UNKNOWN_USER, policy_version=policy.version
        )
    return can_access(principal, doc, policy, classification)


def authorized_subset(
    principal: Principal,
    candidates: Iterable[DocumentAccessTags],
    policy: AccessPolicy,
    classification: Classification,
) -> list[DocumentAccessTags]:
    """Scope filter then per-document re-check: the two enforcement layers in order (plan §5.2).

    A ScopeError denies everything. Counts and summaries must be computed only over the result.
    """
    try:
        scope = compute_scope(principal, policy, classification)
    except ScopeError:
        log.warning("scope denied user=%s", principal.user_id)
        return []
    return [
        d
        for d in candidates
        if scope.admits(d) and can_access(principal, d, policy, classification).allowed
    ]
