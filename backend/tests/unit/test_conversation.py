"""ADR-0067: model intent routing and answer composition, with their deterministic gates."""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any

import pytest

from app.agents.conversation import SEARCH, compose_answer, route_intent
from app.agents.llm import LLMError


class Fake:
    name = "fake"

    def __init__(self, out: Any = None, fail: bool = False) -> None:
        self.out, self.fail, self.calls = out, fail, []  # type: list[dict[str, Any]]

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> Any:
        self.calls.append({"prompt_id": prompt_id, "user": user, "schema": schema})
        if self.fail:
            raise LLMError("down")
        return self.out


def test_intent_is_one_of_the_offered_tools_or_nothing() -> None:
    llm = Fake({"tool": "dfa"})
    assert (
        route_intent(
            llm, "prepare a draft note for approval", on_file=True, allowed=["dfa", "presend"]
        )
        == "dfa"
    )
    assert llm.calls[0]["schema"]["properties"]["tool"]["enum"] == ["dfa", "presend", SEARCH]
    assert "<message>prepare a draft note for approval</message>" in llm.calls[0]["user"]
    # outside the offered list, an unknown tool, an error or no model: fall back to the rules
    assert route_intent(Fake({"tool": "movements"}), "x", on_file=True, allowed=["dfa"]) is None
    assert route_intent(Fake({"tool": "drop_table"}), "x", on_file=True, allowed=["dfa"]) is None
    assert route_intent(Fake(fail=True), "x", on_file=True, allowed=["dfa"]) is None
    assert route_intent(None, "x", on_file=True, allowed=["dfa"]) is None
    assert route_intent(Fake({"tool": "dfa"}), "x", on_file=True, allowed=["not_a_tool"]) is None
    assert (
        route_intent(
            Fake({"tool": SEARCH}), "rules on transfers", on_file=False, allowed=["summary"]
        )
        == SEARCH
    )


S = [
    {"text": "G.O.Ms.No.31 dated 12-05-2025 is in force for transfers of employees."},
    {"text": "G.O.Ms.No.88 dated 03-06-2022 was superseded by G.O.Ms.No.31."},
    {"text": "Spouse cases are given preference subject to vacancy."},
]


def test_a_composed_answer_keeps_every_checked_statement_once() -> None:
    out = compose_answer(
        Fake({"lead": "G.O.Ms.No.31 is in force for transfers of employees.", "lead_uses": [1],
              "sections": [{"heading": "Current position", "items": [1, 3, 3, 9]},
                           {"heading": "Earlier orders", "items": [2]}]}),
        "which order applies?", S,
    )  # fmt: skip
    assert out == {
        "lead": "G.O.Ms.No.31 is in force for transfers of employees.",
        "lead_uses": [1],
        "sections": [{"heading": "Current position", "items": [1, 3]},
                     {"heading": "Earlier orders", "items": [2]}],
    }  # fmt: skip
    # a statement the model leaves out is still shown
    left = compose_answer(
        Fake({"lead": "", "lead_uses": [], "sections": [{"heading": "Now", "items": [1]}]}), "q", S
    )
    assert left is not None and left["sections"][-1] == {"heading": None, "items": [2, 3]}


@pytest.mark.parametrize(
    ("lead", "uses"),
    [
        ("G.O.Ms.No.45 is in force.", [1]),  # a number the statements do not carry
        ("G.O.Ms.No.31 is in force.", [3]),  # the number is not in the statement it names
        (
            "Officers should approve every spouse request immediately without delay.",
            [3],
        ),  # own words
        ("G.O.Ms.No.31 is in force.", []),  # names no statement
    ],
)
def test_a_lead_that_adds_anything_is_dropped(lead: str, uses: list[int]) -> None:
    out = compose_answer(
        Fake(
            {
                "lead": lead,
                "lead_uses": uses,
                "sections": [{"heading": "Position", "items": [1, 2, 3]}],
            }
        ),
        "q",
        S,
    )
    assert out is not None and out["lead"] is None and out["sections"][0]["heading"] == "Position"


def test_headings_carry_no_facts_and_failures_fall_back() -> None:
    out = compose_answer(
        Fake(
            {
                "lead": "",
                "lead_uses": [],
                "sections": [{"heading": "Orders of 2025", "items": [1, 2, 3]}],
            }
        ),
        "q",
        S,
    )
    assert out is None  # nothing left to add: shown as checked
    assert compose_answer(Fake(fail=True), "q", S) is None
    assert compose_answer(Fake({"x": 1}), "q", S[:1]) is None  # one statement: no call at all
    assert compose_answer(None, "q", S) is None


NOTES = [
    {"note_no": 1, "post": "Section Officer (Vigilance)", "signed_at": "2025-04-09T10:00:00",
     "text": "A complaint has been received alleging that the technical evaluation of three tenders for "
             "drain works in 2024 was manipulated. It is proposed that a preliminary enquiry may be "
             "ordered, with a report within 60 days."},
    {"note_no": 3, "post": "Secretary to Government", "signed_at": "2025-04-18T10:00:00",
     "text": "Approved. Order preliminary enquiry. Keep the file confidential."},
]  # fmt: skip


def test_a_file_summary_keeps_only_sentences_its_notes_support() -> None:
    from app.agents.conversation import summarise_file

    llm = Fake({
        "lead": "A complaint about manipulated tender evaluation; the Secretary approved a preliminary enquiry on 18-04-2025.",
        "lead_notes": [1, 3],
        "points": [
            {"text": "A complaint alleged the technical evaluation of three tenders for drain works in 2024 was manipulated.", "notes": [1]},
            {"text": "A preliminary enquiry was proposed with a report within 60 days.", "notes": [1]},
            {"text": "The Secretary approved the enquiry and suspended the contractor for 90 days.", "notes": [3]},
            {"text": "The enquiry was ordered.", "notes": [7]},
        ],
    })  # fmt: skip
    out = summarise_file(llm, "Summarise this file", NOTES)
    assert out is not None
    assert out["lead"] and out["lead_notes"] == [1, 3]  # 18-04-2025 is the signature date
    texts = [p["text"] for p in out["points"]]
    assert len(texts) == 2  # "90 days" is in no note; note 7 does not exist
    assert "N1 · Section Officer (Vigilance)" in llm.calls[0]["user"]
    assert summarise_file(Fake(fail=True), "x", NOTES) is None
    assert summarise_file(None, "x", NOTES) is None
    assert summarise_file(Fake({"lead": "", "lead_notes": [], "points": []}), "x", NOTES) is None


def test_draft_inputs_fill_only_the_formats_fields_the_notes_support() -> None:
    from app.agents.conversation import draft_inputs

    fmt = {"title": "Government Order (G.O.Rt.)", "use_when": "Routine orders",
           "inputs": ["subject", "facts", "proposal", "signatory", "addressees", "copy_to"]}  # fmt: skip
    llm = Fake({
        "inputs": {
            "subject": "Vigilance – Complaint regarding technical evaluation of three tenders for drain works – Reg.",
            "facts": "A complaint has been received alleging that the technical evaluation of three tenders for drain works in 2024 was manipulated.",
            "proposal": "Government order a preliminary enquiry, with a report within 60 days, as approved by the Secretary to Government on 18-04-2025.",
            "signatory": "Secretary to Government",
            "addressees": "The Chief Engineer, Rs.5 crore works",
            "request": "not a field of this format",
        },
        "sources": {"subject": [1], "facts": [1], "proposal": [1, 3], "signatory": [3], "addressees": [1], "request": [1]},
    })  # fmt: skip
    out = draft_inputs(llm, "draft it", fmt, NOTES)
    assert out is not None
    assert set(out["inputs"]) == {
        "subject",
        "facts",
        "proposal",
        "signatory",
    }  # addressees: "5" is in no note
    assert out["sources"]["proposal"] == [1, 3]
    assert (
        "inputs needed: subject, facts, proposal, signatory, addressees, copy_to"
        in llm.calls[0]["user"]
    )
    assert draft_inputs(Fake(fail=True), "x", fmt, NOTES) is None
    assert draft_inputs(None, "x", fmt, NOTES) is None
