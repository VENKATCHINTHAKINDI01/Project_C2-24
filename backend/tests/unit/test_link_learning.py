"""ADR-0074: links between orders learnt from officers' work, under the owner's governance rules."""

# ruff: noqa: E501

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth.models import Scope
from app.config import get_settings
from app.graph.link_learning import (
    Governance,
    LinkDecision,
    LinkKey,
    LinkSignal,
    LinkState,
    LinkStatus,
    Permission,
    evidence_holds,
    link_status,
    load_governance,
    rollup_links,
    wording,
    work_signals,
)
from app.graph.repository import EdgeKind, GraphEdge
from app.main import create_app

GOV, VERSION = load_governance(get_settings().relationship_governance_path)
T0 = dt.datetime(2026, 11, 27, 10, tzinfo=dt.UTC)
LINK = {"source": "AP-ESE01-GOMS-29-2021", "kind": "SUPERSEDES", "target": "AP-ESE01-GOMS-8-2021"}


def sig(user: str, weight: int = 1, days: int = 0, minutes: int = 0, **kw: Any) -> LinkSignal:
    return LinkSignal(
        at=T0 + dt.timedelta(days=days, minutes=minutes),
        request_id="r",
        user_id=user,
        post="Section Officer",
        department="ESE01",
        code="useful" if weight > 0 else "not_right",
        weight=weight,
        config_version=VERSION,
        **LINK,
        **kw,
    )


def dec(action: str, minutes: int = 0) -> LinkDecision:
    return LinkDecision(
        at=T0 + dt.timedelta(minutes=minutes),
        request_id="r",
        user_id="U05",
        post="Deputy Secretary",
        department="ESE01",
        action=action,
        reason="checked the order",
        config_version=VERSION,
        **LINK,
    )


def status(
    signals: tuple[LinkSignal, ...] | list[LinkSignal] = (),
    decisions: tuple[LinkDecision, ...] | list[LinkDecision] = (),
    gov: Governance = GOV,
    **kw: Any,
) -> LinkStatus:
    return link_status(
        stated_in_text=kw.get("stated", False),
        wording_found=kw.get("wording", True),
        signals=signals,
        decisions=decisions,
        gov=gov,
    )


# --- governance settings ------------------------------------------------------------------------


def test_the_settings_load_versioned_and_marked_to_confirm() -> None:
    assert GOV.validation_authority.status == "TO_CONFIRM"
    assert VERSION.startswith(GOV.version + "+") and len(VERSION) > len(GOV.version) + 10
    assert (GOV.usage_support.minimum_score, GOV.usage_support.minimum_distinct_officers) == (5, 2)


def test_permission_comes_from_the_configured_posts_longest_match_first() -> None:
    assert GOV.permission("Section Officer (Estt.I)") is Permission.VALIDATE
    assert GOV.permission("Assistant Section Officer") is Permission.FLAG
    assert GOV.permission("Senior Assistant") is Permission.FLAG
    assert GOV.permission("Junior Assistant") is Permission.VIEW
    assert GOV.permission("Assistant Secretary (Estt.)") is Permission.VALIDATE
    assert GOV.permission("Monitoring Officer, C2-24 Assist") is Permission.VIEW
    assert GOV.permission("Record Keeper") is Permission.VIEW  # not listed: the default


def test_validation_is_limited_to_the_officers_department() -> None:
    assert GOV.may_validate("Deputy Secretary", "ESE01", {"ESE01"})
    assert not GOV.may_validate("Deputy Secretary", "FIN01", {"ESE01"})
    assert not GOV.may_validate("Deputy Secretary", "ESE01", {"ESE01", "FIN01"})
    assert not GOV.may_validate("Assistant Section Officer", "ESE01", {"ESE01"})


@pytest.mark.parametrize("field", ["auto_validate_from_usage", "auto_validate_from_approval"])
def test_usage_or_approval_can_never_be_configured_to_validate(field: str) -> None:
    data = GOV.model_dump()
    data["legal_validation"][field] = True
    with pytest.raises(ValidationError):
        Governance.model_validate(data)


def test_a_single_officer_threshold_is_refused() -> None:
    data = GOV.model_dump()
    data["usage_support"]["minimum_distinct_officers"] = 1
    with pytest.raises(ValidationError):
        Governance.model_validate(data)


# --- states ---------------------------------------------------------------------------------------


def test_wording_found_is_suggested_and_none_is_candidate() -> None:
    assert status().state is LinkState.SUGGESTED
    assert status(wording=False).state is LinkState.CANDIDATE


def test_use_by_independent_officers_gives_support_never_validation() -> None:
    s = [sig("U01", 1, days=d) for d in range(3)] + [sig("U02", 1, days=d) for d in range(3)]
    st = status(s)
    assert st.state is LinkState.SUPPORTED_BY_USE and (st.score, st.officers) == (6, 2)


def test_one_officers_repeated_use_cannot_pass_for_adoption() -> None:
    many = [sig("U01", 1, days=d, minutes=m) for d in range(10) for m in range(5)]
    st = status(many)
    assert (
        st.state is LinkState.SUGGESTED
        and st.score == GOV.usage_support.max_score_per_officer
        and st.officers == 1
    )


def test_test_and_automated_activity_is_not_counted() -> None:
    gov = Governance.model_validate(
        {
            **GOV.model_dump(),
            "usage_support": {**GOV.usage_support.model_dump(), "test_officers": ("U02",)},
        }
    )
    s = (
        [sig("U01", 1, days=d) for d in range(3)]
        + [sig("U02", 1, days=d) for d in range(3)]
        + [sig("U03", 1, days=d, automated=True) for d in range(3)]
    )
    assert status(s, gov=gov).state is LinkState.SUGGESTED


def test_lowering_the_threshold_never_turns_support_into_validation() -> None:
    gov = Governance.model_validate(
        {
            **GOV.model_dump(),
            "usage_support": {**GOV.usage_support.model_dump(), "minimum_score": 1},
        }
    )
    st = status([sig("U01"), sig("U02")], gov=gov)
    assert st.state is LinkState.SUPPORTED_BY_USE


def test_only_a_human_decision_or_the_orders_own_words_validate() -> None:
    assert status(stated=True, wording=False).state is LinkState.VALIDATED
    st = status([], [dec("validate")])
    assert st.state is LinkState.VALIDATED and st.decided_post == "Deputy Secretary"
    assert status([], [dec("validate"), dec("reject", minutes=5)]).state is LinkState.REJECTED


def test_not_right_after_validation_asks_for_a_review_without_changing_the_decision() -> None:
    st = status([sig("U03", -2, minutes=10)], [dec("validate")])
    assert st.state is LinkState.VALIDATED and st.contested


def test_a_request_for_more_evidence_is_shown_until_decided() -> None:
    assert status([], [dec("request_evidence")]).evidence_requested
    assert not status([], [dec("request_evidence"), dec("validate", minutes=1)]).evidence_requested


def test_documentary_evidence_must_be_the_newer_orders_own_sentence() -> None:
    text = "ORDER. In supersession of G.O.Ms.No.8, School Education (Ser.I) Department, dated 05.03.2021, the following orders are issued. Other matter."
    s = wording(text, "AP-ESE01-GOMS-8-2021")
    assert s is not None and "supersession" in s
    assert evidence_holds(text, "AP-ESE01-GOMS-8-2021", s)
    assert not evidence_holds(
        text,
        "AP-ESE01-GOMS-8-2021",
        "In supersession of G.O.Ms.No.8 dated 2021 all orders stand cancelled.",
    )
    assert not evidence_holds(text, "AP-ESE01-GOMS-85-2021", s)
    assert wording("G.O.Ms.No.18 of 2021 is referred.", "AP-ESE01-GOMS-8-2021") is None


def test_an_order_cited_through_its_read_list_is_found() -> None:
    """Real G.O.s cite the older order as "the G.O. 1st read above" (synthetic D14)."""
    text = (
        "G.O.Ms.No.27 Dated: 06-08-2024\nRead the following:\n"
        "1. G.O.Ms.No.14, Urban Services (Works) Department, Dt.18-03-2021.\n"
        "2. From the Commissioner, Urban Services, Lr.No.USD-W/77/2024, Dt.19-04-2024.\nORDER:\n"
        "1. In the G.O. 1st read above, Government delegated powers. "
        "2. Government, after careful examination, and in supersession of the orders issued in the G.O. 1st read above, hereby delegate the following powers:\n"
    )
    s = wording(text, "AP-USD01-GOMS-14-2021")
    assert (
        s is not None and s.startswith("2. Government") or (s is not None and "supersession" in s)
    )
    assert evidence_holds(text, "AP-USD01-GOMS-14-2021", s or "")
    assert wording(text, "AP-USD01-GOMS-9-2023") is None


# --- API -----------------------------------------------------------------------------------------


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


NEW, OLD = "AP-USD01-GOMS-27-2024", "AP-USD01-GOMS-14-2021"


@pytest.fixture(scope="module")
def c() -> Iterator[TestClient]:
    app = create_app(get_settings().model_copy(update={"sandbox": True}))
    with TestClient(app) as client:
        client.get("/assist/notices", headers=_h("U01"))
        # an inferred (unconfirmed) link next to the one the order states
        app.state.assist_runtime().stores.graph.upsert_edge(
            GraphEdge(source=NEW, kind=EdgeKind.AMENDS, target=OLD, confirmed=False)
        )
        yield client


def _link(c: TestClient, uid: str, kind: str) -> dict[str, Any]:
    r = c.get(f"/assist/links/{NEW}", headers=_h(uid))
    assert r.status_code == 200, r.text
    return next(x for x in r.json()["links"] if x["kind"] == kind and x["target"] == OLD)


def test_the_panel_shows_stated_and_inferred_links_with_permissions(c: TestClient) -> None:
    stated = _link(c, "U01", "SUPERSEDES")
    assert stated["state"] == "validated" and stated["stated_in_text"] and stated["can_validate"]
    inferred = _link(c, "U01", "AMENDS")
    assert inferred["state"] in ("suggested", "candidate") and not inferred["stated_in_text"]


def test_view_only_posts_cannot_flag(c: TestClient) -> None:
    r = c.post(
        "/assist/links/feedback",
        json={"source": NEW, "kind": "AMENDS", "target": OLD, "code": "useful"},
        headers=_h("M01"),
    )
    assert r.status_code == 403


def test_signals_are_recorded_but_never_validate(c: TestClient) -> None:
    for uid in ("U01", "U02", "U03"):
        r = c.post(
            "/assist/links/feedback",
            json={"source": NEW, "kind": "AMENDS", "target": OLD, "code": "useful"},
            headers=_h(uid),
        )
        assert r.status_code == 200, r.text
    assert _link(c, "U01", "AMENDS")["state"] != "validated"


def test_validation_needs_the_orders_sentence(c: TestClient) -> None:
    body = {
        "source": NEW,
        "kind": "AMENDS",
        "target": OLD,
        "action": "validate",
        "reason": "read both orders",
    }
    assert c.post("/assist/links/decision", json=body, headers=_h("U05")).status_code == 409
    bad = c.post(
        "/assist/links/decision",
        json={**body, "evidence": "This sentence is not in the order at all, G.O. 14 of 2021."},
        headers=_h("U05"),
    )
    assert bad.status_code == 409
    said = _link(c, "U05", "AMENDS")["wording"]
    assert said and "supersession" in said
    ok = c.post("/assist/links/decision", json={**body, "evidence": said}, headers=_h("U05"))
    assert ok.status_code == 200, ok.text
    got = _link(c, "U01", "AMENDS")
    assert got["state"] == "validated" and got["decided_post"] == "Deputy Secretary"


def test_an_officer_of_another_department_cannot_decide(c: TestClient) -> None:
    body = {
        "source": NEW,
        "kind": "AMENDS",
        "target": OLD,
        "action": "reject",
        "reason": "not related",
    }
    assert c.post("/assist/links/decision", json=body, headers=_h("U07")).status_code in (403, 404)


def test_an_unknown_link_is_the_same_not_available(c: TestClient) -> None:
    body = {"source": NEW, "kind": "REPEALS", "target": OLD, "code": "useful"}
    assert c.post("/assist/links/feedback", json=body, headers=_h("U01")).status_code == 404


def test_reject_and_ask_for_evidence_are_recorded_with_the_post(c: TestClient) -> None:
    base = {"source": NEW, "kind": "AMENDS", "target": OLD}
    assert (
        c.post(
            "/assist/links/decision",
            json={**base, "action": "request_evidence", "reason": "need the amending para"},
            headers=_h("U05"),
        ).status_code
        == 200
    )
    assert _link(c, "U01", "AMENDS")["evidence_requested"]
    assert (
        c.post(
            "/assist/links/decision",
            json={**base, "action": "reject", "reason": "it supersedes, not amends"},
            headers=_h("U05"),
        ).status_code
        == 200
    )
    got = _link(c, "U01", "AMENDS")
    assert got["state"] == "rejected" and got["decided_post"] == "Deputy Secretary"


# --- step 2: W and C work signals ----------------------------------------------------------------


def test_work_signals_w1_to_w7_and_c1_to_c4() -> None:
    lk = LinkKey(source=NEW, kind="SUPERSEDES", target=OLD)
    links = [lk]

    # W1: note cites newer order when earlier note cited older
    assert work_signals(
        links=links,
        event_kind="note_written",
        text=f"As per {NEW}, sanction is accorded.",
        earlier_text=f"Earlier note relied on {OLD}.",
    ) == [(lk, "note_cites_newer", None)]

    # W2: note cites older order as in force
    assert work_signals(
        links=links,
        event_kind="note_written",
        text=f"Orders in {OLD} apply to this proposal.",
    ) == [(lk, "note_cites_older", None)]

    # W3: explicit supersession statement vs "still in force"
    w3_pos = work_signals(
        links=links,
        event_kind="note_written",
        text=f"In supersession of G.O.Ms.No.14 of 2021, {NEW} governs.",
    )
    assert (lk, "note_states_supersession", None) in w3_pos

    w3_neg = work_signals(
        links=links,
        event_kind="note_written",
        text="G.O.Ms.No.14 of 2021 is still in force.",
    )
    assert (lk, "note_states_in_force", None) in w3_neg

    # W4 & W5: draft kept vs removed on confirmation
    assert (lk, "draft_kept", None) in work_signals(
        links=links,
        event_kind="note_confirmed",
        text=f"Put up under {NEW}.",
        initial_text=f"Draft citing {NEW}.",
    )
    assert (lk, "draft_removed", None) in work_signals(
        links=links,
        event_kind="note_confirmed",
        text="Put up without citing any order.",
        initial_text=f"Draft citing {NEW}.",
    )

    # W6: draft_approved (+3) supports use, never validates
    w6 = work_signals(links=links, event_kind="draft_approved", text=f"Issued under {NEW}.")
    assert w6 == [(lk, "draft_approved", None)]
    assert GOV.signal_weights["draft_approved"] == 3
    st = link_status(
        stated_in_text=False,
        wording_found=True,
        signals=[sig("U06", GOV.signal_weights["draft_approved"])],
        decisions=[],
        gov=GOV,
    )
    assert st.state is not LinkState.VALIDATED

    # W7: draft_returned with remark naming order/wrong
    assert work_signals(
        links=links,
        event_kind="draft_returned",
        text=f"Draft under {NEW}.",
        remarks=f"Wrong order cited: {NEW} does not apply.",
    ) == [(lk, "draft_returned_wrong", f"Wrong order cited: {NEW} does not apply.")]

    # C1: presend_fixed after prior Type A flag
    assert work_signals(
        links=links,
        event_kind="presend",
        text=f"Updated to cite {NEW}.",
        prior_flagged_older=[OLD],
    ) == [(lk, "presend_fixed", None)]

    # C2: send_file with "still in force" remark
    assert (lk, "presend_still_in_force", f"{OLD} is still in force.") in work_signals(
        links=links,
        event_kind="note_written",
        text=f"Proceeding under {OLD}.",
        remarks=f"{OLD} is still in force.",
    )

    # C3 & C4: Type A conflict flag accept / dismiss
    assert work_signals(
        links=links,
        event_kind="flag_feedback",
        text="",
        flag_action="accept",
        flag_older_id=OLD,
    ) == [(lk, "flag_accepted", None)]
    assert work_signals(
        links=links,
        event_kind="flag_feedback",
        text="",
        flag_action="dismiss",
        flag_older_id=OLD,
    ) == [(lk, "flag_dismissed", "not a conflict")]


def test_presend_and_conflict_flag_feedback_record_work_signals() -> None:
    app = create_app(get_settings().model_copy(update={"sandbox": True}))
    fin_new, fin_old = "AP-FIN01-GOMS-31-2025", "AP-FIN01-GOMS-88-2022"
    with TestClient(app) as client:
        # 2894562 is U01's open file citing G.O.Ms.88/2022 (superseded by G.O.Ms.31/2025)
        cno = "2894562"

        # 1. Conflict flag feedback (C3 accepted)
        r_fb = client.post(
            "/assist/feedback",
            json={
                "kind": "conflict_flag",
                "action": "accepted",
                "request_id": "req-link-1",
                "computer_no": cno,
                "flag_type": "A",
                "canonical_id": fin_old,
            },
            headers=_h("U01"),
        )
        assert r_fb.status_code == 200, r_fb.text

        # 2. Pre-send flags fin_old (Type A), then officer updates note to cite fin_new -> C1
        r_pre1 = client.post("/assist/presend", json={"computer_no": cno}, headers=_h("U01"))
        assert r_pre1.status_code == 200, r_pre1.text
        assert any(
            f["type"] == "A" and f["cited"] == fin_old for f in r_pre1.json().get("flags", [])
        )

        r_pre2 = client.post(
            "/assist/presend",
            json={
                "computer_no": cno,
                "text": "Submitted under G.O.Ms.No.31, Finance Dept., 2025 for sanction.",
            },
            headers=_h("U01"),
        )
        assert r_pre2.status_code == 200, r_pre2.text

        # Confirm U01's work signals were recorded on (fin_new, SUPERSEDES, fin_old)
        r_links = client.get(f"/assist/links/{fin_new}", headers=_h("U01"))
        assert r_links.status_code == 200, r_links.text
        got = next(
            x
            for x in r_links.json()["links"]
            if x["kind"] == "SUPERSEDES" and x["target"] == fin_old
        )
        assert got["score"] >= 3  # C1 (+3) and C3 (+2) capped at max_score_per_officer=3 for U01


# --- step 3: nightly roll-up, audit, cache invalidation ------------------------------------------


def test_rollup_updates_graph_audits_state_changes_and_invalidates_cache() -> None:
    from app.audit.log import AuditLog
    from app.auth.models import DocumentAccessTags
    from app.cache.answers import InMemoryAnswerCache
    from app.graph.link_learning import InMemoryLinkStore
    from app.graph.repository import GraphNode, InMemoryGraphRepository

    graph = InMemoryGraphRepository()
    for cid in (NEW, OLD):
        graph.upsert_node(
            GraphNode(
                canonical_id=cid,
                tags=DocumentAccessTags(
                    doc_id=cid, department="USD01", classification="UNCLASSIFIED"
                ),
            )
        )
    graph.upsert_edge(GraphEdge(source=NEW, kind=EdgeKind.AMENDS, target=OLD, confirmed=False))

    store = InMemoryLinkStore()
    for uid in ("U01", "U02"):
        store.add_signal(
            LinkSignal(
                at=T0,
                request_id="r",
                user_id=uid,
                post="Section Officer",
                department="USD01",
                code="useful",
                weight=3,
                config_version=VERSION,
                source=NEW,
                kind="AMENDS",
                target=OLD,
            )
        )
    texts = {
        NEW: (
            "G.O.Ms.No.27 Dated: 06-08-2024\n"
            "ORDER:\n"
            "In supersession of G.O.Ms.No.14 of 2021, revised norms are issued."
        )
    }

    scope = Scope(
        user_id="U01",
        policy_version="test",
        classification_ranks={"Public": 0},
        public_rank=0,
        department="FIN",
        max_rank=0,
        department_wide=False,
        sections=frozenset(),
        file_nos=frozenset(),
    )
    cache = InMemoryAnswerCache()
    cache.put("query-1", scope, "old", cited_ids=frozenset({OLD}))
    cache.put("query-2", scope, "other", cited_ids=frozenset({"AP-FIN01-GOMS-1-2020"}))
    audit = AuditLog()

    # 1. Operational support (2 officers, score=6 >= 5) -> supported_by_use, confirmed=False
    res1 = rollup_links(
        graph=graph,
        link_store=store,
        texts=texts,
        gov=GOV,
        gov_version=VERSION,
        audit=audit,
        caches=[cache],
    )
    assert res1.checked == 1
    assert res1.updated == 1
    assert res1.state_changes == 1
    assert res1.invalidated_entries == 1
    edge = next(e for e in graph.edges() if e.kind is EdgeKind.AMENDS)
    assert edge.state == "supported_by_use"
    assert edge.score == 6
    assert edge.confirmed is False  # usage never validates
    assert edge.evidence and "supersession" in edge.evidence
    assert cache.get("query-1", scope) is None
    assert cache.get("query-2", scope) is not None
    assert any(
        ev.action == "graph.link.state_change" and ev.outcome == "supported_by_use"
        for ev in audit.events()
    )

    # 2. Idempotent when nothing changed
    res2 = rollup_links(
        graph=graph,
        link_store=store,
        texts=texts,
        gov=GOV,
        gov_version=VERSION,
        audit=audit,
        caches=[cache],
    )
    assert res2.updated == 0 and res2.state_changes == 0 and res2.invalidated_entries == 0

    # 3. Human validation transitions to validated with confirmed=True
    store.add_decision(
        LinkDecision(
            at=T0,
            request_id="r",
            user_id="U05",
            post="Deputy Secretary",
            department="USD01",
            action="validate",
            reason="checked the order",
            config_version=VERSION,
            source=NEW,
            kind="AMENDS",
            target=OLD,
        )
    )
    cache.put("query-3", scope, "v2", cited_ids=frozenset({NEW}))
    res3 = rollup_links(
        graph=graph,
        link_store=store,
        texts=texts,
        gov=GOV,
        gov_version=VERSION,
        audit=audit,
        caches=[cache],
    )
    assert res3.updated == 1 and res3.state_changes == 1 and res3.invalidated_entries == 1
    edge3 = next(e for e in graph.edges() if e.kind is EdgeKind.AMENDS)
    assert edge3.state == "validated" and edge3.confirmed is True
    assert cache.get("query-3", scope) is None


# --- step 4: File CITES order, File RELATED TO file, Order APPLIES TO section, L1–L3 ----------


def test_file_cites_order_related_files_and_applies_to_section() -> None:
    from app.auth.models import DocumentAccessTags
    from app.graph.link_learning import (
        FileLinkSource,
        build_file_and_section_links,
        file_node_id,
        files_following_order,
        section_node_id,
    )
    from app.graph.repository import Direction, GraphNode, InMemoryGraphRepository

    graph = InMemoryGraphRepository()
    graph.upsert_node(
        GraphNode(
            canonical_id=NEW,
            tags=DocumentAccessTags(doc_id=NEW, department="USD01", classification="UNCLASSIFIED"),
        )
    )
    files = [
        FileLinkSource(
            file_no="USD01-S1/1/2024",
            tags=DocumentAccessTags(
                doc_id="FILE:USD01-S1/1/2024",
                department="USD01",
                section="S1",
                classification="UNCLASSIFIED",
                file_no="USD01-S1/1/2024",
            ),
            texts=(f"Note: following {NEW} for urban norms.",),
            linked_files=("FIN01-F1/2/2024",),
        ),
        FileLinkSource(
            file_no="USD01-S2/2/2024",
            tags=DocumentAccessTags(
                doc_id="FILE:USD01-S2/2/2024",
                department="USD01",
                section="S2",
                classification="RESTRICTED",
                file_no="USD01-S2/2/2024",
            ),
            texts=("Note: G.O.Ms.No.27 of 2024 applies here.",),
        ),
        FileLinkSource(
            file_no="FIN01-F1/2/2024",
            tags=DocumentAccessTags(
                doc_id="FILE:FIN01-F1/2/2024",
                department="FIN01",
                section="F1",
                classification="UNCLASSIFIED",
                file_no="FIN01-F1/2/2024",
            ),
            texts=("Budget concurrence file.",),
        ),
    ]
    res = build_file_and_section_links(graph, files, order_ids=(NEW,))
    assert res.file_cites_order == 2
    assert res.file_related_to_file == 2  # explicit link + shared citation
    assert res.order_applies_to_section == 2

    assert any(
        e.source == file_node_id("USD01-S1/1/2024")
        and e.kind is EdgeKind.RELATED_TO
        and e.target == file_node_id("USD01-S2/2/2024")
        for e in graph.edges()
    )
    assert any(
        e.source == NEW
        and e.kind is EdgeKind.APPLIES_TO
        and e.target == section_node_id("USD01", "S1")
        for e in graph.edges()
    )

    # Scope enforcement: UNCLASSIFIED-only viewer sees F1, never the RESTRICTED file F2
    pub_scope = Scope(
        user_id="U99",
        policy_version="test",
        classification_ranks={"UNCLASSIFIED": 0, "RESTRICTED": 1},
        public_rank=0,
        department="USD01",
        max_rank=0,
        department_wide=True,
        sections=frozenset(),
        file_nos=frozenset(),
    )
    assert files_following_order(graph, NEW, pub_scope) == ["USD01-S1/1/2024"]
    sec_hits = graph.walk(
        [NEW],
        pub_scope,
        kinds=frozenset({EdgeKind.APPLIES_TO}),
        direction=Direction.OUT,
        max_hops=1,
    )
    assert [h.canonical_id for h in sec_hits] == [section_node_id("USD01", "S1")]

    # RESTRICTED-cleared officer in USD01 sees both files
    dept_scope = pub_scope.model_copy(update={"max_rank": 1})
    assert files_following_order(graph, NEW, dept_scope) == [
        "USD01-S1/1/2024",
        "USD01-S2/2/2024",
    ]


def test_linking_signals_l1_to_l3_and_governance_weights() -> None:
    from app.graph.link_learning import linking_signals

    assert GOV.signal_weights["file_adds_reference"] == 1
    assert GOV.signal_weights["files_linked"] == 1
    assert GOV.signal_weights["receipt_cites_newer"] == 1

    lk = LinkKey(**LINK)
    l1 = linking_signals(
        links=[lk],
        action="add_reference",
        primary_orders=[lk.source],
        other_orders=[lk.target],
    )
    assert l1 == [(lk, "file_adds_reference", None)]

    l2 = linking_signals(
        links=[lk],
        action="link_files",
        primary_orders=[lk.source],
        other_orders=[lk.target],
    )
    assert l2 == [(lk, "files_linked", None)]

    l3 = linking_signals(
        links=[lk],
        action="receipt_added",
        primary_orders=[lk.source],
        other_orders=[lk.target],
        receipt_text=f"Letter citing {lk.source} in place of previous norms.",
    )
    assert l3 == [(lk, "receipt_cites_newer", None)]


# --- step 5: monitoring pad — links that changed state this week, with evidence ----------------


def test_recent_link_changes_returns_state_changes_with_evidence_and_respects_visibility() -> None:
    from app.audit.log import AuditLog
    from app.auth.models import DocumentAccessTags
    from app.graph.link_learning import (
        InMemoryLinkStore,
        recent_link_changes,
    )
    from app.graph.repository import GraphNode, InMemoryGraphRepository

    graph = InMemoryGraphRepository()
    for cid in (NEW, OLD, "AP-SEC01-GOMS-1-2024", "AP-SEC01-GOMS-2-2023"):
        graph.upsert_node(
            GraphNode(
                canonical_id=cid,
                tags=DocumentAccessTags(
                    doc_id=cid,
                    department="USD01" if cid in (NEW, OLD) else "SEC01",
                    classification="UNCLASSIFIED" if cid in (NEW, OLD) else "SECRET",
                ),
            )
        )
    graph.upsert_edge(GraphEdge(source=NEW, kind=EdgeKind.AMENDS, target=OLD, confirmed=False))
    graph.upsert_edge(
        GraphEdge(
            source="AP-SEC01-GOMS-1-2024",
            kind=EdgeKind.SUPERSEDES,
            target="AP-SEC01-GOMS-2-2023",
            confirmed=False,
        )
    )

    store = InMemoryLinkStore()
    store.add_decision(
        LinkDecision(
            at=T0,
            request_id="r",
            user_id="U05",
            post="Deputy Secretary",
            department="USD01",
            action="validate",
            reason="checked the order",
            config_version=VERSION,
            source=NEW,
            kind="AMENDS",
            target=OLD,
            evidence="In supersession of G.O.Ms.No.14 of 2021, revised norms are issued.",
        )
    )
    audit = AuditLog()
    rollup_links(
        graph=graph,
        link_store=store,
        texts={
            NEW: (
                "G.O.Ms.No.27 Dated: 06-08-2024\n"
                "ORDER:\n"
                "In supersession of G.O.Ms.No.14 of 2021, revised norms are issued."
            )
        },
        gov=GOV,
        gov_version=VERSION,
        audit=audit,
    )

    # Also simulate a restricted link change in audit that a lower-cleared monitor cannot see
    audit.record(
        "rollup",
        "system.rollup",
        "graph.link.state_change",
        "suggested",
        ids=("AP-SEC01-GOMS-1-2024", "SUPERSEDES", "AP-SEC01-GOMS-2-2023", VERSION),
        detail="candidate->suggested score=0 signals=0 decisions=0",
    )

    rows = recent_link_changes(
        audit.events(),
        graph,
        since=dt.datetime.now(dt.UTC) - dt.timedelta(days=7),
        visible=lambda cid: cid in (NEW, OLD),
    )
    assert len(rows) == 1
    assert rows[0].source == NEW
    assert rows[0].target == OLD
    assert rows[0].to_state == "validated"
    assert rows[0].evidence and "supersession" in rows[0].evidence
