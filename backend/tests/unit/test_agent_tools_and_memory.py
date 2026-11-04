"""Bounded agent tools (plan §5.6) and session-memory scope rules (plan §10.1, §13.2 'memory')."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from app.agents.tools import STATUS_UNCONFIRMED, ToolContext, ToolError, ToolName, call_tool
from app.auth.models import StatusCoverage
from app.auth.store import AccessTuple, Relation
from app.config import REPO_ROOT, load_hierarchy
from app.memory.session import SessionError, SessionMemory, Turn
from app.temporal.engine import Instrument, RelationKind, TemporalRelation
from tests.unit.mock_access import CLASSES, MATRIX, POLICY, USER_IDS, doc_tags, new_store, rows
from tests.unit.test_ladder import CFG, CID, DOC, GRAPH, INDEX, L2

TAGS = doc_tags()
IDX = {r["id"]: r for r in rows("documents_index.csv")}
HIERARCHY = load_hierarchy(REPO_ROOT / "data" / "ontology" / "hierarchy.yaml")
_REL = [r for r in rows("ground_truth/relations.csv") if r["relation"] in {"SUPERSEDES", "REPEALS"}]
SUPERSEDED = {r["to_canonical_or_raw"] for r in _REL}
RELS = tuple(
    TemporalRelation(
        source=r["from_canonical"],
        kind=RelationKind(r["relation"]),
        target=r["to_canonical_or_raw"],
    )
    for r in _REL
)


def _iso(s: str) -> dt.date | None:
    return dt.date.fromisoformat(s) if s else None


INSTRUMENTS = {
    r["canonical_id"]: Instrument(
        canonical_id=r["canonical_id"],
        hierarchy_level=int(r["hierarchy_level"]),
        effective_from=_iso(r["effective_from"]),
        valid_until=None if r["canonical_id"] in SUPERSEDED else _iso(r["effective_to"]),
    )
    for r in IDX.values()
}


def _ctx(uid: str, as_of: dt.date = dt.date(2026, 10, 2), store=None, policy=POLICY) -> ToolContext:  # type: ignore[no-untyped-def]
    return ToolContext(
        user_id=uid,
        as_of=as_of,
        index=INDEX,
        l2=L2,
        graph=GRAPH,
        cfg=CFG,
        store=store or new_store(),
        policy=policy,
        classification=CLASSES,
        hierarchy=HIERARCHY,
        instruments=INSTRUMENTS,
        relations=RELS,
    )


def _call(uid: str, name: str, args: dict[str, Any], **kw: Any):  # type: ignore[no-untyped-def]
    return call_tool(_ctx(uid, **kw), name, args)


def _docs(res) -> set[str]:  # type: ignore[no-untyped-def]
    return {DOC[d.canonical_id] for d in res.documents}


# ---- tools ------------------------------------------------------------------------------------


def test_compare_documents_reports_precedence_as_context() -> None:
    res = _call("U03", "compare_documents", {"canonical_ids": [CID["D13"], CID["D14"]]})
    assert res.precedence is not None and res.precedence.prevails == CID["D14"]


def test_find_precedents_returns_notings_only() -> None:
    res = _call("U01", "find_precedents", {"text": "spouse grounds transfer request"})
    assert res.documents and all(d.doc_type.startswith("Noting") for d in res.documents)
    assert "D20" not in _docs(res)


@pytest.mark.parametrize("uid", USER_IDS)
def test_absent_and_forbidden_look_identical_for_every_tool(uid: str) -> None:
    forbidden = [d for d in IDX if not MATRIX[(d, uid)]]
    absent = "AP-USD01-GOMS-999-2025"
    for did in forbidden:
        for name in ("get_document", "check_document_status"):
            hidden = _call(uid, name, {"canonical_ids": [CID[did]]})
            missing = _call(uid, name, {"canonical_ids": [absent]})
            assert (
                hidden == missing.model_copy(update={"tool": hidden.tool}) and not hidden.available
            )
        pair = _call(uid, "compare_documents", {"canonical_ids": [CID[did], CID["D01"]]})
        assert not pair.available and pair.precedence is None


@pytest.mark.parametrize("uid", USER_IDS)
def test_search_tools_never_return_forbidden_documents(uid: str) -> None:
    for name, args in (
        ("search_authorized_documents", {"text": "vigilance enquiry report drain tenders charges"}),
        ("search_authorized_documents", {"terms": ["transfer"]}),
        ("find_precedents", {"text": "transfer request vigilance clearance"}),
        ("get_current_rules", {"terms": ["works"]}),
    ):
        res = _call(uid, name, args)
        assert all(MATRIX[(d, uid)] for d in _docs(res)), (uid, name)


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("run_sql", {"query": "SELECT * FROM documents"}),
        ("get_document", {"canonical_ids": ["G.O.Ms.88"]}),
        ("get_document", {"canonical_ids": [CID["D01"], CID["D02"]]}),
        ("get_document", {"canonical_ids": [CID["D01"]], "text": "and everything else"}),
        ("compare_documents", {"canonical_ids": [CID["D01"]]}),
        ("search_authorized_documents", {"query": "free-form"}),
    ],
)
def test_unknown_tools_and_free_form_arguments_are_refused(name: str, args: dict[str, Any]) -> None:
    with pytest.raises(ToolError):
        _call("U01", name, args)


def test_tool_set_matches_the_plan() -> None:
    assert {t.value for t in ToolName} == {
        "search_authorized_documents",
        "get_document",
        "find_precedents",
        "get_current_rules",
        "check_document_status",
        "compare_documents",
    }


def test_revocation_applies_to_the_next_tool_call() -> None:
    store = new_store()
    args = {"canonical_ids": [CID["D20"]]}
    assert call_tool(_ctx("U04", store=store), "get_document", args).available
    store.delete(
        [
            AccessTuple(
                subject="user:U04",
                relation=Relation.ASSIGNED,
                object="file:USD01-12/58/2025-ESTT.I",
            )
        ]
    )
    assert not call_tool(_ctx("U04", store=store), "get_document", args).available


# ---- status coverage (owner decision, 3 Nov 2026) ------------------------------------------

LENIENT = POLICY.model_copy(update={"status_coverage": StatusCoverage.UP_TO_DOCUMENT})


def test_policy_default_is_the_strict_coverage_rule() -> None:
    assert POLICY.status_coverage is StatusCoverage.FULL_DEPARTMENT


def test_strict_rule_reports_status_only_with_full_department_coverage() -> None:
    sec = _call("U06", "check_document_status", {"canonical_ids": [CID["D12"]]})
    assert sec.status == "superseded" and sec.current_version == CID["D14"]  # Secretary, own dept
    for uid, did in (("U01", "D03"), ("U01", "D14"), ("U06", "D03"), ("U05", "D14")):
        res = _call(uid, "check_document_status", {"canonical_ids": [CID[did]]})
        assert res.status is None and res.current_version is None, (uid, did)
        assert res.message == STATUS_UNCONFIRMED and _docs_unconfirmed(res) == {did}


def _docs_unconfirmed(res) -> set[str]:  # type: ignore[no-untyped-def]
    return {DOC[d.canonical_id] for d in res.status_unconfirmed}


def test_current_rules_never_claim_current_without_coverage() -> None:
    args = {"department": "FIN01", "terms": ["transfers"]}
    strict = _call("U01", "get_current_rules", args)
    assert strict.documents == () and strict.message == STATUS_UNCONFIRMED
    assert _docs_unconfirmed(strict) >= {"D04"}
    now = _call("U01", "get_current_rules", args, policy=LENIENT)
    assert _docs(now) == {"D04", "D05"} and now.message is None  # 31/2025 + clarification
    then = _call("U01", "get_current_rules", args, policy=LENIENT, as_of=dt.date(2023, 1, 1))
    assert _docs(then) == {"D03"}


def test_lenient_rule_still_needs_coverage_for_restricted_orders() -> None:
    assert (
        _call(
            "U01", "check_document_status", {"canonical_ids": [CID["D03"]]}, policy=LENIENT
        ).status
        == "superseded"
    )
    restricted = _call(
        "U01", "check_document_status", {"canonical_ids": [CID["D11"]]}, policy=LENIENT
    )
    assert restricted.message == STATUS_UNCONFIRMED  # RESTRICTED standing order, U01 not dept-wide
    expired = _call("U01", "check_document_status", {"canonical_ids": [CID["D08"]]}, policy=LENIENT)
    assert expired.status == "expired" and expired.current_version is None


def _with_hidden_successor(ctx: ToolContext, target: str) -> ToolContext:
    hidden = Instrument(
        canonical_id="AP-USD01-GOMS-77-2026", hierarchy_level=4, effective_from=dt.date(2026, 1, 1)
    )
    rel = TemporalRelation(source=hidden.canonical_id, kind=RelationKind.SUPERSEDES, target=target)
    return ToolContext(
        **{
            **ctx.__dict__,
            "instruments": {**INSTRUMENTS, hidden.canonical_id: hidden},
            "relations": (*RELS, rel),
        }
    )


@pytest.mark.parametrize("uid", USER_IDS)
def test_outcome_is_identical_with_or_without_a_hidden_successor(uid: str) -> None:
    """The generic message must not depend on whether a hidden superseding order exists."""
    for did in (d for d in IDX if MATRIX[(d, uid)]):
        args = {"canonical_ids": [CID[did]]}
        plain = call_tool(_ctx(uid), "check_document_status", args)
        hidden = call_tool(
            _with_hidden_successor(_ctx(uid), CID[did]), "check_document_status", args
        )
        assert plain == hidden, (uid, did)


# ---- session memory -------------------------------------------------------------------------

LOCATIONS = {CID[d]: TAGS[d] for d in IDX}
T0 = dt.datetime(2026, 10, 2, 10, tzinfo=dt.UTC)


def _turn(rid: str, ids: tuple[str, ...]) -> Turn:
    return Turn(request_id=rid, at=T0, canonical_query="q", entity_ids=ids, scope_signature="s")


def _recall(mem: SessionMemory, uid: str, sid: str, store=None) -> tuple[str, ...]:  # type: ignore[no-untyped-def]
    return mem.recall(
        uid,
        sid,
        locations=LOCATIONS,
        store=store or new_store(),
        policy=POLICY,
        classification=CLASSES,
    )


def test_that_precedent_resolves_newest_first() -> None:
    mem = SessionMemory()
    mem.append("U01", "S1", _turn("R1", (CID["D17"],)))
    mem.append("U01", "S1", _turn("R2", (CID["D19"], CID["D04"])))
    assert _recall(mem, "U01", "S1") == (CID["D19"], CID["D04"], CID["D17"])


def test_sessions_are_never_shared_between_users() -> None:
    mem = SessionMemory()
    mem.append("U04", "S9", _turn("R1", (CID["D21"],)))
    with pytest.raises(SessionError):
        mem.turns("U01", "S9")
    with pytest.raises(SessionError):
        mem.append("U01", "S9", _turn("R2", ()))


def test_mid_session_revocation_drops_remembered_entities() -> None:
    """Turn N cannot surface what an earlier turn retrieved under a wider scope (plan §13.2)."""
    store = new_store()
    mem = SessionMemory()
    mem.append("U04", "S1", _turn("R1", (CID["D20"], CID["D21"])))
    assert _recall(mem, "U04", "S1", store) == (CID["D20"], CID["D21"])
    store.delete(
        [
            AccessTuple(
                subject="user:U04",
                relation=Relation.ASSIGNED,
                object="file:USD01-12/58/2025-ESTT.I",
            )
        ]
    )
    assert _recall(mem, "U04", "S1", store) == (CID["D21"],)


def test_memory_keeps_ids_only_and_is_bounded() -> None:
    assert set(Turn.model_fields) == {
        "request_id",
        "at",
        "canonical_query",
        "entity_ids",
        "scope_signature",
    }
    mem = SessionMemory(max_turns=3)
    for i in range(5):
        mem.append("U01", "S1", _turn(f"R{i}", ()))
    assert [t.request_id for t in mem.turns("U01", "S1")] == ["R2", "R3", "R4"]
