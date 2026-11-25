"""e-Office file movement in the sandbox (25 Nov 2026, owner: "from file creation to approval").
Only the officer the file is with writes notes, sends or closes it; sending signs the sender's
Yellow Notes and records the move; the file goes up the chain and comes back down approved."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from tests.unit.test_institutional_memory import _dfa


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


@pytest.fixture(scope="module")
def c() -> Iterator[TestClient]:
    app = create_app(get_settings().model_copy(update={"sandbox": True}))
    with TestClient(app) as client:
        client.get("/assist/notices", headers=_h("U01"))  # builds the runtime
        yield client


def _page(c: TestClient, cno: str, uid: str) -> Any:
    return c.get(f"/sandbox/files/{cno}", headers=_h(uid))


def _send(c: TestClient, cno: str, uid: str, to: str, remarks: str = "") -> Any:
    return c.post(
        f"/sandbox/files/{cno}/move", json={"to_user": to, "remarks": remarks}, headers=_h(uid)
    )


def _note(c: TestClient, cno: str, uid: str, text: str) -> Any:
    return c.post(f"/sandbox/files/{cno}/notes", json={"text": text}, headers=_h(uid))


def _folder(c: TestClient, uid: str, cno: str) -> dict[str, Any]:
    rows = c.get("/sandbox/files", headers=_h(uid)).json()["files"]
    return next(r for r in rows if r["computer_no"] == cno)


def test_a_file_goes_up_the_chain_is_approved_and_the_order_issued(c: TestClient) -> None:
    f = c.post(
        "/sandbox/files",
        json={"subject": "Transfer of Sri P. Ravi, Junior Assistant, on spouse grounds",
              "previous_references": []},
        headers=_h("U01"),
    ).json()["file"]  # fmt: skip
    cno = f["computer_no"]
    assert _page(c, cno, "U01").json()["file"]["with_me"] is True

    # Section Officer notes and sends up; the note is signed on sending
    assert (
        _note(c, cno, "U01", "1. Sri P. Ravi requests transfer on spouse grounds.").status_code
        == 200
    )
    opts = c.get(f"/sandbox/files/{cno}/move-options", headers=_h("U01")).json()["options"]
    ids = [o["user_id"] for o in opts]
    assert "U02" in ids and "U06" in ids and "U07" not in ids  # own department only (U07 is FIN01)
    assert ids.index("U06") < ids.index("U02")  # highest post first
    r = _send(c, cno, "U01", "U02", "For orders, please.")
    assert r.status_code == 200 and r.json()["movement"]["to_post"].startswith(
        "Assistant Secretary"
    )
    page = _page(c, cno, "U01").json()
    assert page["file"]["with_me"] is False and [n["state"] for n in page["notes"]] == ["green"]
    assert _folder(c, "U01", cno)["sent_by_me"] is True
    # the sender no longer holds it: no note, no send
    assert _note(c, cno, "U01", "2. More.").status_code == 404
    assert _send(c, cno, "U01", "U05").status_code == 404

    # up the chain: Assistant Secretary → Deputy Secretary → Secretary
    assert _folder(c, "U02", cno)["with_me"] is True
    assert _note(c, cno, "U02", "2. Submitted for orders.").status_code == 200
    assert _send(c, cno, "U02", "U05").status_code == 200
    assert _send(c, cno, "U05", "U06", "Submitted.").status_code == 200
    assert _note(c, cno, "U06", "3. Approved. Issue orders.").status_code == 200
    back = _send(c, cno, "U06", "U01", "Approved; issue orders.").json()["movement"]
    assert back["sent_back"] is True  # down the hierarchy

    # down to the Section Officer, who prepares the order and puts it up to the Secretary
    d = _dfa(c, cno)
    ap = c.get(f"/sandbox/files/{cno}/approver-options", headers=_h("U01")).json()["options"]
    assert {o["user_id"] for o in ap} == {"U02", "U05", "U06"}  # approving posts only
    r = c.post(f"/sandbox/files/{cno}/drafts/{d}/submit", json={"to_user": "U06",
               "remarks": "DFA put up."}, headers=_h("U01"))  # fmt: skip
    assert r.status_code == 200 and _page(c, cno, "U06").json()["file"]["with_me"] is True
    # put up to the Secretary: the Assistant Secretary, also an approver, does not see it
    assert _page(c, cno, "U02").json()["awaiting_approval"] == []
    assert c.post(f"/sandbox/files/{cno}/approvals/{d}/issue", headers=_h("U02")).status_code == 404
    r = c.post(f"/sandbox/files/{cno}/approvals/{d}/issue", headers=_h("U06"))
    assert r.status_code == 200 and r.json()["issued_as"].startswith("G.O.Rt.No.")

    issued = _page(c, cno, "U02").json()["issued"]  # on the file for everyone who opens it
    assert len(issued) == 1 and issued[0]["approved_by_post"] == "Secretary to Government"
    assert "SYNTHETIC — issued in the mock e-Office sandbox" in issued[0]["text"]
    notes = _page(c, cno, "U06").json()["notes"]
    assert [n["author_post"].split(" (")[0] for n in notes] == [
        "Section Officer", "Assistant Secretary", "Secretary to Government",
    ]  # fmt: skip
    moves = _page(c, cno, "U06").json()["movements"]
    assert [m["to_user"] for m in moves] == ["U02", "U05", "U06", "U01", "U06"]

    # the holder closes the decided file
    r = c.post(f"/sandbox/files/{cno}/close", json={"remarks": "Orders issued. File closed."},
               headers=_h("U06"))  # fmt: skip
    assert r.status_code == 200 and _page(c, cno, "U06").json()["file"]["with_me"] is False


def test_an_officer_outside_the_trail_cannot_send_or_note(c: TestClient) -> None:
    f = c.post(
        "/sandbox/files", json={"subject": "Movement check", "previous_references": []},
        headers=_h("U01"),
    ).json()["file"]  # fmt: skip
    cno = f["computer_no"]
    assert _send(c, cno, "U01", "U07").status_code == 404  # another department: not offered
    assert _send(c, cno, "U03", "U02").status_code == 404  # not the holder (or cannot open)
    assert _note(c, cno, "U03", "x").status_code == 404
    assert c.get(f"/sandbox/files/{cno}/move-options", headers=_h("U07")).status_code == 404
    assert (
        _note(c, cno, "U01", "   ").status_code == 422
        or _note(c, cno, "U01", "   ").status_code == 409
    )
