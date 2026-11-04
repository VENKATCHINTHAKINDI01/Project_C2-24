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

from app.agents.tools import STATUS_UNCONFIRMED
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
    assert [p["user_id"] for p in r.json()["profiles"]] == USERS  # posts without login excluded
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
    assert r["found"] and r["message"] == STATUS_UNCONFIRMED  # Estt.I SO can't see all of Finance
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
        for cno in COMPUTER_NOS:
            r = client.post("/assist/presend", json={"computer_no": cno}, headers=_h(uid))
            check(uid, f"presend {cno}", r.json())
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
