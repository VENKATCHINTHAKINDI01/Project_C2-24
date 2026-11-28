"""ADR-0072: suggested notes and Polish in the note editor, with their gates."""

# ruff: noqa: E501

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.llm import LLMError
from app.config import get_settings
from app.main import create_app
from app.noting.note_assist import polish_note, rule_polish, suggest_notes


class Fake:
    name = "fake"

    def __init__(self, out: Any = None, fail: bool = False) -> None:
        self.out, self.fail = out, fail
        self.calls: list[dict[str, Any]] = []

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> Any:
        self.calls.append({"prompt_id": prompt_id, "user": user})
        if self.fail:
            raise LLMError("down")
        return self.out


NOTES = [
    {"note_no": 1, "post": "Section Officer", "date": "10-11-2026",
     "text": "Sri P. Ravi, Assistant Engineer, Municipal Circle, Kurnool, in his representation dated 03-11-2026 has requested transfer to Guntur Circle on spouse ground. A vacancy exists in Guntur Circle. Put up for orders."},
    {"note_no": 2, "post": "Section Officer", "date": "14-11-2026",
     "text": "Verified. He joined Kurnool on 01-06-2023 and no disciplinary case is pending. Put up."},
    {"note_no": 3, "post": "Deputy Secretary", "date": "17-11-2026",
     "text": "Orders may issue transferring Sri P. Ravi to Guntur Circle, subject to his relief by the Head of Department. Draft G.O.Rt. may be put up."},
]  # fmt: skip
ROUGH = "as per DS orders at N3 draft go rt prepared for transfer of p ravi AE kurnool to guntur. hod relief condition added. pls approve"


def test_suggestions_are_kept_only_when_the_notes_they_cite_carry_them() -> None:
    good = {
        "label": "Put up the draft G.O.Rt.",
        "sources": [3],
        "text": "As ordered at N3, a draft G.O.Rt. transferring Sri P. Ravi to Guntur Circle, subject to his relief by the Head of Department, is placed below. Submitted for orders.",
    }
    invented_date = {
        "label": "Seek relief",
        "sources": [3],
        "text": "The Head of Department may relieve Sri P. Ravi by 30-11-2026.",
    }
    own_words = {
        "label": "Comment",
        "sources": [3],
        "text": "Considering administrative exigencies and employee welfare, favourable consideration recommended strongly.",
    }
    llm = Fake({"suggestions": [good, invented_date, own_words]})
    res = suggest_notes(
        llm, subject="Transfer of Sri P. Ravi", notes=NOTES, me_post="Section Officer"
    )
    assert [s.label for s in res.suggestions] == ["Put up the draft G.O.Rt."]
    assert res.suggestions[0].sources == (3,)
    assert res.withheld == 2
    assert "<last_direction>N3</last_direction>" in llm.calls[0]["user"]


def test_suggestions_fall_back_to_an_acknowledgement_without_the_model() -> None:
    for llm in (None, Fake(fail=True), Fake({"suggestions": []})):
        res = suggest_notes(llm, subject="s", notes=NOTES, me_post="Section Officer")
        assert [s.text for s in res.suggestions] == [
            "Orders at N3 noted. Action will be taken accordingly."
        ]
        assert res.reason


def _sents(*parts: tuple[str, int] | str) -> dict[str, Any]:
    out = []
    for p in parts:
        text, no = (p, 0) if isinstance(p, str) else p
        out.append({"text": text, "from_note": no, "new_paragraph": text.startswith("Submitted")})
    return {"sentences": out}


OK = (
    "As ordered by the Deputy Secretary at N3, a draft G.O.Rt. has been prepared for the transfer of Sri P. Ravi, Assistant Engineer, from Kurnool to Guntur.",
    "The condition of relief by the Head of Department has been included.",
    "Submitted for approval, please.",
)


def test_polish_keeps_every_figure_and_reference() -> None:
    res = polish_note(Fake(_sents(*OK)), text=ROUGH, notes=NOTES)
    assert res.reason is None
    assert res.text == OK[0] + " " + OK[1] + "\n" + OK[2]
    # a version that adds a date the officer never wrote is withheld: rule-based clean-up instead
    bad = (OK[0].replace("Guntur.", "Guntur with effect from 01-12-2026."), OK[1], OK[2])
    res = polish_note(Fake(_sents(*bad)), text=ROUGH, notes=NOTES)
    assert res.reason == "changed what the note says" and "01-12-2026" in res.withheld
    assert res.text == rule_polish(ROUGH)


def test_a_typed_note_in_plain_words_is_polished() -> None:
    """Owner report 26 Nov: Polish worked on suggested notes but not on a note typed by hand."""
    typed = "the representation of sri p ravi for transfer to guntur on spouse ground was examined and vacancy is available there. hod report received. may be placed before DS for orders"
    out = (
        "The representation of Sri P. Ravi for transfer to Guntur on spouse ground has been examined, and a vacancy is available there.",
        "The report of the Head of Department has been received.",
        "The file may be placed before the Deputy Secretary for orders.",
    )
    res = polish_note(Fake(_sents(*out)), text=typed, notes=NOTES)
    assert res.reason is None, res.withheld


def test_polish_never_drops_a_date_even_when_shortening() -> None:
    text = "the representation dated 03-11-2026 of p ravi was examined and the vacancy position verified with the HoD. put up for orders"
    short = _sents(
        "Representation of Sri P. Ravi examined; vacancy verified with the Head of Department.",
        "Submitted for orders.",
    )
    res = polish_note(Fake(short), text=text, mode="short")
    assert res.reason == "changed what the note says" and "03-11-2026" in res.withheld


def test_elaborate_adds_only_facts_that_their_note_carries() -> None:
    fact = ("He joined Kurnool on 01-06-2023 and no disciplinary case is pending.", 2)
    res = polish_note(Fake(_sents(OK[0], fact, OK[2])), text=ROUGH, mode="elaborate", notes=NOTES)
    assert res.reason is None
    assert res.added == (fact,)
    wrong_note = (fact[0], 1)  # N1 does not say this
    assert polish_note(
        Fake(_sents(OK[0], wrong_note)), text=ROUGH, mode="elaborate", notes=NOTES
    ).reason
    plain_mode = polish_note(Fake(_sents(OK[0], fact)), text=ROUGH, mode="polish", notes=NOTES)
    assert plain_mode.reason  # adding facts needs "elaborate" or an instruction


def test_polish_and_suggestions_stream_only_checked_pieces() -> None:
    events: list[dict[str, Any]] = []
    bad = "It is hereby sanctioned with effect from 01-12-2026."
    res = polish_note(Fake(_sents(OK[0], bad, OK[2])), text=ROUGH, notes=NOTES, emit=events.append)
    assert [e["text"] for e in events] == [OK[0], OK[2]]  # the unchecked sentence never shown
    assert res.reason == "changed what the note says"  # and the whole is withheld at the end
    events.clear()
    good = {
        "label": "Put up the draft G.O.Rt.",
        "sources": [3],
        "text": "As ordered at N3, a draft G.O.Rt. transferring Sri P. Ravi to Guntur Circle, subject to his relief by the Head of Department, is placed below. Submitted for orders.",
    }
    suggest_notes(
        Fake({"suggestions": [good]}),
        subject="s",
        notes=NOTES,
        me_post="Section Officer",
        emit=events.append,
    )
    assert [e["type"] for e in events] == ["suggestion"]


def test_rule_polish_expands_and_closes_sentences() -> None:
    assert rule_polish("as per DS orders draft go rt prepared. pls approve") == (
        "As per Deputy Secretary orders draft G.O.Rt. prepared. Please approve."
    )


# --- API -------------------------------------------------------------------------------------


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


@pytest.fixture(scope="module")
def c() -> Iterator[TestClient]:
    app = create_app(get_settings().model_copy(update={"sandbox": True}))
    with TestClient(app) as client:
        client.get("/assist/notices", headers=_h("U01"))
        yield client


def test_note_assist_api_holder_only_and_nothing_saved(c: TestClient) -> None:
    cno = c.post("/sandbox/files", json={"subject": "Transfer of Sri P. Ravi on spouse ground", "previous_references": []},
                 headers=_h("U01")).json()["file"]["computer_no"]  # fmt: skip
    r = c.post("/assist/note/suggestions", json={"computer_no": cno}, headers=_h("U01"))
    assert r.status_code == 200 and r.json()["suggestions"] == []  # no notes yet
    before = c.get(f"/sandbox/files/{cno}", headers=_h("U01")).json()
    p = c.post("/assist/note/polish", json={"computer_no": cno, "text": ROUGH}, headers=_h("U01"))
    assert p.status_code == 200
    body = p.json()
    assert body["text"].startswith("As per Deputy Secretary orders at N3")
    st = c.post(
        "/assist/note/polish/stream", json={"computer_no": cno, "text": ROUGH}, headers=_h("U01")
    )
    assert st.status_code == 200 and '"type": "done"' in st.text
    assert body["reason"]  # no model in tests: the rule-based clean-up, said so
    after = c.get(f"/sandbox/files/{cno}", headers=_h("U01")).json()
    assert after["notes"] == before["notes"] and after["drafts"] == before["drafts"]
    short = c.post(
        "/assist/note/polish", json={"computer_no": cno, "text": "pls approve"}, headers=_h("U01")
    )
    assert short.status_code == 422
    # an officer the file is not with gets no suggestions; one who cannot open it gets 404
    other = c.post("/assist/note/suggestions", json={"computer_no": cno}, headers=_h("U02"))
    assert other.status_code in (200, 404)
    if other.status_code == 200:
        assert other.json()["suggestions"] == []


def test_a_note_with_spelling_mistakes_is_polished() -> None:
    """Owner report 27 Nov: Polish withheld the AI version of a note full of typing mistakes."""
    typed = "I aprove the file aftr cheking al the relted fils from myside."
    good = "I approve the file after checking all the related files from my side."
    res = polish_note(Fake(_sents(good)), text=typed, notes=NOTES)
    assert res.reason is None, res.withheld
    assert res.text == good


def test_the_basic_clean_up_corrects_common_misspellings_but_not_names() -> None:
    assert rule_polish("I aprove the file aftr cheking al the relted fils from myside") == (
        "I approve the file after checking all the related files from my side."
    )
    assert rule_polish("sent to Guntur and Kurnool") == "Sent to Guntur and Kurnool."


def test_a_rewrite_that_changes_too_much_says_so() -> None:
    res = polish_note(
        Fake(_sents("The quarterly budget statement shows a deficit.")),
        text="I aprove the file aftr cheking al the relted fils from myside.",
    )
    assert res.reason == "rewrote too much"
