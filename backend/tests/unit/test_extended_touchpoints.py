"""Extended touchpoints 12, 17, 19 (plan §11.5; ADR-0037): movements and where the file is
pending, what was decided and what changed since, and the section handover — each from records
the officer may see, with references, and the same 404 for hidden and unknown files."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.agents.tools import ToolResult
from app.config import get_settings
from app.connectors.eoffice import MovementRef, OfficerFile
from app.main import create_app
from app.noting.chain import file_so_far, parse_notes
from app.noting.movements import movement_summary
from app.precedent.handover import SectionFile, build_handover
from app.temporal.since_decision import NewerOrder, since_decision

APP = create_app(get_settings().model_copy(update={"sandbox": True}))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        yield c


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


NOTES = """Note # 1
1. The request of Sri X for transfer on spouse grounds is examined.
2. Submitted for orders.

10/06/2024 10:15 AM
A. KUMAR
ASSISTANT SECTION OFFICER

Note # 2
3. Submitted. May approve.

11/06/2024 04:00 PM
B. RAO
SECTION OFFICER

Note # 3
4. Approved. Issue orders.

20/06/2024 05:30 PM
C. DEVI, I.A.S
SECRETARY TO GOVERNMENT
"""


def _mv(seq: int, a: str, ap: str, b: str, bp: str, day: int, hh: int, **kw: object) -> MovementRef:
    return MovementRef(
        seq=seq,
        from_user=a,
        from_post=ap,
        to_user=b,
        to_post=bp,
        sent_at=dt.datetime(2024, 6, day, hh, tzinfo=IST),
        **kw,
    )


MOVES = (
    _mv(
        1,
        "A1",
        "Assistant Section Officer (Estt.I)",
        "S1",
        "Section Officer (Estt.I)",
        10,
        11,
        remarks="for approval",
    ),
    _mv(
        2,
        "S1",
        "Section Officer (Estt.I)",
        "G1",
        "Secretary to Government",
        11,
        17,
        remarks="put up",
        due_on=dt.date(2024, 6, 18),
        priority="urgent",
    ),
)


def test_signature_below_the_date_is_read_as_name_and_post() -> None:
    """Set v2 prints the date first and the name and post below it (regression: the post was
    read from the note's last paragraph)."""
    notes = parse_notes(NOTES, "AP-USD01-NOTE-X-1-2024")
    assert [(n.note_no, n.post, n.signer) for n in notes] == [
        (1, "ASSISTANT SECTION OFFICER", "A. KUMAR"),
        (2, "SECTION OFFICER", "B. RAO"),
        (3, "SECRETARY TO GOVERNMENT", "C. DEVI, I.A.S"),
    ]
    assert notes[2].text == "4. Approved. Issue orders."


def test_each_movement_carries_its_remarks_and_the_note_put_up_before_it() -> None:
    chain = file_so_far([("AP-USD01-NOTE-X-1-2024", NOTES)])
    m = movement_summary(
        file_no="F/1", state="open", movements=MOVES, chain=chain, as_of=dt.date(2024, 6, 25)
    )
    assert [(s.remarks, [n.note_no for n in s.notes]) for s in m.steps] == [
        ("for approval", [1]),
        ("put up", [2]),
    ]
    assert m.steps[0].days_held == 1 and m.steps[1].days_held == 14
    assert (m.pending_with, m.days_pending, m.overdue) == ("G1", 14, True)
    assert m.headline.startswith("Pending with Secretary to Government (G1) since 11-06-2024")
    assert "overdue" in m.headline
    assert m.last_direction is not None and m.last_direction.note_no == 3

    back = (
        *MOVES,
        _mv(
            3,
            "G1",
            "Secretary to Government",
            "S1",
            "Section Officer (Estt.I)",
            21,
            10,
            sent_back=True,
        ),
    )
    closed = movement_summary(
        file_no="F/1", state="closed", movements=back, chain=chain, as_of=dt.date(2026, 1, 1)
    )
    assert closed.pending_with is None and closed.steps[-1].days_held is None
    assert closed.sent_back_times == 1 and closed.headline.startswith("File closed")


def _st(status: str | None, by: str | None = None, since: dt.date | None = None) -> ToolResult:
    if status is None:
        return ToolResult(tool="check_document_status", available=False)
    return ToolResult(
        tool="check_document_status", available=True, status=status, by=by, since=since
    )


def test_changes_after_the_decision_are_told_apart_from_changes_before_it() -> None:
    chain = file_so_far([("AP-USD01-NOTE-X-1-2024", NOTES)])
    statuses = {
        "AP-FIN01-GOMS-88-2022": _st("superseded", "AP-FIN01-GOMS-31-2025", dt.date(2025, 5, 12)),
        "AP-FIN01-GOMS-10-2020": _st("superseded", "AP-FIN01-GOMS-11-2023", dt.date(2023, 1, 2)),
        "AP-GAD01-GOMS-39-2019": _st("in_force"),
    }
    newer = {
        "AP-GAD01-GOMS-39-2019": [
            NewerOrder(
                canonical_id="AP-GAD01-GOMS-72-2025",
                kind="amended",
                issue_date=dt.date(2025, 7, 30),
                subject="Amendment",
            )
        ]
    }
    sd = since_decision(
        file_no="F/1",
        state="closed",
        chain=chain,
        movements=MOVES,
        relied_on=list(statuses),
        status_of=lambda c: statuses[c],
        newer=newer,
        subject_of=lambda c: "subject",
        date_of=lambda c: None,
    )
    assert sd.decided is not None and sd.decided.note_no == 3
    assert sd.decided_on == dt.date(2024, 6, 20)
    got = [(c.cited, c.change, c.after_decision) for c in sd.changes]
    assert got[:2] == [
        ("AP-GAD01-GOMS-39-2019", "amended", True),  # newest change first
        ("AP-FIN01-GOMS-88-2022", "superseded", True),
    ]
    assert ("AP-FIN01-GOMS-10-2020", "superseded", False) in got  # already changed when decided
    assert "Since then 2 of the 3 order(s) it relied on changed" in sd.headline
    assert sd.changes[1].by_reference == "G.O.Ms.No.31, Finance Department, of 2025"

    quiet = since_decision(
        file_no="F/1",
        state="closed",
        chain=chain,
        movements=MOVES,
        relied_on=["AP-GAD01-GOMS-39-2019"],
        status_of=lambda c: _st("in_force"),
        newer={},
        subject_of=lambda c: None,
        date_of=lambda c: None,
    )
    assert "None of the 1 order(s) it relied on has changed since" in quiet.headline
    assert "records available to you" in quiet.headline


def test_handover_lists_files_in_hand_standing_and_changed_orders() -> None:
    chain = file_so_far([("AP-USD01-NOTE-X-1-2024", NOTES)])
    as_of = dt.date(2024, 6, 25)

    def sf(no: str, state: str, relied: list[tuple[str, ToolResult]]) -> SectionFile:
        f = OfficerFile(
            computer_no=no, file_no=f"F/{no}", subject="s", with_officer=False, state=state
        )
        m = movement_summary(
            file_no=f.file_no,
            state=state,
            movements=MOVES,
            chain=chain,
            as_of=as_of if no != "2" else dt.date(2024, 6, 12),
        )
        return SectionFile(file=f, moves=m, relied_on=[(c, s, None, "subj") for c, s in relied])

    ok = _st("in_force")
    unconf = ToolResult(tool="check_document_status", available=True)
    gone = _st("superseded", "AP-FIN01-GOMS-31-2025", dt.date(2025, 5, 12))
    h = build_handover(
        section="ESTT.I",
        department="USD01",
        as_of=as_of,
        files=[
            sf("1", "open", [("AP-A-GOMS-1-2020", ok), ("AP-FIN01-GOMS-88-2022", gone)]),
            sf("2", "open", [("AP-A-GOMS-1-2020", ok), ("AP-B-GOMS-2-2021", unconf)]),
            sf("3", "closed", [("AP-B-GOMS-2-2021", unconf)]),
        ],
    )
    assert [f.computer_no for f in h.in_hand] == ["1", "2"]  # overdue first
    assert h.in_hand[0].overdue and h.in_hand[0].changed_orders == 1
    assert [(o.canonical_id, o.status, len(o.files)) for o in h.standing] == [
        ("AP-A-GOMS-1-2020", "in_force", 2),
        ("AP-B-GOMS-2-2021", "unconfirmed", 2),
    ]
    assert [o.canonical_id for o in h.no_longer_in_force] == ["AP-FIN01-GOMS-88-2022"]
    assert [d.computer_no for d in h.decisions] == ["3"] and h.closed_files == 1
    assert "2 file(s) in hand (1 overdue), 1 closed" in h.headline


# --- through the API (sandbox seed v1) ---------------------------------------------------------


def test_movements_route(client: TestClient) -> None:
    j = client.post("/assist/movements", json={"computer_no": "1771342"}, headers=_h("U01")).json()
    assert j["state"] == "closed" and len(j["steps"]) == 4
    assert [n["note_no"] for s in j["steps"] for n in s["notes"]] == [1, 2, 3, 4]
    assert j["steps"][0]["remarks"] == "Submitted after Note #1"
    assert j["last_direction"]["note_no"] == 5 and "Approved" in j["last_direction"]["excerpt"]
    open_ = client.post(
        "/assist/movements", json={"computer_no": "2894562"}, headers=_h("U01")
    ).json()
    assert open_["state"] == "open" and open_["headline"]


def test_since_decision_route(client: TestClient) -> None:
    j = client.post(
        "/assist/since-decision", json={"computer_no": "1771342"}, headers=_h("U01")
    ).json()
    assert j["decided"]["note_no"] == 5 and j["decided_on"] == "2022-06-20"
    c = j["changes"][0]
    assert (c["cited"], c["change"], c["by"], c["after_decision"]) == (
        "AP-FIN01-GOMS-88-2022",
        "superseded",
        "AP-FIN01-GOMS-31-2025",
        True,
    )
    assert c["by_reference"].startswith("G.O.Ms.No.31, Finance Department, dated")


def test_hidden_and_unknown_files_get_the_same_404(client: TestClient) -> None:
    for path in ("/assist/movements", "/assist/since-decision"):
        hidden = client.post(path, json={"computer_no": "2633187"}, headers=_h("U01"))
        unknown = client.post(path, json={"computer_no": "9999999"}, headers=_h("U01"))
        assert hidden.status_code == unknown.status_code == 404
        assert hidden.json() == unknown.json()


def test_handover_counts_only_files_the_officer_can_open(client: TestClient) -> None:
    mine = client.get("/assist/handover", headers=_h("U01")).json()
    senior = client.get("/assist/handover", headers=_h("U02")).json()
    assert mine["section"] == senior["section"] == "ESTT.I"
    ids = {f["computer_no"] for f in mine["in_hand"]} | {
        d["computer_no"] for d in mine["decisions"]
    }
    reach = {
        f["computer_no"] for f in client.get("/sandbox/files", headers=_h("U01")).json()["files"]
    }
    assert ids <= reach and "2633187" not in str(mine)  # the confidential decision U01 can't open
    assert senior["closed_files"] == mine["closed_files"] + 1
    gone = {o["canonical_id"]: o for o in mine["no_longer_in_force"]}
    assert gone["AP-FIN01-GOMS-88-2022"]["by"] == "AP-FIN01-GOMS-31-2025"
    none = client.get("/assist/handover", headers=_h("U05")).json()
    assert none["section"] is None and "no dealing section" in none["message"]
