"""Human-in-the-loop: the officer confirms or discards an inserted Yellow Note in e-Office, and
gives feedback on answers, statements and conflict flags (plan §9; CLAUDE.md §8; ADR-0031)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.messages import DOCUMENT_NOT_AVAILABLE, FILE_NOT_AVAILABLE
from app.config import get_settings
from app.hitl.feedback import (
    Action,
    InMemoryActionLog,
    TargetKind,
    edit_share,
    strip_watermark,
)
from app.main import create_app
from tests.unit.test_orchestrator import AnswersOnly

APP = create_app(get_settings().model_copy(update={"sandbox": True}))
FILE = "2894562"  # Estt.I spouse-ground transfer; U01 (SO) and U02 (AS) can open it
WATERMARK = "AI FIRST-CUT — draft for the officer; not a note until signed."
BODY = f"{WATERMARK}\n1. Zanzibarite request to transfer on spouse grounds. [S1]\n2. Consider."


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        APP.state.assist_runtime().llm = AnswersOnly()
        try:
            yield c
        finally:
            APP.state.assist_runtime().llm = None


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


def _log() -> InMemoryActionLog:
    log = APP.state.actions
    assert isinstance(log, InMemoryActionLog)
    return log


def _insert(c: TestClient, uid: str, kind: str = "yellow_note", rid: str = "req0000001") -> str:
    r = c.post(
        "/assist/draft",
        json={"computer_no": FILE, "kind": kind, "body": BODY, "request_id": rid},
        headers=_h(uid),
    )
    assert r.status_code == 200, r.text
    return str(r.json()["draft_id"])


def _page(c: TestClient, uid: str) -> dict[str, Any]:
    return dict(c.get(f"/sandbox/files/{FILE}", headers=_h(uid)).json())


def _act(c: TestClient, uid: str, draft_id: str, what: str, **kw: Any) -> Any:
    return c.post(f"/sandbox/files/{FILE}/drafts/{draft_id}/{what}", headers=_h(uid), **kw)


# --- edit share ---------------------------------------------------------------------------


def test_edit_share_counts_the_officers_changes_not_the_watermark() -> None:
    ai = f"{WATERMARK}\nThe request may kindly be considered."
    assert edit_share(ai, "The request may kindly be considered.") == 0.0
    assert edit_share(ai, "The  request may\nkindly be considered.") == 0.0  # spacing only
    assert edit_share(ai, "Entirely different words here now please.") == 1.0
    assert 0.0 < edit_share(ai, "The request may kindly be rejected.") < 0.3
    assert strip_watermark(ai) == "The request may kindly be considered."
    points = (
        "FIRST-CUT NOTE — cited points, prepared with C2-24 Assist; a draft.\nSubject: X\n1. A."
    )
    assert strip_watermark(points) == "Subject: X\n1. A."
    head = "Points for consideration before the file is sent (C2-24 pre-send check, draft):\n1. A."
    assert strip_watermark(head) == "Points for consideration before the file is sent:\n1. A."


# --- the officer's own actions in e-Office --------------------------------------------------


def test_a_yellow_note_is_the_authors_own_until_confirmed(client: TestClient) -> None:
    did = _insert(client, "U01")
    assert any(d["draft_id"] == did for d in _page(client, "U01")["drafts"])
    assert all(d["draft_id"] != did for d in _page(client, "U02")["drafts"])  # same file
    # another officer cannot touch it, and cannot tell it from a draft that does not exist
    for what in ("save", "confirm", "discard"):
        kw = {"json": {"text": "x"}} if what == "save" else {}
        theirs = _act(client, "U02", did, what, **kw)
        nothing = _act(client, "U02", "MOCK-DRAFT-99999", what, **kw)
        assert theirs.status_code == nothing.status_code == 404
        assert theirs.json() == nothing.json()
    # a file the officer cannot open looks like an unknown file
    hidden = client.post("/sandbox/files/2633187/drafts/x/confirm", headers=_h("U01"))
    unknown = client.post("/sandbox/files/9999999/drafts/x/confirm", headers=_h("U01"))
    assert (hidden.status_code, hidden.json()) == (404, {"detail": FILE_NOT_AVAILABLE})
    assert (unknown.status_code, unknown.json()) == (hidden.status_code, hidden.json())


def test_confirming_an_edited_yellow_note_makes_the_next_green_note_and_records_feedback(
    client: TestClient,
) -> None:
    before = _page(client, "U01")["notes"]
    did = _insert(client, "U01", rid="req0000002")
    edited = BODY.replace("2. Consider.", "2. Submitted for orders.")
    r = _act(client, "U01", did, "save", json={"text": edited})
    assert r.json()["versions"] == 2
    n_actions = len(_log().actions)
    r = _act(client, "U01", did, "confirm")
    assert r.status_code == 200 and r.json()["state"] == "green"
    page = _page(client, "U01")
    note = page["notes"][-1]
    assert len(page["notes"]) == len(before) + 1
    assert note["note_id"] == r.json()["note_id"] and note["state"] == "green"
    assert note["note_no"] == before[-1]["note_no"] + 1
    assert note["created_by_assistant"] is True
    assert "AI FIRST-CUT" not in note["text"] and "Submitted for orders." in note["text"]
    assert all(d["draft_id"] != did for d in page["drafts"])  # no longer a draft
    # the other officer who opens the file now sees the Green Note (it is the file's record)
    assert any(n["note_id"] == note["note_id"] for n in _page(client, "U02")["notes"])
    # confirmed once: a second confirm finds nothing
    assert _act(client, "U01", did, "confirm").status_code == 404
    (rec,) = _log().actions[n_actions:]
    assert rec.user_id == "U01" and rec.query_id == "req0000002"
    assert rec.target_kind is TargetKind.YELLOW_NOTE and rec.action is Action.CONFIRMED_EDITED
    assert rec.target_ids == (FILE, did, note["note_id"])
    assert rec.edit_share is not None and 0 < rec.edit_share < 0.5
    dumped = rec.model_dump_json()
    for word in ("Zanzibarite", "Submitted", "spouse"):  # no text from the note, ever
        assert word not in dumped


def test_confirmed_unchanged_and_discarded(client: TestClient) -> None:
    n = len(_log().actions)
    kept = _insert(client, "U01", rid="req0000003")
    gone = _insert(client, "U01", rid="req0000004")
    assert _act(client, "U01", kept, "confirm").status_code == 200
    r = _act(client, "U01", gone, "discard")
    assert r.json()["status"] == "discarded"
    assert all(d["draft_id"] != gone for d in _page(client, "U01")["drafts"])
    a, b = _log().actions[n:]
    assert (a.action, a.edit_share) == (Action.CONFIRMED, 0.0)
    assert (b.action, b.edit_share, b.query_id) == (Action.DISCARDED, None, "req0000004")


def test_only_a_yellow_note_is_confirmed_here(client: TestClient) -> None:
    did = _insert(client, "U02", kind="dfa_draft")
    r = _act(client, "U02", did, "confirm")
    assert r.status_code == 409 and "Yellow Note" in r.json()["detail"]
    assert any(d["draft_id"] == did for d in _page(client, "U02")["drafts"])  # still a draft


def test_no_assistant_endpoint_can_confirm_a_note(client: TestClient) -> None:
    """Confirming a note is the officer's e-Office action (/sandbox). Under /assist the only
    "confirm" is a human reviewer confirming OCR text (checkpoint 5)."""
    for path in APP.openapi()["paths"]:
        words = set(re.split(r"[/{}_-]+", path))
        if path.startswith("/assist") and "confirm" in words:
            assert path.startswith("/assist/review/"), path
        assert not words & {"sign", "send", "dispatch", "approve"}, path


# --- feedback on answers, statements and flags ----------------------------------------------


def _feedback(c: TestClient, uid: str, **body: Any) -> Any:
    return c.post("/assist/feedback", json=body, headers=_h(uid))


def test_thumbs_on_an_answer_only_in_the_officers_own_session(client: TestClient) -> None:
    r = client.post(
        "/assist/chat",
        json={"message": "Has a spouse-ground transfer been decided before?"},
        headers=_h("U01"),
    ).json()
    sid, rid = r["session_id"], r["request_id"]
    n = len(_log().actions)
    ok = _feedback(client, "U01", kind="answer", request_id=rid, session_id=sid, action="thumbs_up")
    assert ok.status_code == 200 and ok.json()["recorded"] is True
    (rec,) = _log().actions[n:]
    assert (rec.target_kind, rec.action, rec.query_id) == (TargetKind.ANSWER, Action.THUMBS_UP, rid)
    # someone else's session, a made-up session and a request not in the session: all the same
    other = _feedback(
        client, "U02", kind="answer", request_id=rid, session_id=sid, action="thumbs_down"
    )
    madeup = _feedback(
        client, "U02", kind="answer", request_id=rid, session_id="ab" * 8, action="thumbs_down"
    )
    wrong = _feedback(
        client, "U01", kind="answer", request_id="zzzzzzzz", session_id=sid, action="thumbs_down"
    )
    assert other.status_code == madeup.status_code == wrong.status_code == 404
    assert other.json() == madeup.json() == wrong.json()
    assert len(_log().actions) == n + 1


def test_thumbs_on_a_statement_only_for_a_record_the_officer_may_see(client: TestClient) -> None:
    n = len(_log().actions)
    ok = _feedback(
        client,
        "U01",
        kind="statement",
        request_id="req0000005",
        canonical_id="AP-FIN01-GOMS-31-2025#para-2.v",
        action="thumbs_down",
        reason="outdated",
    )
    assert ok.status_code == 200
    (rec,) = _log().actions[n:]
    assert rec.target_ids == ("AP-FIN01-GOMS-31-2025",) and rec.reason is not None
    hidden = _feedback(  # D20: the confidential 2025 decision, hidden from U01
        client,
        "U01",
        kind="statement",
        request_id="req0000005",
        canonical_id="AP-USD01-NOTE-USD0112-58-2025",
        action="thumbs_up",
    )
    unknown = _feedback(
        client,
        "U01",
        kind="statement",
        request_id="req0000005",
        canonical_id="AP-FIN01-GOMS-999-2031",
        action="thumbs_up",
    )
    assert (hidden.status_code, hidden.json()) == (404, {"detail": DOCUMENT_NOT_AVAILABLE})
    assert (unknown.status_code, unknown.content) == (hidden.status_code, hidden.content)
    assert len(_log().actions) == n + 1


def test_accept_or_dismiss_a_flag_on_a_file_the_officer_can_open(client: TestClient) -> None:
    n = len(_log().actions)
    ok = _feedback(
        client,
        "U01",
        kind="conflict_flag",
        request_id="req0000006",
        computer_no=FILE,
        flag_type="A",
        canonical_id="AP-FIN01-GOMS-88-2022",
        action="dismissed",
        reason="already_handled",
    )
    assert ok.status_code == 200
    (rec,) = _log().actions[n:]
    assert rec.target_ids == (FILE, "AP-FIN01-GOMS-88-2022") and rec.flag_type == "A"
    flag = {"kind": "conflict_flag", "request_id": "req0000006", "flag_type": "A"}
    hidden = _feedback(client, "U01", computer_no="2633187", action="accepted", **flag)
    unknown = _feedback(client, "U01", computer_no="9999999", action="accepted", **flag)
    assert (hidden.status_code, hidden.json()) == (404, {"detail": FILE_NOT_AVAILABLE})
    assert (unknown.status_code, unknown.content) == (hidden.status_code, hidden.content)


def test_feedback_takes_fixed_codes_only(client: TestClient) -> None:
    base = {
        "kind": "statement",
        "request_id": "req0000007",
        "canonical_id": "AP-FIN01-GOMS-31-2025",
    }
    assert _feedback(client, "U01", action="dismissed", **base).status_code == 422  # wrong kind
    free = _feedback(client, "U01", action="thumbs_down", reason="the GO says 20%", **base)
    assert free.status_code == 422  # no free-text reason
    extra = _feedback(client, "U01", action="thumbs_down", comment="text", **base)
    assert extra.status_code == 422  # no other fields
    assert _feedback(client, "U01", action="thumbs_up", **base).status_code == 200
    assert "the GO says" not in json.dumps([a.model_dump(mode="json") for a in _log().actions])


def test_bigquery_sink_writes_ids_only_and_never_breaks_the_action() -> None:
    import datetime as dt

    from app.hitl.feedback import BigQueryActionLog, HumanAction

    class Client:
        def __init__(self, fail: bool) -> None:
            self.rows: list[Any] = []
            self.fail = fail

        def insert_rows_json(self, table: str, rows: list[Any]) -> list[Any]:
            if self.fail:
                raise RuntimeError("quota")
            self.rows.append((table, rows))
            return []

    rec = HumanAction(
        action_id="a1",
        ts=dt.datetime(2026, 11, 15, tzinfo=dt.UTC),
        user_id="U01",
        query_id="req0000009",
        target_kind=TargetKind.CONFLICT_FLAG,
        target_ids=(FILE, "AP-FIN01-GOMS-88-2022"),
        action=Action.DISMISSED,
        flag_type="A",
    )
    ok = Client(fail=False)
    BigQueryActionLog("p", "p.c2_audit.human_action", client=ok).write(rec)
    ((table, (row,)),) = ok.rows
    assert table == "p.c2_audit.human_action"
    assert row["target_ids"] == [FILE, "AP-FIN01-GOMS-88-2022"] and row["action"] == "dismissed"
    schema = json.loads(
        (Path(__file__).parents[3] / "data/schemas/bigquery/human_action.json").read_text()
    )
    assert sorted(row) == sorted(f["name"] for f in schema)  # rows match the table
    BigQueryActionLog("p", "t", client=Client(fail=True)).write(rec)  # dropped, not raised
