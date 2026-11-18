"""Institutional memory grows only by official acts (ADR-0045), and an interrupted draft comes back
(ADR-0046). Each test module builds its own sandbox: issuing orders changes what is in force."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.runtime import AssistRuntime
from app.config import get_settings
from app.main import create_app


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


@pytest.fixture(scope="module")
def c() -> Iterator[TestClient]:
    app = create_app(get_settings().model_copy(update={"sandbox": True}))
    with TestClient(app) as client:
        client.get("/assist/notices", headers=_h("U01"))  # builds the runtime
        yield client


def _run(c: TestClient) -> AssistRuntime:
    run = c.app.state.assist_runtime()  # type: ignore[attr-defined]
    assert run is not None
    return run  # type: ignore[no-any-return]


SUBJECT = "Establishment – Sri P. Suresh, Junior Assistant – Request for transfer on spouse grounds"
LETTER = (
    b"From: Sri P. Suresh, Junior Assistant, Regional Office, Kurnool\n"
    b"Sub: Request for transfer on spouse grounds\n"
    b"I request transfer to Regional Office, Anantapur, where my spouse works.\n"
)


def _new_file(c: TestClient, refs: list[str] | None = None) -> dict[str, Any]:
    body = {"subject": SUBJECT, "previous_references": refs or []}
    r = c.post("/sandbox/files", json=body, headers=_h("U01"))
    assert r.status_code == 200, r.text
    return r.json()["file"]  # type: ignore[no-any-return]


def _attach(c: TestClient, cno: str, name: str, data: bytes, uid: str = "U01") -> Any:
    return c.post(
        f"/sandbox/files/{cno}/attachments",
        params={"name": name},
        content=data,
        headers={**_h(uid), "content-type": "application/octet-stream"},
    )


def _records(c: TestClient, cno: str, uid: str = "U01") -> Any:
    return c.get(f"/assist/files/{cno}/records", headers=_h(uid))


def _sandbox_ids(run: AssistRuntime) -> set[str]:
    return {
        r.canonical_id
        for (uri, _), r in run.stores.results.items()
        if uri.startswith("sandbox://") and r.canonical_id
    }


# ---- stage 1: the file's particulars and the papers attached ----------------------------------


def test_a_new_file_enters_with_its_particulars_and_links_to_its_previous_references(
    c: TestClient,
) -> None:
    f = _new_file(c, ["USD01-12/31/2022-ESTT.I"])
    rec = _records(c, f["computer_no"]).json()
    kinds = {x["doc_type"]: x for x in rec["records"]}
    assert "File record" in kinds and kinds["File record"]["last_event"] == "file_created"
    assert kinds["File record"]["subject"] == SUBJECT  # the subject alone, nothing after it
    cid = kinds["File record"]["canonical_id"]
    assert cid.startswith("AP-USD01-FILE-")
    # the previous reference becomes a graph link to that file's papers
    res = [r for (u, _), r in _run(c).stores.results.items() if r.canonical_id == cid]
    assert any("CITES→AP-USD01-NOTE-USD0112-31-2022" in e for e in res[-1].edges_added)


def test_an_attached_letter_is_read_and_filed_under_the_file_once(c: TestClient) -> None:
    f = _new_file(c)
    cno = f["computer_no"]
    assert _attach(c, cno, "request letter.txt", LETTER).status_code == 200
    assert _attach(c, cno, "same-letter-again.txt", LETTER).status_code == 200  # same bytes
    recs = [x for x in _records(c, cno).json()["records"] if x["doc_type"] == "Annexure"]
    assert len(recs) == 1 and recs[0]["last_event"] == "attachment_added"  # one record, not two
    page = c.get(f"/sandbox/files/{cno}", headers=_h("U01")).json()
    assert [a["filename"] for a in page["attachments"]] == [
        "request_letter.txt",
        "same-letter-again.txt",
    ]


def test_a_scan_waits_for_ocr_review_and_is_not_searchable_meanwhile(c: TestClient) -> None:
    f = _new_file(c)
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
        b"\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    assert _attach(c, f["computer_no"], "scan.png", png).status_code == 200
    rec = _records(c, f["computer_no"]).json()
    assert rec["waiting"] == [{"filename": "scan.png", "waiting_for": ["OCR review"]}]
    assert not [x for x in rec["records"] if x["doc_type"] == "Annexure"]


def test_attaching_is_checked_like_every_file_action(c: TestClient) -> None:
    f = _new_file(c)
    cno = f["computer_no"]
    assert _attach(c, cno, "virus.exe", b"MZ").status_code == 422
    assert _attach(c, cno, "empty.txt", b"").status_code == 422
    assert _attach(c, cno, "x.txt", LETTER, uid="U03").status_code == 404  # cannot open the file
    assert _attach(c, "9999999", "x.txt", LETTER).status_code == 404
    big = b"x" * (get_settings().upload_max_bytes + 1)
    assert _attach(c, cno, "big.txt", big).status_code == 413
    assert _records(c, cno, uid="U03").status_code == 404
    # other routes keep the small limit
    r = c.post("/sandbox/files", content=b"x" * 2_000_000, headers=_h("U01"))
    assert r.status_code == 413


# ---- stage 2: confirmed notes and issued orders; drafts never ------------------------------------


def _yellow(c: TestClient, cno: str, text: str) -> str:
    body = {
        "computer_no": cno,
        "kind": "yellow_note",
        "body": text,
        "citations": [],
        "request_id": "t",
    }
    return c.post("/assist/draft", json=body, headers=_h("U01")).json()["draft_id"]  # type: ignore[no-any-return]


def test_a_saved_draft_never_enters_but_a_confirmed_note_does_with_its_versions(
    c: TestClient,
) -> None:
    run = _run(c)
    f = _new_file(c)
    cno = f["computer_no"]
    before = _sandbox_ids(run)
    d1 = _yellow(c, cno, "1. The individual requests transfer on spouse grounds.")
    c.post(f"/sandbox/files/{cno}/drafts/{d1}/save", json={"text": "1. Edited."}, headers=_h("U01"))
    c.get("/assist/notices", headers=_h("U01"))  # any sync
    assert _sandbox_ids(run) - before <= {x for x in _sandbox_ids(run) if "-FILE-" in x}
    assert not [x for x in _records(c, cno).json()["records"] if x["doc_type"] == "Noting"]

    assert c.post(f"/sandbox/files/{cno}/drafts/{d1}/confirm", headers=_h("U01")).status_code == 200
    d2 = _yellow(c, cno, "2. Approved.")
    assert c.post(f"/sandbox/files/{cno}/drafts/{d2}/confirm", headers=_h("U01")).status_code == 200
    notes = [x for x in _records(c, cno).json()["records"] if x["doc_type"] == "Noting"]
    assert len(notes) == 1 and notes[0]["versions"] == 2  # one note sheet, two versions kept
    info = c.get(f"/assist/documents/{notes[0]['canonical_id']}", headers=_h("U01")).json()
    assert [h["event"] for h in info["history"]] == ["note_confirmed", "note_confirmed"]
    assert info["standing"] == "not_an_order"


def _dfa(c: TestClient, cno: str, extra: str = "") -> str:
    prep = c.post(
        "/assist/draft/prepare",
        json={
            "computer_no": cno,
            "format_id": "go_rt",
            "inputs": {
                "facts": "The individual requested transfer on spouse grounds." + extra,
                "proposal": "Government hereby permit the transfer of the individual.",
                "signatory": "SECRETARY TO GOVERNMENT",
                "addressees": "The individual",
                "copy_to": "The Regional Office",
            },
        },
        headers=_h("U01"),
    ).json()
    body = {
        "computer_no": cno,
        "kind": "dfa_draft",
        "body": prep["draft"]["text"],
        "citations": prep["draft"]["citations"],
        "request_id": prep["request_id"],
    }
    return c.post("/assist/draft", json=body, headers=_h("U01")).json()["draft_id"]  # type: ignore[no-any-return]


def test_an_order_enters_only_when_another_officer_approves_and_issues_it(c: TestClient) -> None:
    run = _run(c)
    f = _new_file(c)
    cno = f["computer_no"]
    d = _dfa(c, cno)
    before = _sandbox_ids(run)
    assert c.post(f"/sandbox/files/{cno}/drafts/{d}/submit", headers=_h("U01")).status_code == 200
    assert _sandbox_ids(run) == before  # put up is still a draft
    # the author cannot approve their own draft; an officer who is no approver cannot either
    assert c.post(f"/sandbox/files/{cno}/approvals/{d}/issue", headers=_h("U01")).status_code == 404
    page = c.get(f"/sandbox/files/{cno}", headers=_h("U02")).json()
    assert [x["draft_id"] for x in page["awaiting_approval"]] == [d]
    r = c.post(f"/sandbox/files/{cno}/approvals/{d}/issue", headers=_h("U02"))
    assert r.status_code == 200 and r.json()["issued_as"].startswith("G.O.Rt.No.90")
    orders = [x for x in _records(c, cno).json()["records"] if x["doc_type"] == "Government Order"]
    assert len(orders) == 1 and orders[0]["standing"] == "in_force"
    assert orders[0]["canonical_id"].startswith("AP-USD01-GORT-90")
    assert orders[0]["last_event"] == "draft_dispatched"
    # issued once: a second click finds nothing to issue
    assert c.post(f"/sandbox/files/{cno}/approvals/{d}/issue", headers=_h("U02")).status_code == 404
    # an officer who cannot see this department's records never learns the order exists
    assert (
        c.get(f"/assist/documents/{orders[0]['canonical_id']}", headers=_h("U07")).status_code
        == 404
    )


def test_a_draft_with_gaps_or_no_number_line_is_not_put_up(c: TestClient) -> None:
    f = _new_file(c)
    cno = f["computer_no"]
    body = {
        "computer_no": cno,
        "kind": "dfa_draft",
        "body": "ORDER: [What Government now order.]",
        "citations": [],
        "request_id": "t",
    }
    d = c.post("/assist/draft", json=body, headers=_h("U01")).json()["draft_id"]
    r = c.post(f"/sandbox/files/{cno}/drafts/{d}/submit", headers=_h("U01"))
    assert r.status_code == 409 and "gap" in r.json()["detail"]


@pytest.fixture()
def fresh() -> Iterator[TestClient]:
    """A sandbox of its own: files made by other tests are newer precedents on the same subject."""
    app = create_app(get_settings().model_copy(update={"sandbox": True}))
    with TestClient(app) as client:
        client.get("/assist/notices", headers=_h("U01"))
        yield client


def test_an_issued_order_that_supersedes_makes_the_old_one_history(fresh: TestClient) -> None:
    c = fresh
    f = _new_file(c)
    cno = f["computer_no"]

    # read G.O.Ms.No.31 and supersede it explicitly, naming its place in the Read list
    def prepare(facts: str) -> Any:
        return c.post(
            "/assist/draft/prepare",
            json={
                "computer_no": cno,
                "format_id": "go_ms",
                "add_references": ["AP-FIN01-GOMS-31-2025"],
                "inputs": {
                    "facts": facts,
                    "proposal": "Government hereby issue the revised guidelines annexed.",
                    "signatory": "SECRETARY TO GOVERNMENT",
                    "addressees": "All Departments",
                    "copy_to": "The Finance Department",
                },
            },
            headers=_h("U01"),
        ).json()

    first = prepare("Revised guidelines are issued.")
    at = [i["canonical_id"] for i in first["read_list"]].index("AP-FIN01-GOMS-31-2025") + 1
    ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(at, f"{at}th")
    prep = prepare(
        f"In supersession of the orders issued in the reference {ordinal} read above, "
        "revised guidelines are issued."
    )
    text = prep["draft"]["text"]
    assert f"{at}. G.O.Ms.No.31" in text
    body = {
        "computer_no": cno,
        "kind": "dfa_draft",
        "body": text,
        "citations": prep["draft"]["citations"],
        "request_id": prep["request_id"],
    }
    d = c.post("/assist/draft", json=body, headers=_h("U01")).json()["draft_id"]
    assert c.post(f"/sandbox/files/{cno}/drafts/{d}/submit", headers=_h("U01")).status_code == 200
    assert c.post(f"/sandbox/files/{cno}/approvals/{d}/issue", headers=_h("U02")).status_code == 200
    new = next(
        x["canonical_id"]
        for x in _records(c, cno).json()["records"]
        if x["doc_type"] == "Government Order"
    )
    old = c.get("/assist/documents/AP-FIN01-GOMS-31-2025", headers=_h("U01")).json()
    assert old["standing"] == "superseded" and old["use_instead"] == new
    # an earlier decision that rested on the old order is quoted as history, never as practice
    note = c.post(
        "/assist/draft/prepare",
        json={"format_id": "note_proposal", "inputs": {"subject": SUBJECT + " – Reg."}},
        headers=_h("U01"),
    ).json()
    quoted = [p for p in note["draft"]["parts"] if p["key"] == "precedent"]
    old_chain = {"AP-FIN01-GOMS-88-2022", "AP-FIN01-GOMS-31-2025"}
    rested = [p for p in quoted if old_chain & set(p["refs"])]
    assert rested and all("since superseded" in p["text"] for p in rested)
    assert all(new in p["refs"] for p in rested)  # and says what applies now: the new order


def test_an_undecided_proposal_is_never_quoted_as_an_earlier_decision(c: TestClient) -> None:
    """USD01-12/19/2026-ESTT.I ends with a proposal put up ("…may kindly approve…"), not a
    decision: it must not be quoted as one."""
    r = c.post(
        "/assist/draft/prepare",
        json={
            "format_id": "note_proposal",
            "inputs": {
                "subject": "Establishment – Junior Assistant – Request for transfer on spouse "
                "grounds – Reg."
            },
        },
        headers=_h("U01"),
    ).json()
    quoted = [p["text"] for p in r["draft"]["parts"] if p["key"] == "precedent"]
    assert quoted and not [t for t in quoted if "USD01-12/19/2026" in t]


# ---- ADR-0046: an interrupted draft comes back ---------------------------------------------------

WS = {
    "format_id": "go_ms",
    "inputs": {"subject": SUBJECT, "facts": "Facts typed before the power cut."},
    "added": ["AP-FIN01-GOMS-31-2025"],
    "prepared": True,
    "text": "DRAFT — edited text",
}


def test_the_workspace_comes_back_exactly_and_only_to_its_officer(c: TestClient) -> None:
    f = _new_file(c)
    cno = f["computer_no"]
    r = c.post(
        "/assist/draft/workspace", json={"computer_no": cno, "workspace": WS}, headers=_h("U01")
    )
    assert r.status_code == 200 and r.json()["saved_at"]
    got = c.get("/assist/draft/workspace", params={"computer_no": cno}, headers=_h("U01")).json()
    assert got["workspace"]["text"] == WS["text"] and got["workspace"]["added"] == WS["added"]
    assert got["workspace"]["inputs"]["facts"] == "Facts typed before the power cut."
    # another officer who can open the file gets nothing of it; one who cannot gets the 404
    other = c.get("/assist/draft/workspace", params={"computer_no": cno}, headers=_h("U02"))
    assert other.status_code == 200 and other.json()["workspace"] is None
    hidden = c.get("/assist/draft/workspace", params={"computer_no": cno}, headers=_h("U03"))
    assert hidden.status_code == 404
    assert (
        c.post(
            "/assist/draft/workspace", json={"computer_no": cno, "workspace": WS}, headers=_h("U03")
        ).status_code
        == 404
    )
    # a new matter has its own workspace
    c.post(
        "/assist/draft/workspace",
        json={"workspace": {**WS, "text": "new matter"}},
        headers=_h("U01"),
    )
    assert (
        c.get("/assist/draft/workspace", headers=_h("U01")).json()["workspace"]["text"]
        == "new matter"
    )
    assert (
        c.get("/assist/draft/workspace", params={"computer_no": cno}, headers=_h("U01")).json()[
            "workspace"
        ]["text"]
        == WS["text"]
    )
    # saving the draft into the file clears that file's workspace
    _yellow(c, cno, "1. Saved into the file.")
    assert (
        c.get("/assist/draft/workspace", params={"computer_no": cno}, headers=_h("U01")).json()[
            "workspace"
        ]
        is None
    )
    # start over
    assert c.post("/assist/draft/workspace/discard", json={}, headers=_h("U01")).json()["discarded"]
    assert c.get("/assist/draft/workspace", headers=_h("U01")).json()["workspace"] is None


def test_the_workspace_takes_only_what_the_screen_holds(c: TestClient) -> None:
    for bad in (
        {**WS, "format_id": "../x"},
        {**WS, "added": ["<script>"]},
        {**WS, "text": "x" * 40_001},
        {**WS, "extra": 1},
    ):
        r = c.post("/assist/draft/workspace", json={"workspace": bad}, headers=_h("U01"))
        assert r.status_code == 422, bad
    assert c.get("/assist/draft/workspace").status_code == 401
    ev = [e for e in c.app.state.audit.events() if e.action.startswith("assist.draft.workspace")]  # type: ignore[attr-defined]
    assert all("power cut" not in " ".join(e.ids) + (e.detail or "") for e in ev)  # never text


def test_ask_finds_a_new_record_only_for_officers_who_may_see_it(c: TestClient) -> None:
    """Ask AI (any screen): a paper attached today is found by those who may see the file, and
    for anyone else the answer is the same as for words that are in no record at all."""
    f = _new_file(c)
    letter = b"Sub: Request regarding the Zephyrine canal culvert repairs at Kurnool.\n"
    assert _attach(c, f["computer_no"], "culvert.txt", letter).status_code == 200

    def ask(uid: str, q: str) -> dict[str, Any]:
        r = c.post("/assist/chat", json={"message": q}, headers=_h(uid))
        assert r.status_code == 200
        return r.json()  # type: ignore[no-any-return]

    mine = ask("U01", "Zephyrine canal culvert repairs")
    assert any("-ANX-" in d for d in mine["documents"])
    new = [d for d in mine["documents"] if "-ANX-" in d]
    other = ask("U03", "Zephyrine canal culvert repairs")
    assert not set(new) & set(other["documents"])
    for d in other["documents"]:  # anything U03 is shown is a record U03 may open
        assert c.get(f"/assist/documents/{d}", headers=_h("U03")).status_code == 200
    for d in new:  # and the new paper is "not available" to U03, like any unknown record
        hidden = c.get(f"/assist/documents/{d}", headers=_h("U03"))
        missing = c.get("/assist/documents/AP-USD01-ANX-USD0112-999-2026", headers=_h("U03"))
        assert hidden.status_code == missing.status_code == 404
        assert hidden.json()["detail"] == missing.json()["detail"]
