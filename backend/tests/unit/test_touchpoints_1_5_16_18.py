"""Extended touchpoints 1, 5, 16, 18 (plan §11.5; ADR-0038): diary pre-fill from the letter,
previous references when creating a file, closing remarks and the closed file joining the
precedent index, and scanned old notings becoming searchable after OCR review — each within the
officer's access, with the same 404 for hidden and unknown."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.identifiers.resolver import load_departments
from app.ingestion.diarise import prefill
from app.main import create_app

ONTOLOGY = get_settings().ontology_dir


def _client() -> TestClient:
    return TestClient(create_app(get_settings().model_copy(update={"sandbox": True})))


@pytest.fixture()
def client() -> Iterator[TestClient]:  # fresh sandbox each test: these change sandbox state
    with _client() as c:
        yield c


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


LETTER = """GOVERNMENT OF ANDHRA PRADESH
ABSTRACT
Public Services – Human Resources – General Transfers of Employees for the year 2022 –
Guidelines – Orders – Issued.
FINANCE (HR.I-PLG. & POLICY) DEPARTMENT
G.O.Ms.No.88 Dated: 03-06-2022
Read the following:
1. G.O.Ms.No.62, Finance (HR.I-Plg. & Policy) Department, Dt.14-06-2019.
ORDER:
1. The Government hereby issue the following guidelines.
(BY ORDER AND IN THE NAME OF THE GOVERNOR OF ANDHRA PRADESH)
K. SATYANARAYANA
PRINCIPAL SECRETARY TO GOVERNMENT
To
All Departments of Secretariat.
"""


def test_prefill_reads_only_what_the_letter_says() -> None:
    p = prefill(LETTER, load_departments(ONTOLOGY / "departments.yaml"))
    assert (p.letter_ref.value, p.letter_date.value) == ("G.O.Ms.No.88", "2022-06-03")
    assert p.sender.value == "Principal Secretary To Government, Finance Department"
    assert p.main_category.value == "Government Order" and p.missing == ()
    assert p.subject.value is not None and p.subject.value.startswith("Public Services")
    assert p.letter_ref.read_from == "G.O.Ms.No.88 Dated: 03-06-2022"
    bare = prefill(
        "A note with no reference at all.", load_departments(ONTOLOGY / "departments.yaml")
    )
    assert bare.letter_ref.value is None and "letter_ref" in bare.missing  # never guessed


def test_diarise_route_reads_the_scan_and_says_so(client: TestClient) -> None:
    j = client.post("/assist/diarise", json={"computer_no": "9100001"}, headers=_h("U01")).json()
    p = j["prefill"]
    assert p["letter_ref"]["value"] == "G.O.Ms.No.19" and p["letter_date"]["value"] == "2018-02-09"
    assert (
        p["sender"]["value"] == "Secretary To Government (Ser.), General Administration Department"
    )
    assert p["from_ocr"] is True  # a scan: OCR draft, not yet reviewed
    native = client.post("/assist/diarise", json={"computer_no": "9100005"}, headers=_h("U01"))
    assert native.json()["prefill"]["from_ocr"] is False
    hidden = client.post("/assist/diarise", json={"computer_no": "9100001"}, headers=_h("U03"))
    unknown = client.post("/assist/diarise", json={"computer_no": "9199999"}, headers=_h("U03"))
    assert hidden.status_code == unknown.status_code == 404 and hidden.json() == unknown.json()


SPOUSE = "Establishment – Sri X, Junior Assistant – Request for transfer on spouse grounds – Reg."


def test_previous_references_offer_only_files_the_officer_can_open(client: TestClient) -> None:
    mine = client.post("/assist/previous-references", json={"subject": SPOUSE}, headers=_h("U01"))
    got = {s["computer_no"] for s in mine.json()["suggestions"]}
    assert {"1771342", "2041966", "2629410"} <= got and "2633187" not in got  # D20: confidential
    senior = client.post("/assist/previous-references", json={"subject": SPOUSE}, headers=_h("U02"))
    assert "2633187" in {s["computer_no"] for s in senior.json()["suggestions"]}
    made = client.post(
        "/sandbox/files",
        json={"subject": SPOUSE, "previous_references": ["USD01-12/31/2022-ESTT.I", "NOT-A-FILE"]},
        headers=_h("U01"),
    ).json()["file"]
    assert made["previous_references"] == ["USD01-12/31/2022-ESTT.I"]  # only files they can reach
    assert made["dealing_section"] == "ESTT.I" and made["state"] == "open"
    assert client.get(f"/sandbox/files/{made['computer_no']}", headers=_h("U01")).status_code == 200


def test_closing_joins_the_precedent_index_within_access(client: TestClient) -> None:
    q = {"query": "complaint dropped after the preliminary enquiry into the drain works tenders"}
    cr = client.post(
        "/assist/closing-remarks", json={"computer_no": "2601155"}, headers=_h("U06")
    ).json()
    assert cr["can_close"] and cr["text"].startswith("The last direction on the file is at Note #")
    assert cr["cited"] and cr["blockers"] == []
    not_holder = client.post(
        "/assist/closing-remarks", json={"computer_no": "2894562"}, headers=_h("U01")
    ).json()
    assert not not_holder["can_close"] and "not with you" in not_holder["blockers"][0]
    before = client.post("/assist/search", json=q, headers=_h("U04")).json()["documents"]
    r = client.post(
        "/sandbox/files/2601155/close",
        json={
            "remarks": "Complaint dropped after the preliminary enquiry into the drain works "
            "tenders; no further action. File closed."
        },
        headers=_h("U06"),
    )
    assert r.status_code == 200 and r.json()["file"]["state"] == "closed"
    after = client.post("/assist/search", json=q, headers=_h("U04")).json()["documents"]
    new = {d["canonical_id"] for d in after} - {d["canonical_id"] for d in before}
    assert new and all(c.startswith("AP-USD01-NOTE-USD0131-4-2025") for c in new)
    outsider = client.post("/assist/search", json=q, headers=_h("U01")).json()["documents"]
    assert not new & {d["canonical_id"] for d in outsider}  # confidential vigilance file
    # closing again, or closing a file you do not hold: not available
    assert (
        client.post(
            "/sandbox/files/2601155/close", json={"remarks": "again"}, headers=_h("U06")
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/sandbox/files/2894562/close", json={"remarks": "not mine"}, headers=_h("U01")
        ).status_code
        == 404
    )


def test_a_reviewed_scan_of_an_old_noting_becomes_precedent(client: TestClient) -> None:
    q = {"query": "technical scores of two bidders altered; articles of charge framed"}

    def found(uid: str) -> set[str]:
        return {
            d["canonical_id"]
            for d in client.post("/assist/search", json=q, headers=_h(uid)).json()["documents"]
        }

    before = found("U04")
    items = client.get("/assist/review/ocr", headers=_h("U04")).json()["items"]
    item = next(i for i in items if i["filename"].startswith("D22_"))
    assert all(
        not i["filename"].startswith("D22_")
        for i in client.get("/assist/review/ocr", headers=_h("U01")).json()["items"]
    )
    text = client.get(f"/assist/review/ocr/{item['item_id']}", headers=_h("U04")).json()[
        "draft_text"
    ]
    ok = client.post(
        f"/assist/review/ocr/{item['item_id']}/confirm",
        json={"reason": "checked against the scan", "corrected_text": text},
        headers=_h("U04"),
    ).json()
    assert ok["status"] == "indexed"
    assert ok["canonical_id"] in found("U04") - before
    assert ok["canonical_id"] not in found("U01")
    notes = client.post(
        "/assist/file-so-far", json={"computer_no": "2601155"}, headers=_h("U04")
    ).json()["notes"]
    assert [n["note_no"] for n in notes][-3:] == [6, 7, 8]  # the migrated notes join the chain
