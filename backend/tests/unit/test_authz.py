"""Authorization: access store + compute_scope + can_access vs the mock access matrix (plan §5.2).

Grants come from the access store (tuples), never from document metadata. Expected decisions come
from `access_matrix.csv`; app code only sees grants and document location tags.
"""

from __future__ import annotations

from itertools import product

import pytest

from app.auth.models import DecisionReason, SearchScope
from app.auth.policy import (
    ScopeError,
    authorized_subset,
    can_access,
    check,
    compute_scope,
    scope_for,
)
from app.auth.store import AccessTuple, AuthzStore, InMemoryAuthzStore, Relation, StoreError
from tests.unit.mock_access import CLASSES, MATRIX, POLICY, USER_IDS, doc_tags, new_store

STORE = new_store()
DOCS = doc_tags()
PRINCIPALS = {uid: STORE.principal(uid) for uid in USER_IDS}


def _t(user: str, rel: Relation, obj: str) -> AccessTuple:
    return AccessTuple(subject=f"user:{user}", relation=rel, object=obj)


def test_policy_is_marked_mock_and_store_satisfies_protocol() -> None:
    assert POLICY.status == "mock"
    assert isinstance(STORE, AuthzStore)


@pytest.mark.parametrize(("doc_id", "user_id"), sorted(MATRIX))
def test_store_backed_check_reproduces_access_matrix(doc_id: str, user_id: str) -> None:
    decision = check(user_id, DOCS[doc_id], STORE, POLICY, CLASSES)
    assert decision.allowed is MATRIX[(doc_id, user_id)]
    assert decision.policy_version == POLICY.version


def test_matrix_is_fully_covered() -> None:
    assert len(MATRIX) == len(DOCS) * len(PRINCIPALS) == 29 * 8


def test_scope_and_recheck_agree_everywhere() -> None:
    """Both enforcement layers encode the same policy (plan §5.2)."""
    for uid, did in product(PRINCIPALS, DOCS):
        scope = compute_scope(PRINCIPALS[uid], POLICY, CLASSES)
        assert (
            scope.admits(DOCS[did])
            is can_access(PRINCIPALS[uid], DOCS[did], POLICY, CLASSES).allowed
        )


def test_authorized_subset_matches_matrix_per_officer() -> None:
    for uid, p in PRINCIPALS.items():
        got = {d.doc_id for d in authorized_subset(p, DOCS.values(), POLICY, CLASSES)}
        want = {did for (did, u), ok in MATRIX.items() if u == uid and ok}
        assert got == want, uid


# ---- rank AND search scope (owner decision, 3 Nov 2026) --------------------------------------


def test_senior_rank_without_department_scope_is_not_department_wide() -> None:
    """Deputy Secretary whose e-Office search privilege is only Individual loses dept-wide reach."""
    p = PRINCIPALS["U05"].model_copy(update={"search_scopes": frozenset({SearchScope.INDIVIDUAL})})
    d = can_access(p, DOCS["D21"], POLICY, CLASSES)
    assert not d.allowed and d.reason is DecisionReason.NO_SECTION_OR_ASSIGNMENT
    assert not compute_scope(p, POLICY, CLASSES).department_wide


def test_department_scope_without_senior_rank_is_not_department_wide() -> None:
    """A Section Officer given Department search scope still sees only their section."""
    p = PRINCIPALS["U01"].model_copy(update={"search_scopes": frozenset({SearchScope.DEPARTMENT})})
    assert not can_access(p, DOCS["D24"], POLICY, CLASSES).allowed  # Works note
    assert can_access(p, DOCS["D17"], POLICY, CLASSES).allowed  # own Estt.I note


def test_individual_scope_reaches_only_assigned_or_handled_files() -> None:
    p = PRINCIPALS["U01"].model_copy(update={"search_scopes": frozenset({SearchScope.INDIVIDUAL})})
    assert not can_access(p, DOCS["D17"], POLICY, CLASSES).allowed
    handled = p.model_copy(update={"handled_files": frozenset({DOCS["D17"].file_no or ""})})
    d = can_access(handled, DOCS["D17"], POLICY, CLASSES)
    assert d.allowed and d.reason is DecisionReason.HANDLED_FILE


def test_assignment_grants_cross_section_access() -> None:
    d = check("U04", DOCS["D20"], STORE, POLICY, CLASSES)
    assert d.allowed and d.reason is DecisionReason.ASSIGNED_FILE


def test_secret_report_needs_secret_clearance_even_for_deputy_secretary() -> None:
    d = check("U05", DOCS["D23"], STORE, POLICY, CLASSES)
    assert not d.allowed and d.reason is DecisionReason.CLEARANCE_TOO_LOW


# ---- the store is the source of truth: grants and revocations apply on the next request -------


def test_revoking_an_assignment_applies_immediately() -> None:
    store = new_store()
    grant = _t("U04", Relation.ASSIGNED, "file:USD01-12/58/2025-ESTT.I")
    before = scope_for("U04", store, POLICY, CLASSES)
    assert check("U04", DOCS["D20"], store, POLICY, CLASSES).allowed
    store.delete([grant])
    after = scope_for("U04", store, POLICY, CLASSES)
    assert not check("U04", DOCS["D20"], store, POLICY, CLASSES).allowed
    assert not after.admits(DOCS["D20"])
    assert before.signature != after.signature


def test_unknown_or_incomplete_user_is_denied() -> None:
    store = new_store()
    assert check("U99", DOCS["D01"], store, POLICY, CLASSES).reason is DecisionReason.UNKNOWN_USER
    with pytest.raises(ScopeError):
        scope_for("U99", store, POLICY, CLASSES)
    store.delete([_t("U01", Relation.HAS_CLEARANCE, "clearance:RESTRICTED")])
    with pytest.raises(ScopeError):
        scope_for("U01", store, POLICY, CLASSES)


def test_contradictory_grants_fail_closed() -> None:
    store = InMemoryAuthzStore(
        [
            _t("X", Relation.MEMBER_OF, "department:USD01"),
            _t("X", Relation.MEMBER_OF, "department:FIN01"),
            _t("X", Relation.HAS_CLEARANCE, "clearance:SECRET"),
            _t("X", Relation.HAS_RANK, "rank:5"),
        ]
    )
    with pytest.raises(StoreError):
        store.principal("X")
    bad_scope = InMemoryAuthzStore([_t("Y", Relation.HAS_SEARCH_SCOPE, "scope:everything")])
    with pytest.raises(StoreError):
        bad_scope.principal("Y")


def test_unknown_document_classification_fails_closed() -> None:
    odd = DOCS["D01"].model_copy(update={"classification": "TOP_SECRET"})
    p = PRINCIPALS["U06"]
    assert can_access(p, odd, POLICY, CLASSES).reason is DecisionReason.UNKNOWN_CLASSIFICATION
    assert not compute_scope(p, POLICY, CLASSES).admits(odd)


def test_unknown_clearance_denies_everything() -> None:
    p = PRINCIPALS["U01"].model_copy(update={"clearance": "COSMIC"})
    with pytest.raises(ScopeError):
        compute_scope(p, POLICY, CLASSES)
    assert authorized_subset(p, DOCS.values(), POLICY, CLASSES) == []
    assert not can_access(p, DOCS["D01"], POLICY, CLASSES).allowed


def test_section_all_does_not_widen_access_for_junior_rank() -> None:
    p = PRINCIPALS["U01"].model_copy(update={"section": None})
    visible = authorized_subset(p, DOCS.values(), POLICY, CLASSES)
    assert {d.classification for d in visible} == {"UNCLASSIFIED"}


def test_scope_signature_changes_with_every_permission_input() -> None:
    p = PRINCIPALS["U02"]
    s1 = compute_scope(p, POLICY, CLASSES).signature
    assert s1 == compute_scope(p, POLICY, CLASSES).signature
    for change in (
        {"clearance": "RESTRICTED"},
        {"section": "WORKS"},
        {"assigned_files": frozenset({"USD01-31/4/2025-VIG"})},
        {"handled_files": frozenset({"USD01-31/4/2025-VIG"})},
        {"role_rank": 3, "search_scopes": frozenset({SearchScope.DEPARTMENT})},
        {"search_scopes": frozenset({SearchScope.INDIVIDUAL})},
    ):
        assert compute_scope(p.model_copy(update=change), POLICY, CLASSES).signature != s1
    newer = POLICY.model_copy(update={"version": "next"})
    assert compute_scope(p, newer, CLASSES).signature != s1


def test_identical_permissions_share_a_signature() -> None:
    """Owner decision (3 Nov 2026): identical permissions share cached answers (plan §10.2)."""
    a = PRINCIPALS["U01"]
    b = a.model_copy(update={"user_id": "U99"})
    assert (
        compute_scope(a, POLICY, CLASSES).signature == compute_scope(b, POLICY, CLASSES).signature
    )
