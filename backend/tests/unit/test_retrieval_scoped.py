"""Permission-enforced L0/L1 retrieval + shared answer cache (plan §3.2, §5.2, §5.4, §5.7, §13.3).

Leakage checks over exact-ID, filter, count and existence paths for all 8 mock officers.
"""

from __future__ import annotations

import datetime as dt

import pytest

from app.auth.policy import scope_for
from app.auth.store import AccessTuple, InMemoryAuthzStore, Relation
from app.cache.answers import InMemoryAnswerCache, answer_cache_key
from app.retrieval.scoped import (
    IndexedDocument,
    InMemoryScopedIndex,
    L1Criteria,
    RetrievalResult,
    Rung,
    count_authorised,
    retrieve,
)
from tests.unit.mock_access import CLASSES, MATRIX, POLICY, USER_IDS, doc_tags, new_store, rows

TAGS = doc_tags()
INDEX_ROWS = {r["id"]: r for r in rows("documents_index.csv")}
DOCS = [
    IndexedDocument(
        canonical_id=r["canonical_id"],
        tags=TAGS[did],
        doc_type=r["doc_type"],
        issue_date=dt.datetime.strptime(r["date"], "%d-%m-%Y").date(),
        subject=r["subject"],
    )
    for did, r in INDEX_ROWS.items()
]
INDEX = InMemoryScopedIndex(DOCS)


def _run(
    uid: str, rung: Rung, q: str | L1Criteria, store: InMemoryAuthzStore | None = None
) -> RetrievalResult:
    return retrieve(
        uid,
        rung,
        q,
        retriever=INDEX,
        store=store or new_store(),
        policy=POLICY,
        classification=CLASSES,
    )


@pytest.mark.parametrize("uid", USER_IDS)
def test_l1_everything_query_returns_exactly_the_authorised_set(uid: str) -> None:
    res = _run(uid, Rung.L1, L1Criteria())
    got = {d.tags.doc_id for d in res.documents}
    assert got == {did for (did, u), ok in MATRIX.items() if u == uid and ok}
    assert count_authorised(res) == len(got)


@pytest.mark.parametrize(("did", "uid"), sorted(MATRIX))
def test_l0_exact_reference_never_leaks(did: str, uid: str) -> None:
    res = _run(uid, Rung.L0, INDEX_ROWS[did]["canonical_id"])
    assert (len(res.documents) == 1) is MATRIX[(did, uid)]


def test_absent_and_forbidden_look_identical() -> None:
    """Existence questions: no difference between 'not there' and 'not yours' (plan §5.4)."""
    forbidden = _run("U01", Rung.L0, "AP-USD01-RPT-USD0131-9-2025")
    absent = _run("U01", Rung.L0, "AP-USD01-RPT-USD0131-99-2025")
    garbage = _run("U01", Rung.L0, "not an id")
    assert forbidden.documents == absent.documents == garbage.documents == ()


def test_l0_finds_pre_adr0007_memo_ids_from_tagged_references() -> None:
    res = _run("U03", Rung.L0, "AP-USD01-CIRMEMO-USD01WRKS0-9-2023-D20230711")
    assert [d.canonical_id for d in res.documents] == ["AP-USD01-CIRMEMO-USD01WRKS0-9-2023"]


def test_l1_template_slots() -> None:
    crit = L1Criteria(
        department="USD01", doc_types=frozenset({"Noting"}), subject_terms=("transfer",)
    )
    officer_b = {d.tags.doc_id for d in _run("U02", Rung.L1, crit).documents}
    officer_c = {d.tags.doc_id for d in _run("U03", Rung.L1, crit).documents}
    assert officer_b and officer_b <= {"D17", "D18", "D19", "D20"}
    assert officer_c == set()  # same question, different officer → correctly different answer


def test_revocation_takes_effect_on_the_next_retrieval() -> None:
    store = new_store()
    assert _run("U04", Rung.L0, "AP-USD01-NOTE-USD0112-58-2025", store).documents
    store.delete(
        [
            AccessTuple(
                subject="user:U04",
                relation=Relation.ASSIGNED,
                object="file:USD01-12/58/2025-ESTT.I",
            )
        ]
    )
    assert _run("U04", Rung.L0, "AP-USD01-NOTE-USD0112-58-2025", store).documents == ()


def test_unknown_user_gets_nothing_not_unscoped_results() -> None:
    res = _run("U99", Rung.L1, L1Criteria())
    assert res.documents == () and res.scope_signature is None


def test_query_type_must_match_rung() -> None:
    with pytest.raises(TypeError):
        _run("U01", Rung.L0, L1Criteria())


# ---- shared answer cache (owner decision, 3 Nov 2026) ----------------------------------------


def test_identical_permissions_share_answers_but_different_ones_never_do() -> None:
    store = new_store()
    # a second Section Officer with exactly U01's grants, e.g. in another regional office
    twin = [
        AccessTuple(subject="user:U11", relation=t.relation, object=t.object)
        for t in store.tuples_of("U01")
    ]
    store.write(twin)
    cache = InMemoryAnswerCache()
    s01 = scope_for("U01", store, POLICY, CLASSES)
    cache.put("spouse transfer precedent", s01, "answer A", frozenset({"AP-FIN01-GOMS-31-2025"}))
    assert (
        cache.get("Spouse  transfer precedent", scope_for("U11", store, POLICY, CLASSES))
        == "answer A"
    )
    assert cache.get("spouse transfer precedent", scope_for("U03", store, POLICY, CLASSES)) is None
    assert cache.get("spouse transfer precedent", scope_for("U02", store, POLICY, CLASSES)) is None


def test_permission_change_moves_officer_to_a_new_cache_key() -> None:
    store = new_store()
    before = answer_cache_key("q", scope_for("U01", store, POLICY, CLASSES))
    store.write(
        [
            AccessTuple(
                subject="user:U01", relation=Relation.ASSIGNED, object="file:USD01-31/4/2025-VIG"
            )
        ]
    )
    assert answer_cache_key("q", scope_for("U01", store, POLICY, CLASSES)) != before


def test_unverifiable_scope_bypasses_cache_and_new_documents_invalidate() -> None:
    cache = InMemoryAnswerCache()
    s = scope_for("U01", new_store(), POLICY, CLASSES)
    cache.put("q", None, "x", frozenset())
    assert len(cache) == 0 and cache.get("q", None) is None
    cache.put("q", s, "x", frozenset({"AP-FIN01-GOMS-88-2022"}))
    assert cache.invalidate_documents(frozenset({"AP-FIN01-GOMS-88-2022"})) == 1
    assert cache.get("q", s) is None
