"""Officer conveniences (ADR-0034): references as written in a note, the cited paragraph on
hover, the usage dashboard (aggregates, monitoring officers only) and the officer's digest —
each within the officer's access, with the same 404 for hidden and unknown."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.agents.passage_context import context_of
from app.auth.messages import DOCUMENT_NOT_AVAILABLE
from app.config import get_settings
from app.connectors.eoffice import OfficerFile
from app.hitl.feedback import Action, HumanAction, TargetKind
from app.identifiers.display import reference_text
from app.main import create_app
from app.tracking.query_log import QueryRecord
from app.tracking.usage import summarise

APP = create_app(get_settings().model_copy(update={"sandbox": True, "monitoring_users": "U05"}))


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        yield c


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


# --- references as an officer writes them -----------------------------------------------


def test_reference_text_says_only_what_the_id_and_the_date_say() -> None:
    names = {"FIN01": "Finance", "GAD01": "General Administration"}
    assert (
        reference_text("AP-FIN01-GOMS-31-2025#para-2.v", dt.date(2025, 5, 12), names)
        == "G.O.Ms.No.31, Finance Department, dated 12-05-2025, para 2(v)"
    )
    assert reference_text("AP-FIN01-GOMS-88-2022", None, names) == (
        "G.O.Ms.No.88, Finance Department, of 2022"
    )
    assert reference_text("AP-GAD01-CIRMEMO-GAD01SERA0-3-2023-D20230814", None, names) == (
        "Circular Memo No.3/2023, General Administration Department, dated 14-08-2023"
    )
    assert reference_text("AP-USD01-NOTE-USD0112-31-2022") == "AP-USD01-NOTE-USD0112-31-2022"
    assert reference_text("not an id") == "not an id"
    assert reference_text("AP-ZZZ01-GOMS-1-2020", None, names) == "G.O.Ms.No.1, of 2020"


# --- the cited paragraph ------------------------------------------------------------------


def test_the_paragraph_holding_the_quote_is_found_and_marked() -> None:
    text = (
        "ORDER:\n\n2. The ban is relaxed:\n(iv) Transfers shall not exceed 15%.\n"
        "(v) Spouse cases, where both spouses are State\n Government employees, shall be "
        "given preference.\n(vi) Dated 18-09-\n2026.\n"
    )
    c = context_of(text, "spouse cases, where both spouses are state government employees")
    assert c is not None and c.paragraph.startswith("(v) Spouse cases")
    s, e = c.highlight or (0, 0)
    assert (
        c.paragraph[s:e].lower().split()
        == "spouse cases, where both spouses are state government employees".split()
    )
    d = context_of(text, "18-09-2026")
    assert d is not None and d.paragraph.startswith("(vi)")
    assert context_of(text, "words that are not there") is None


def test_context_route_same_404_for_hidden_and_unknown(client: TestClient) -> None:
    ok = client.get(
        "/assist/documents/AP-FIN01-GOMS-31-2025%23para-2.v/context",
        params={"quote": "Spouse cases"},
        headers=_h("U01"),
    )
    assert ok.status_code == 200
    j = ok.json()
    assert (
        j["reference"].startswith("G.O.Ms.No.31, Finance Department")
        and "para 2(v)" in j["reference"]
    )
    assert j["paragraph"] and "Spouse cases" in j["paragraph"]
    s, e = j["highlight"]
    assert j["paragraph"][s:e] == "Spouse cases"
    hidden = client.get(  # D20: the confidential decision, hidden from U01
        "/assist/documents/AP-USD01-NOTE-USD0112-58-2025/context",
        params={"quote": "approved"},
        headers=_h("U01"),
    )
    unknown = client.get(
        "/assist/documents/AP-FIN01-GOMS-999-2031/context",
        params={"quote": "approved"},
        headers=_h("U01"),
    )
    assert (hidden.status_code, hidden.json()) == (404, {"detail": DOCUMENT_NOT_AVAILABLE})
    assert (unknown.status_code, unknown.content) == (hidden.status_code, hidden.content)


def test_citations_carry_the_written_reference(client: TestClient) -> None:
    r = client.post(
        "/assist/chat",
        json={"message": "Is G.O.Ms.No.88/2022 still in force?"},
        headers=_h("U01"),
    ).json()
    cites = [c for s in r["statements"] for c in s["citations"]]
    assert cites and all(c["reference"] for c in cites)
    assert any(c["reference"].startswith("G.O.Ms.No.88, Finance Department") for c in cites)


# --- usage dashboard ------------------------------------------------------------------------


def _rec(day: int, ms: int, status: str, rung: str | None, hit: bool = False) -> QueryRecord:
    return QueryRecord(
        query_id=f"q{day}{ms}",
        ts=dt.datetime(2026, 11, day, 10, tzinfo=dt.UTC),
        session_id="s",
        turn=1,
        user_id="U01",
        department="USD01",
        section=None,
        role="SO",
        query_hash="h",
        intent=None,
        ladder_level=rung,
        scope_signature=None,
        latency_ms=ms,
        cache_hit=hit,
        answer_status=status,
    )


def test_usage_aggregates_only() -> None:
    recs = [
        _rec(14, 1000, "answered", "L0"),
        _rec(14, 3000, "no_answer", None),
        _rec(15, 2000, "answered", "L2", hit=True),
        _rec(1, 9999, "answered", "L1"),  # before the window
    ]
    acts = [
        HumanAction(
            action_id="a",
            ts=dt.datetime(2026, 11, 15, tzinfo=dt.UTC),
            user_id="U01",
            query_id="q",
            target_kind=TargetKind.ANSWER,
            action=Action.THUMBS_UP,
        )
    ]
    u = summarise(recs, acts, dt.date(2026, 11, 10), {"build_seconds": 2.4})
    assert u.questions == 3 and u.outcomes["answered"] == 2 and u.outcomes["no_answer"] == 1
    assert [d.questions for d in u.days] == [2, 1] and u.days[0].p50_ms == 2000
    assert u.cache_hit_rate == round(1 / 3, 3) and u.no_answer_rate == round(1 / 3, 3)
    assert u.answered_by == {"L0": 1, "none": 1, "L2": 1} and u.feedback == {"thumbs_up": 1}
    assert u.start == {"build_seconds": 2.4}
    dumped = u.model_dump_json()
    assert "U01" not in dumped and "q14" not in dumped  # no user, no query IDs


def test_usage_is_only_for_monitoring_officers(client: TestClient) -> None:
    client.post("/assist/chat", json={"message": "leave encashment precedent"}, headers=_h("U01"))
    ok = client.get("/assist/usage", headers=_h("U05"))
    assert ok.status_code == 200 and ok.json()["questions"] >= 1
    assert ok.json()["start"]["build_seconds"] >= 0
    other = client.get("/assist/usage", headers=_h("U01"))
    nowhere = client.get("/assist/no-such-route", headers=_h("U01"))
    assert other.status_code == nowhere.status_code == 404
    assert other.json() == nowhere.json()


# --- the officer's digest ---------------------------------------------------------------------


def test_digest_lists_only_files_the_officer_can_open(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = (
        OfficerFile(
            computer_no="2894562",
            file_no="USD01-12/19/2026-ESTT.I",
            subject="s",
            with_officer=True,
            since=dt.datetime(2026, 9, 22, tzinfo=dt.UTC),
            due_on=dt.date(2026, 9, 30),
        ),
        OfficerFile(  # a Vigilance file U01 is not cleared for: must not appear at all
            computer_no="2633187",
            file_no="USD01-31/2/2024-VIG",
            subject="hidden",
            with_officer=True,
            since=dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
        ),
    )
    monkeypatch.setattr(APP.state.adapter, "officer_files", lambda uid: files)
    j = client.get("/assist/digest", headers=_h("U01")).json()
    assert [w["computer_no"] for w in j["waiting"]] == ["2894562"]
    w = j["waiting"][0]
    assert (
        w["overdue"] is True
        and w["days_waiting"] == (dt.date(2026, 10, 2) - dt.date(2026, 9, 22)).days
    )
    assert "hidden" not in str(j) and "2633187" not in str(j)
    for c in j["changed_orders"]:
        assert c["status"] in {"superseded", "repealed", "expired"} and c["reference"]
