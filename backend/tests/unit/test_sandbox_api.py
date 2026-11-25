"""Mock e-Office sandbox API + assist API over HTTP (plan §11.3–§11.5; CLAUDE.md §2.4, §4).

Sign-in is simulated (header). The leakage sweep sends every golden question, every corpus
reference and a pre-send on every file as every sandbox officer, and checks every canonical ID
anywhere in the response against the independent access matrix.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.tools import CURRENT_UNCONFIRMED, STATUS_UNCONFIRMED
from app.auth.messages import DOCUMENT_NOT_AVAILABLE, FILE_NOT_AVAILABLE, RECEIPT_NOT_AVAILABLE
from app.config import get_settings
from app.eoffice_mock.models import BANNER
from app.identifiers.canonical import InvalidCanonicalIdError, lookup_keys
from app.main import create_app
from tests.unit.mock_access import CORPUS, MATRIX, rows

IDX = {r["canonical_id"]: r for r in rows("documents_index.csv")}
FILE_OF = {r["raw_reference"].removeprefix("File No."): r["id"] for r in IDX.values()}
GOLDEN = json.loads((CORPUS / "ground_truth" / "golden_questions.json").read_text("utf-8"))
SEED = json.loads((CORPUS / "eoffice" / "seed.json").read_text("utf-8"))
USERS = [p["user_id"] for p in SEED["profiles"] if p["login"]]
COMPUTER_NOS = [f["computer_no"] for f in SEED["files"]]
RECEIPT_NOS = [r["computer_no"] for r in SEED["receipts"]]
ID_RX = re.compile(r"AP-[A-Z]{2,6}\d{2}-[A-Z]+-[A-Z0-9-]+")


APP = create_app(get_settings().model_copy(update={"sandbox": True}))


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        yield c


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


def _doc_id(cid: str) -> str | None:
    """Runtime canonical ID (may carry a date tag / clause) → corpus doc id."""
    base = cid.split("#", 1)[0]
    try:
        keys = lookup_keys(base)
    except InvalidCanonicalIdError:
        return None
    hit = next((k for k in keys if k in IDX), None)
    return IDX[hit]["id"] if hit else None


def _named_docs(payload: Any) -> set[str]:
    """Every corpus document a response names, by canonical ID or by e-File number."""
    text = json.dumps(payload, ensure_ascii=False)
    out = {d for m in ID_RX.finditer(text) if (d := _doc_id(m.group(0)))}
    out |= {did for file_no, did in FILE_OF.items() if file_no and file_no in text}
    return out


# ---- sign-in, banner ----------------------------------------------------------------------


@pytest.mark.parametrize("hdr", [{}, _h("U99"), _h("POST-ASSISTANT-SECTION-OFFICER-ESTT-I")])
def test_no_valid_sign_in_is_refused_neutrally(client: TestClient, hdr: dict[str, str]) -> None:
    for method, path, body in (
        ("get", "/sandbox/me", None),
        ("get", "/sandbox/files", None),
        ("post", "/assist/search", {"query": "transfer"}),
        ("post", "/assist/presend", {"computer_no": "2894562"}),
    ):
        r = client.request(method.upper(), path, headers=hdr, json=body)
        assert r.status_code == 401 and r.json() == {"detail": "Not signed in."}, path


def test_every_response_is_marked_as_the_mock_sandbox(client: TestClient) -> None:
    r = client.get("/sandbox/profiles")
    assert r.headers["X-Mock-Sandbox"].startswith("synthetic")
    assert r.json()["banner"] == BANNER
    # posts without login excluded; M01 = the mock monitoring officer (sandbox.yaml, ADR-0035)
    assert [p["user_id"] for p in r.json()["profiles"]] == [*USERS, "M01"]
    # each officer's own search reach is shown at sign-in, nothing more (24 Nov 2026)
    assert all(p["search_scopes"] for p in r.json()["profiles"])
    assert set(r.json()["profiles"][0]) == {
        "user_id",
        "name",
        "post",
        "department",
        "section",
        "clearance",
        "search_scopes",
    }
    assert client.get("/healthz").headers["X-Mock-Sandbox"]


# ---- e-Office reach + clearance ---------------------------------------------------------


def _files(client: TestClient, uid: str) -> set[str]:
    return {f["computer_no"] for f in client.get("/sandbox/files", headers=_h(uid)).json()["files"]}


def test_file_lists_follow_reach_and_clearance(client: TestClient) -> None:
    u01 = _files(client, "U01")
    assert "2894562" in u01 and "1771342" in u01
    assert not u01 & {"2633187", "2601155", "2671408"}  # CONFIDENTIAL Estt.I, Vigilance
    assert {"2601155", "2633187"} <= _files(client, "U04")  # assigned files
    assert "2671408" not in _files(client, "U05")  # SECRET, Deputy Secretary is CONFIDENTIAL
    assert "2671408" in _files(client, "U06")
    assert not _files(client, "U03") & {"2894562", "2601155"}  # Works SO: Works files only


def test_file_list_never_exceeds_the_access_matrix(client: TestClient) -> None:
    by_cno = {f["computer_no"]: f["file_no"] for f in SEED["files"]}
    for uid in USERS:
        for cno in _files(client, uid):
            did = FILE_OF.get(by_cno[cno])
            assert did is None or MATRIX[(did, uid)], (uid, cno, did)


def test_unknown_and_unavailable_files_look_the_same(client: TestClient) -> None:
    hidden = client.get("/sandbox/files/2671408", headers=_h("U05"))
    unknown = client.get("/sandbox/files/9999999", headers=_h("U05"))
    assert (hidden.status_code, hidden.json()) == (unknown.status_code, unknown.json())
    assert hidden.status_code == 404
    p1 = client.post("/assist/presend", json={"computer_no": "2894562"}, headers=_h("U03"))
    p2 = client.post("/assist/presend", json={"computer_no": "9999999"}, headers=_h("U03"))
    assert (p1.status_code, p1.json()) == (p2.status_code, p2.json()) == (404, p1.json())


def test_file_inner_page(client: TestClient) -> None:
    page = client.get("/sandbox/files/2894562", headers=_h("U01")).json()
    assert page["banner"] == BANNER and page["file"]["file_no"] == "USD01-12/19/2026-ESTT.I"
    assert page["notes"] and page["notes"][0]["note_no"] == 1
    assert page["movements"] is not None


# ---- touchpoints through HTTP ----------------------------------------------------------


def test_tp15_advance_search_returns_file_numbers_in_scope(client: TestClient) -> None:
    r = client.post("/assist/search", json={"query": "that 2023 drain case"}, headers=_h("U03"))
    body = r.json()
    assert "USD01-WRKS0/18/2023-WORKS" in body["files"]
    assert not any("VIG" in f for f in body["files"])
    assert body["calibrated"] is False  # sandbox demo thresholds are labelled
    u05 = client.post("/assist/search", json={"query": "that 2023 drain case"}, headers=_h("U05"))
    assert "D23" not in _named_docs(u05.json())


def test_tp10_reference_respects_status_coverage(client: TestClient) -> None:
    r = client.post(
        "/assist/reference", json={"text": "G.O.Ms.No.88/2022 para 2(v)"}, headers=_h("U01")
    ).json()
    assert r["found"] and r["status"] == "superseded"  # 31/2025 is visible to the Estt.I SO
    assert r["by"] == "AP-FIN01-GOMS-31-2025" and r["current_version"] is None
    assert r["message"] == CURRENT_UNCONFIRMED  # can't see all of Finance: no "current" claim
    in_force = client.post(
        "/assist/reference", json={"text": "G.O.Ms.No.31/2025"}, headers=_h("U01")
    ).json()
    assert in_force["status"] is None and in_force["message"] == STATUS_UNCONFIRMED
    sec = client.post(
        "/assist/reference",
        json={"text": "G.O.Ms.No.14, Urban Services (Works) Department, Dt.18-03-2021"},
        headers=_h("U06"),
    ).json()
    assert sec["status"] == "superseded" and sec["current_version"] == "AP-USD01-GOMS-27-2024"
    none = client.post("/assist/reference", json={"text": "G.O.Ms.No.999/2025"}, headers=_h("U06"))
    assert none.json()["found"] is False and "records available to you" in none.json()["message"]


def test_tp11_presend_through_http(client: TestClient) -> None:
    r = client.post("/assist/presend", json={"computer_no": "2894562"}, headers=_h("U01")).json()
    assert r["outcome"] == "conflicts_found" and r["mock_rules"] is True
    assert {f["type"] for f in r["flags"]} == {"A", "C", "E", "F"}
    c = [f for f in r["flags"] if f["type"] == "C"]
    assert not c[0]["certain"] and "not verified as complete" in c[0]["explanation"]


@pytest.mark.parametrize(
    ("uid", "cno"), [("U01", "2633187"), ("U04", "2671408"), ("U05", "2671408")]
)
def test_assist_needs_clearance_for_the_file_not_just_e_office_reach(
    client: TestClient, uid: str, cno: str
) -> None:
    """Regression (found by the sweep, 4 Nov 2026): e-Office reach without clearance for the
    file's classification must look exactly like an unknown file on every assist endpoint."""
    for path, extra in (
        ("/assist/file-so-far", {}),
        ("/assist/presend", {}),
        ("/assist/dfa", {}),
        ("/assist/first-cut", {}),
        ("/assist/note-reference", {"text": "preliminary enquiry"}),
        ("/assist/draft", {"kind": "yellow_note", "body": "x", "request_id": "r"}),
    ):
        hidden = client.post(path, json={"computer_no": cno, **extra}, headers=_h(uid))
        unknown = client.post(path, json={"computer_no": "9999999", **extra}, headers=_h(uid))
        assert (hidden.status_code, hidden.json()) == (404, {"detail": FILE_NOT_AVAILABLE}), path
        assert (unknown.status_code, unknown.json()) == (hidden.status_code, hidden.json())


def test_tp08_file_so_far(client: TestClient) -> None:
    r = client.post("/assist/file-so-far", json={"computer_no": "2601155"}, headers=_h("U05"))
    body = r.json()
    assert [n["note_no"] for n in body["notes"]] == [1, 2, 3]  # D21; D22 is a scan, held
    assert body["chain"][-1] == "Secretary to Government" and body["last_direction"] == 3
    assert body["pending_documents"] == 1 and "waiting for text review" in body["pending_message"]
    assert "D23" not in _named_docs(body)  # the SECRET V&E report is never mentioned
    assert (
        client.post(
            "/assist/file-so-far", json={"computer_no": "2601155"}, headers=_h("U04")
        ).status_code
        == 200
    )  # assigned
    hidden = client.post("/assist/file-so-far", json={"computer_no": "2601155"}, headers=_h("U01"))
    unknown = client.post("/assist/file-so-far", json={"computer_no": "9999999"}, headers=_h("U01"))
    assert (hidden.status_code, hidden.json()) == (unknown.status_code, unknown.json())


def test_tp09_link_file_suggests_only_precedents_in_scope(client: TestClient) -> None:
    r = client.post("/assist/link-suggestions", json={"computer_no": "2899017"}, headers=_h("U03"))
    files = [s["file_no"] for s in r.json()["suggestions"]]
    assert set(files) == {"USD01-WRKS0/52/2024-WORKS", "USD01-WRKS0/18/2023-WORKS"}
    assert "USD01-WRKS0/30/2026-WORKS" not in files  # never the open file itself
    assert not {"D21", "D22", "D23"} & _named_docs(r.json())  # no Vigilance file for the Works SO
    link = client.post(
        "/assist/draft",
        json={
            "computer_no": "2899017",
            "kind": "suggested_reference",
            "body": "Link file USD01-WRKS0/52/2024-WORKS as a read-only reference.",
            "citations": ["AP-USD01-NOTE-USD01WRKS0-52-2024"],
            "request_id": r.json()["request_id"],
        },
        headers=_h("U03"),
    )
    assert link.json()["status"] == "draft" and link.json()["kind"] == "suggested_reference"
    hidden = client.post(
        "/assist/link-suggestions", json={"computer_no": "2899017"}, headers=_h("U01")
    )
    assert hidden.status_code == 404


def test_tp02_receipt_summary_and_validity(client: TestClient) -> None:
    memo = client.post(
        "/assist/receipt", json={"computer_no": "9100010", "as_of": "2025-05-21"}, headers=_h("U01")
    ).json()
    assert memo["document"]["doc_type"] == "Clarification" and len(memo["summary"]) == 2
    assert memo["cited"] == ["AP-FIN01-GOMS-31-2025"] and memo["flags"] == []  # in force: no flag
    go = client.post("/assist/receipt", json={"computer_no": "9100008"}, headers=_h("U01")).json()
    flags = {(f["type"], f["about"]) for f in go["flags"]}
    assert flags == {("F", "this order"), ("F", "cited order")}  # 1184/2025 and the 2024 circular
    assert all("the proposal is dated" not in f["explanation"] for f in go["flags"])
    hidden = client.post("/assist/receipt", json={"computer_no": "9100008"}, headers=_h("U03"))
    unknown = client.post("/assist/receipt", json={"computer_no": "9999999"}, headers=_h("U03"))
    assert (hidden.status_code, hidden.json()) == (unknown.status_code, unknown.json())
    assert hidden.status_code == 404


def test_tp03_put_in_a_file_never_forces_a_match(client: TestClient) -> None:
    r = client.post(
        "/assist/receipt", json={"computer_no": "9100010", "as_of": "2025-05-21"}, headers=_h("U01")
    ).json()["put_in"]
    assert r["suggestion"] == "new_file" and r["files"] == []  # a general clarification
    assert "USD01-12/44/2025-ESTT.I" in r["related_files"]  # related only (cites G.O.Ms.31/2025)


def test_receipt_inbox_follows_reach(client: TestClient) -> None:
    def inbox(uid: str) -> list[str]:
        rows = client.get("/sandbox/receipts", headers=_h(uid)).json()["receipts"]
        return [x["computer_no"] for x in rows]

    assert "9100010" in inbox("U01") and inbox("U03") == []
    page = client.get("/sandbox/receipts/9100010", headers=_h("U01")).json()
    assert page["banner"] == BANNER and page["receipt"]["receipt_no"] == "3/2025/ESTT.I"
    assert client.get("/sandbox/receipts/9100010", headers=_h("U03")).status_code == 404


def test_tp13_approval_brief_follows_each_officers_access(client: TestClient) -> None:
    sec = client.post("/assist/brief", json={"computer_no": "2894562"}, headers=_h("U06")).json()
    assert {f["type"] for f in sec["presend"]["flags"]} == {"A", "C", "E", "F"}
    assert sec["proposal"]["action"] == "transfer"
    assert sec["proposal"]["proposed_authority"] == "Deputy Secretary"
    assert sec["put_up"]["post"] == "Assistant Section Officer (Estt.I)"
    g88 = next(g for g in sec["governing"] if g["cited"] == "AP-FIN01-GOMS-88-2022")
    assert g88["status"] == "superseded" and g88["by"] == "AP-FIN01-GOMS-31-2025"
    assert g88["current_version"] is None  # never "current" without full coverage
    g104 = next(g for g in sec["governing"] if not g["found"])
    assert "records available to you" in g104["message"]
    sec_files = {p["file_no"] for p in sec["precedents"]}
    assert "USD01-12/58/2025-ESTT.I" in sec_files  # the CONFIDENTIAL 2025 case: Secretary may see
    so = client.post("/assist/brief", json={"computer_no": "2894562"}, headers=_h("U01")).json()
    assert "USD01-12/58/2025-ESTT.I" not in {p["file_no"] for p in so["precedents"]}
    hidden = client.post("/assist/brief", json={"computer_no": "2894562"}, headers=_h("U03"))
    assert hidden.status_code == 404


def test_drafts_only_and_audited_without_text(client: TestClient) -> None:
    body = "1. Draft: the request may be kept pending until the next general transfers."
    r = client.post(
        "/assist/draft",
        json={
            "computer_no": "2894562",
            "kind": "yellow_note",
            "body": body,
            "request_id": "req-test-1",
        },
        headers=_h("U01"),
    )
    assert r.status_code == 200 and r.json()["status"] == "draft"
    page = client.get("/sandbox/files/2894562", headers=_h("U01")).json()
    assert any(d["draft_id"] == r.json()["draft_id"] for d in page["drafts"])
    blocked = client.post(
        "/assist/draft",
        json={"computer_no": "2894562", "kind": "yellow_note", "body": "x", "request_id": "r2"},
        headers=_h("U03"),
    )
    assert blocked.status_code == 404
    events = APP.state.audit.events()
    assert any(e.action == "draft.create" and e.outcome == "ok" for e in events)
    dumped = json.dumps([e.model_dump(mode="json") for e in events], ensure_ascii=False)
    assert body not in dumped and "that 2023 drain case" not in dumped  # IDs only, never text


def test_permission_change_takes_effect_on_the_next_call(client: TestClient) -> None:
    adapter = APP.state.adapter
    q = {"query": "Sri K. Venkata Ramana Superintendent transfer"}
    assert "D20" in _named_docs(client.post("/assist/search", json=q, headers=_h("U02")).json())
    original = adapter._profiles["U02"]
    adapter._profiles["U02"] = original.model_copy(update={"clearance": "RESTRICTED"})
    try:
        after = client.post("/assist/search", json=q, headers=_h("U02")).json()
        assert "D20" not in _named_docs(after)
    finally:
        adapter._profiles["U02"] = original


# ---- leakage sweep (pass bar: zero) ------------------------------------------------------


def test_zero_disclosures_through_the_api(client: TestClient) -> None:
    disclosures: list[tuple[str, str, str]] = []
    checks = 0

    def check(uid: str, what: str, payload: Any) -> None:
        nonlocal checks
        checks += 1
        disclosures.extend((uid, what, d) for d in _named_docs(payload) if not MATRIX[(d, uid)])

    refs = [r["raw_reference"] for r in IDX.values() if not r["raw_reference"].startswith("File")]
    for uid in USERS:
        for q in GOLDEN:
            r = client.post("/assist/search", json={"query": q["question"]}, headers=_h(uid))
            check(uid, f"search {q['id']}", r.json())
        for ref in refs:
            r = client.post("/assist/reference", json={"text": ref}, headers=_h(uid))
            check(uid, f"reference {ref}", r.json())
            r = client.post("/assist/reference", json={"text": f"{ref} para 2(v)"}, headers=_h(uid))
            check(uid, f"reference {ref} para 2(v)", r.json())
        check(uid, "notices", client.get("/assist/notices", headers=_h(uid)).json())
        for rno in RECEIPT_NOS:
            r = client.post("/assist/receipt", json={"computer_no": rno}, headers=_h(uid))
            check(uid, f"receipt {rno}", r.json())
            p = client.get(f"/sandbox/receipts/{rno}", headers=_h(uid))
            check(uid, f"receipt page {rno}", p.json())
        for cno in COMPUTER_NOS:
            r = client.post("/assist/presend", json={"computer_no": cno}, headers=_h(uid))
            check(uid, f"presend {cno}", r.json())
            r = client.post("/assist/file-so-far", json={"computer_no": cno}, headers=_h(uid))
            fsf = r.json()
            for n in fsf.get("notes", []):  # the authorised note's own words, as on the file page
                n.pop("text", None)
            check(uid, f"file so far {cno}", fsf)
            r = client.post("/assist/link-suggestions", json={"computer_no": cno}, headers=_h(uid))
            check(uid, f"link suggestions {cno}", r.json())
            for ask in ("preliminary enquiry proposal", "transfer request spouse", "Note #1"):
                r = client.post(
                    "/assist/note-reference",
                    json={"computer_no": cno, "text": ask},
                    headers=_h(uid),
                )
                ref = r.json()
                for sg in ref.get("suggestions", []):  # the note's own words, as on the file page
                    sg.pop("text", None)
                check(uid, f"note reference {cno} {ask}", ref)
            r = client.post("/assist/first-cut", json={"computer_no": cno}, headers=_h(uid))
            cut = r.json()
            cut.pop("body", None)  # composed from the cited items below
            for fl in cut.get("flags", []):
                fl.pop("explanation", None)
            for pt in cut.get("points", []):
                pt.pop("text", None)  # a visible order's own paragraph
            for pr in cut.get("precedents", []):
                pr.pop("decision", None)  # a visible note's own paragraph
            check(uid, f"first-cut {cno}", cut)
            r = client.post("/assist/dfa", json={"computer_no": cno}, headers=_h(uid))
            dfa = r.json()
            dfa.pop("body", None)  # composed from the listed items and flags, checked below
            for fl in dfa.get("flags", []):
                fl.pop("explanation", None)  # the shared pre-send wording, checked via presend
            check(uid, f"dfa {cno}", dfa)
            r = client.post("/assist/brief", json={"computer_no": cno}, headers=_h(uid))
            brief = r.json()
            for ev in (brief.get("proposal") or {}).get("evidence", {}):
                brief["proposal"]["evidence"][ev] = ""  # the draft's own words, as on the page
            check(uid, f"brief {cno}", brief)
            p = client.get(f"/sandbox/files/{cno}", headers=_h(uid)).json()
            # Note text is the authorised document itself, shown as written (it may quote a file
            # number the officer cannot open — e.g. D20 cites the Vigilance file). Check what the
            # page itself names: the file, its correspondence and movements.
            for n in p.get("notes", []):
                n.pop("text", None)
            for d in p.get("drafts", []):
                d.pop("text", None)
            check(uid, f"file page {cno}", p)
    assert checks > 500
    assert disclosures == []


def test_held_scan_citation_is_uncertain_not_missing_through_http(client: TestClient) -> None:
    """Regression (checkpoint eval, 4 Nov 2026): the sandbox has no OCR, so the 2023 Works circular
    stays in review; the Works SO's pre-send check on the 2026 drain file must not say it is
    missing from his records. The held record is never named."""
    r = client.post("/assist/presend", json={"computer_no": "2899017"}, headers=_h("U03")).json()
    e = [f for f in r["flags"] if f["type"] == "E"]
    assert e and not any(f["certain"] for f in e)
    assert all("awaiting review" in f["explanation"] for f in e)
    assert r["awaiting_review"] and all(c.startswith("AP-USD01-") for c in r["awaiting_review"])
    assert "D13" not in str(r) and "_photo" not in str(r)
    # A cited order that does not exist at all is still flagged (softened while scans wait).
    t = client.post("/assist/presend", json={"computer_no": "2894562"}, headers=_h("U01")).json()
    assert any(f["type"] == "E" and "104" in f["cited"] for f in t["flags"])


def test_tp07_reference_to_a_previous_note_through_http(client: TestClient) -> None:
    """Touchpoint 7: the Vigilance SO asks for the earlier proposal; the suggestion is Note #1
    para 3 with the e-Office note ID, and nothing is written until the officer clicks."""
    ask = {"computer_no": "2601155", "text": "earlier proposal for a preliminary enquiry"}
    r = client.post(
        "/assist/note-reference", json={**ask, "as_of": "2025-07-21"}, headers=_h("U04")
    )
    body = r.json()
    top = body["suggestions"][0]
    assert (top["kind"], top["target_id"], top["note_no"], top["paragraph"]) == (
        "previous_note",
        "2601155-N1",
        1,
        3,
    )
    assert body["matching"].startswith("keyword stand-in") and body["calibrated"] is False
    assert "D23" not in _named_docs(body)
    files = client.get("/sandbox/files/2601155", headers=_h("U04")).json()
    assert not files.get("drafts")  # suggesting writes nothing
    made = client.post(
        "/assist/draft",
        json={
            "computer_no": "2601155",
            "kind": "suggested_reference",
            "body": f"Please see {top['insert_text']} ({top['target_id']}).",
            "citations": [top["target_id"], top["source"]],
            "request_id": body["request_id"],
        },
        headers=_h("U04"),
    ).json()
    assert made["status"] == "draft" and made["kind"] == "suggested_reference"
    # the Estt.I SO cannot reach the Vigilance file at all: same answer as an unknown file
    hidden = client.post("/assist/note-reference", json=ask, headers=_h("U01"))
    assert (hidden.status_code, hidden.json()) == (404, {"detail": FILE_NOT_AVAILABLE})


def test_tp10_local_reference_with_a_paragraph_through_http(client: TestClient) -> None:
    """Touchpoint 10: 88/2022 is superseded by 31/2025 from 12-05-2025; both paragraphs 2(v) are
    shown; 31/2025 is not called current without full coverage (owner rule, 3 Nov 2026)."""
    r = client.post(
        "/assist/reference", json={"text": "G.O.Ms.No.88/2022 para 2(v)"}, headers=_h("U01")
    ).json()
    assert (r["status"], r["by"], r["since"]) == (
        "superseded",
        "AP-FIN01-GOMS-31-2025",
        "2025-05-12",
    )
    assert r["cited_clause"]["clause_id"] == "AP-FIN01-GOMS-88-2022#para-2.v"
    assert r["successor_clause"]["clause_id"] == "AP-FIN01-GOMS-31-2025#para-2.v"
    assert "Spouse cases" in r["successor_clause"]["text"]
    assert r["current_version"] is None and r["successor_is_current"] is False
    assert "check it covers the same point" in r["clause_note"]


def test_tp14_dfa_preview_then_draft_only_on_click(client: TestClient) -> None:
    """Touchpoint 14: the Assistant Secretary's DFA preview lists 31/2025 in place of 88/2022,
    leaves out 104/2026, carries the open flags, and writes nothing until "Create DFA draft"."""

    def drafts() -> int:
        page = client.get("/sandbox/files/2894562", headers=_h("U02")).json()
        return len(page.get("drafts", []))

    before = drafts()
    r = client.post("/assist/dfa", json={"computer_no": "2894562"}, headers=_h("U02")).json()
    assert drafts() == before  # the preview writes nothing
    read = {i["canonical_id"]: i for i in r["read_list"]}
    assert read["AP-FIN01-GOMS-31-2025"]["in_place_of"] == ["AP-FIN01-GOMS-88-2022"]
    assert "AP-FIN01-GOMS-88-2022" not in read
    assert [x["cited"] for x in r["left_out"]] == ["AP-FIN01-GOMS-104-2026"]
    assert {f["type"] for f in r["flags"]} == {"A", "C", "E", "F"}
    assert r["abstract"].endswith("– Orders – Issued.")
    assert r["order_paragraphs"].startswith("not drafted")
    assert any("awaiting review" in c for c in r["caveats"])  # D09 / D11 are scans, not read
    made = client.post(
        "/assist/draft",
        json={
            "computer_no": "2894562",
            "kind": "dfa_draft",
            "body": r["body"],
            "citations": r["citations"],
            "request_id": r["request_id"],
        },
        headers=_h("U02"),
    ).json()
    assert made["kind"] == "dfa_draft" and made["status"] == "draft"
    assert drafts() == before + 1
    # The ASSISTANT has no such endpoint. Approving and issuing is the officer's own e-Office act,
    # simulated only in the sandbox (like confirming a Green Note) and only on a DFA another
    # officer put up to them (ADR-0045): never on the assistant's side.
    paths = APP.openapi()["paths"]
    words = {w for p in paths if p.startswith("/assist") for w in re.split(r"[/{}_-]+", p) if w}
    assert not words & {"sign", "send", "dispatch", "approve", "approvals", "issue"}
    officer_acts = [p for p in paths if re.search(r"approv|issue|sign|dispatch", p)]
    assert set(officer_acts) == {
        "/sandbox/files/{computer_no}/approvals/{draft_id}/issue",
        "/sandbox/files/{computer_no}/approvals/{draft_id}/return",
        # read-only: whom the officer holding the file may put a draft up to (25 Nov 2026)
        "/sandbox/files/{computer_no}/approver-options",
    }


def test_tp06_first_cut_then_yellow_note_only_on_click(client: TestClient) -> None:
    """Touchpoint 6: cited points for the Estt.I SO's spouse-ground note — 31/2025 (not 88/2022),
    its ban / ceiling / authority / spouse paragraphs, the earlier decisions set against the
    windows; nothing from the Vigilance files or the confidential 2025 rejection."""

    def drafts() -> int:
        page = client.get("/sandbox/files/2894562", headers=_h("U01")).json()
        return len(page.get("drafts", []))

    before = drafts()
    r = client.post("/assist/first-cut", json={"computer_no": "2894562"}, headers=_h("U01"))
    cut = r.json()
    assert drafts() == before  # the preview writes nothing
    orders = {o["canonical_id"] for o in cut["orders"]}
    assert "AP-FIN01-GOMS-31-2025" in orders and "AP-FIN01-GOMS-88-2022" not in orders
    points = {p["clause_id"] for p in cut["points"]}
    assert {f"AP-FIN01-GOMS-31-2025#para-{x}" for x in ("2.i", "2.iv", "2.v", "2.viii", "3")} <= (
        points
    )
    decided = {p["source"]: p["in_window"] for p in cut["precedents"]}
    assert decided == {
        "AP-USD01-NOTE-USD0112-31-2022": True,
        "AP-USD01-NOTE-USD0112-77-2023": False,
        "AP-USD01-NOTE-USD0112-44-2025": True,
    }
    assert {f["type"] for f in cut["flags"]} == {"A", "C", "E", "F"}
    assert cut["note_text"].startswith("not drafted")
    for hidden in ("VIG", "AP-USD01-NOTE-USD0112-58-2025"):  # Vigilance files; D20
        assert hidden not in json.dumps(cut)
    made = client.post(
        "/assist/draft",
        json={
            "computer_no": "2894562",
            "kind": "yellow_note",
            "body": cut["body"],
            "citations": cut["citations"],
            "request_id": cut["request_id"],
        },
        headers=_h("U01"),
    ).json()
    assert made["kind"] == "yellow_note" and made["status"] == "draft"
    assert drafts() == before + 1


# ---- citation highlights + document preview / download (ADR-0014, ADR-0015) --------------------

UNKNOWN_DOC = "AP-FIN01-GOMS-9999-2022"


def _runtime() -> Any:
    run = APP.state.assist_runtime
    return run() if callable(run) else run


def _row(cid: str) -> dict[str, str]:
    did = _doc_id(cid)
    assert did is not None, cid
    return next(r for r in IDX.values() if r["id"] == did)


def _notes(client: TestClient, cno: str, uid: str) -> list[dict[str, str]]:
    page = client.get(f"/sandbox/files/{cno}", headers=_h(uid)).json()
    return [{"note_id": n["note_id"], "text": n["text"] or ""} for n in page["notes"]]


def test_highlights_mark_each_cited_order_with_its_state(client: TestClient) -> None:
    notes = _notes(client, "2894562", "U01")
    r = client.post(
        "/assist/highlights", json={"computer_no": "2894562", "notes": notes}, headers=_h("U01")
    )
    assert r.status_code == 200
    by_id = {n["note_id"]: n["highlights"] for n in r.json()["notes"]}
    text = {n["note_id"]: n["text"] for n in notes}
    hs = [(nid, h) for nid, hl in by_id.items() for h in hl]
    for nid, h in hs:  # offsets point at the citation in the text the officer sees
        assert re.sub(r"\s+", " ", text[nid][h["start"] : h["end"]]) == h["raw"]
    states = {h["raw"].split(",")[0]: h for _, h in hs}
    old = states["G.O.Ms.No.88"]  # superseded by 31/2025: a potential conflict, openable
    assert old["state"] == "conflict" and old["canonical_id"] == "AP-FIN01-GOMS-88-2022"
    assert [f["type"] for f in old["flags"]] == ["A"]
    held = states["G.O.Ms.No.104"]  # the scan in review: not found, uncertain, never linked
    assert held["state"] == "not_found" and held["canonical_id"] is None
    assert held["flags"] and not any(f["certain"] for f in held["flags"])


def test_highlights_on_a_file_out_of_reach_answer_like_an_unknown_file(
    client: TestClient,
) -> None:
    body = {"notes": [{"note_id": "n1", "text": "G.O.Ms.No.88, Finance Department, Dt.03-06-2022"}]}
    hidden = client.post(
        "/assist/highlights", json={"computer_no": "2894562", **body}, headers=_h("U03")
    )
    unknown = client.post(
        "/assist/highlights", json={"computer_no": "999999", **body}, headers=_h("U03")
    )
    assert hidden.status_code == unknown.status_code == 404
    assert hidden.json() == unknown.json() == {"detail": FILE_NOT_AVAILABLE}


def test_preview_and_download_serve_the_exact_stored_file(client: TestClient) -> None:
    cid = "AP-FIN01-GOMS-88-2022"
    on_disk = (CORPUS / _row(cid)["file"]).read_bytes()
    info = client.get(f"/assist/documents/{cid}", headers=_h("U01")).json()
    assert info["previewable"] and info["media_type"] == "application/pdf"
    assert info["filename"] == f"{cid}.pdf" and info["version"] == _runtime().sources[cid]
    for kind, disposition in (("preview", "inline"), ("download", "attachment")):
        r = client.get(f"/assist/documents/{cid}/{kind}", headers=_h("U01"))
        assert r.status_code == 200 and r.content == on_disk  # the very bytes ingested
        assert r.headers["content-disposition"] == f'{disposition}; filename="{cid}.pdf"'
        assert r.headers["cache-control"] == "private, no-store"
        assert r.headers["x-document-version"] == info["version"]


def test_office_files_download_but_are_not_shown_inline(client: TestClient) -> None:
    run = _runtime()
    cid = next(
        c for c in run.sources if run.documents.get(run.sources[c]).media_type.endswith("document")
    )
    uid = next(u for u in USERS if MATRIX[(_row(cid)["id"], u)])
    assert not client.get(f"/assist/documents/{cid}", headers=_h(uid)).json()["previewable"]
    assert client.get(f"/assist/documents/{cid}/preview", headers=_h(uid)).status_code == 415
    r = client.get(f"/assist/documents/{cid}/download", headers=_h(uid))
    assert r.status_code == 200 and r.content == (CORPUS / _row(cid)["file"]).read_bytes()


def test_a_hidden_document_answers_exactly_like_an_unknown_one(client: TestClient) -> None:
    pairs = [
        (cid, uid)
        for cid in _runtime().sources
        for uid in USERS
        if not MATRIX[(_row(cid)["id"], uid)]
    ]
    assert len(pairs) > 20
    for cid, uid in pairs:
        for suffix in ("", "/preview", "/download"):
            got = client.get(f"/assist/documents/{cid}{suffix}", headers=_h(uid))
            ref = client.get(f"/assist/documents/{UNKNOWN_DOC}{suffix}", headers=_h(uid))
            assert got.status_code == ref.status_code == 404, (cid, uid, suffix)
            assert got.content == ref.content, (cid, uid, suffix)
            assert "x-document-version" not in got.headers


def test_every_view_and_download_is_audited_with_ids_only(client: TestClient) -> None:
    cid = "AP-FIN01-GOMS-88-2022"
    hidden, outsider = next(
        (c, u) for c in _runtime().sources for u in USERS if not MATRIX[(_row(c)["id"], u)]
    )
    before = len(APP.state.audit.events())
    client.get(f"/assist/documents/{cid}/preview", headers=_h("U01"))
    client.get(f"/assist/documents/{cid}/download", headers=_h("U01"))
    client.get(f"/assist/documents/{hidden}/download", headers=_h(outsider))
    new = APP.state.audit.events()[before:]
    got = [(e.action, e.outcome, e.user_id) for e in new]
    assert got == [
        ("assist.document.preview", "ok", "U01"),
        ("assist.document.download", "ok", "U01"),
        ("assist.document.download", "not_available", outsider),
    ]
    assert new[0].ids == (cid, _runtime().sources[cid])
    assert new[2].ids == ()  # a denied request records nothing about the document
    dumped = json.dumps([e.model_dump(mode="json") for e in new], ensure_ascii=False)
    assert "General Transfers" not in dumped and "%PDF" not in dumped


def test_zero_disclosures_through_highlights_and_documents(client: TestClient) -> None:
    """Leakage matrix, two new paths (ADR-0014 rule 6): a crafted note citing every order in the
    corpus, and every stored document requested by every officer."""
    disclosures: list[tuple[str, str, str]] = []
    refs = [r["raw_reference"] for r in IDX.values() if not r["raw_reference"].startswith("File")]
    crafted = "\n".join(f"{i}. As per {ref}." for i, ref in enumerate(refs, 1))
    for uid in USERS:
        for cno in COMPUTER_NOS:
            r = client.post(
                "/assist/highlights",
                json={"computer_no": cno, "notes": [{"note_id": "x", "text": crafted}]},
                headers=_h(uid),
            )
            if r.status_code != 200:
                continue
            for h in r.json()["notes"][0]["highlights"]:
                linked = h["canonical_id"]
                if linked and not MATRIX[(_row(linked)["id"], uid)]:
                    disclosures.append((uid, f"highlight link {cno}", linked))
                for f in h["flags"]:
                    for e in f["evidence_ids"]:
                        if (d := _doc_id(e)) and not MATRIX[(d, uid)]:
                            disclosures.append((uid, f"highlight evidence {cno}", e))
                    disclosures.extend(
                        (uid, f"highlight flag {cno}", d)
                        for d in _named_docs({"c": f["cited"], "e": f["explanation"]})
                        if not MATRIX[(d, uid)]
                    )
        for cid in _runtime().sources:
            for suffix in ("", "/preview", "/download"):
                got = client.get(f"/assist/documents/{cid}{suffix}", headers=_h(uid))
                if got.status_code in (200, 415) and not MATRIX[(_row(cid)["id"], uid)]:
                    disclosures.append((uid, f"document{suffix}", cid))
    assert disclosures == []


def test_a_hidden_order_cited_in_a_note_reads_like_one_that_does_not_exist(
    client: TestClient,
) -> None:
    """Regression (OPP-19, 10 Nov 2026): the not-found flag named the order by the ID resolved
    from the note, which looked like a record we hold. Now only the note's own words are used."""

    def ask(raw: str) -> str:
        body = {"computer_no": "2899017", "notes": [{"note_id": "n", "text": f"1. As per {raw}."}]}
        r = client.post("/assist/highlights", json=body, headers=_h("U03")).json()
        r.pop("request_id")
        return json.dumps(r).replace(raw, "<cited>")

    hidden = ask("Standing Order No.2/2020")  # D11: DENY for U03 (access matrix)
    assert hidden == ask("Standing Order No.7/2020")  # no such order
    assert "AP-USD01-SO-2-2020" not in hidden


def test_unavailable_answers_guide_the_officer_without_revealing_existence(
    client: TestClient,
) -> None:
    """ADR-0016 (owner, 11 Nov 2026): one message for hidden and non-existent records, which
    points the officer to the competent authority in e-Office for access or approval."""
    hidden_doc, outsider = next(
        (c, u) for c in _runtime().sources for u in USERS if not MATRIX[(_row(c)["id"], u)]
    )
    cases = [
        ("/sandbox/files/2894562", "/sandbox/files/999999", "U03", FILE_NOT_AVAILABLE),
        (
            f"/assist/documents/{hidden_doc}/preview",
            f"/assist/documents/{UNKNOWN_DOC}/preview",
            outsider,
            DOCUMENT_NOT_AVAILABLE,
        ),
    ]
    for hidden, unknown, uid, msg in cases:
        a = client.get(hidden, headers=_h(uid))
        b = client.get(unknown, headers=_h(uid))
        assert a.status_code == b.status_code == 404
        assert a.content == b.content and a.json() == {"detail": msg}
        assert "competent authority" in msg and "e-Office" in msg
        for leak in ("restricted", "not authorised", "classified", "confidential", "secret"):
            assert leak not in msg.lower()
    assert RECEIPT_NOT_AVAILABLE.startswith("This receipt isn't available to you.")
