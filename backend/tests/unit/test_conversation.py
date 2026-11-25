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
        self.out, self.fail = out, fail
        self.calls: list[dict[str, Any]] = []

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


def test_an_action_question_is_answered_from_the_e_office_record() -> None:
    """Regression (25 Nov): "do I have any actions on this file now" got a history retold with no
    answer and ISO dates. The e-Office record (state, holder, last direction) is now note 0."""
    import datetime as dt

    from app.agents.conversation import record_lines, summarise_file
    from app.connectors.eoffice import FileContext, MovementRef
    from app.noting.chain import file_so_far

    fctx = FileContext(
        computer_no="1", file_no="F/1", subject="s", department="d", dealing_section="x",
        classification="UNCLASSIFIED", movement_trail=("U02", "U01"), state="closed",
        movements=(MovementRef(seq=1, from_user="U02", from_post="Section Officer", to_user="U05",
                               to_post="Secretary to Government",
                               sent_at=dt.datetime(2025, 4, 10, 11, 0)),),
    )  # fmt: skip
    last = file_so_far([]).last_direction
    facts = record_lines(fctx, "U01", last)
    assert facts[0] == "This file is about s." and facts[1] == "The file is closed in e-Office."
    assert "with the Secretary to Government, sent by the Section Officer on 10-04-2025" in facts[2]
    assert facts[3] == "The file is not with you now."
    llm = Fake({
        "lead": "No. The file is closed and is not with you now; the Secretary to Government approved "
                "a preliminary enquiry on 18-04-2025.",
        "lead_notes": [0, 3],
        "points": [{"text": "The Secretary approved the preliminary enquiry on 18-04-2025.", "notes": [3]}],
    })  # fmt: skip
    out = summarise_file(llm, "do i have any actions to be done for this file now", NOTES, facts)
    assert out is not None and out["lead"].startswith("No.") and out["lead_notes"] == [0, 3]
    sent = llm.calls[0]["user"]
    assert "N0 · e-Office record" in sent and "The file is not with you now." in sent
    assert "18-04-2025" in sent and "2025-04-18" not in sent  # dates as officers write them
    # a record line cannot carry a claim the record does not make
    bad = Fake({"lead": "The file is with you and due on 30-04-2025.", "lead_notes": [0],
                "points": [{"text": "The Secretary approved the enquiry.", "notes": [3]}]})  # fmt: skip
    got = summarise_file(bad, "any action?", NOTES, facts)
    assert got is not None and got["lead"] is None


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


@pytest.mark.parametrize(
    ("text", "base", "ok"),
    [
        ("The Secretary approved the proposal.", "Approved. Order enquiry.", True),
        ("The proposal was approved.", "Approval is solicited for the proposal.", False),
        ("The proposal has not been approved yet.", "Approved.", False),
        ("The proposal is not yet approved.", "It is not approved till date.", True),
        ("The order was issued on 10-04-2025.", "Draft G.O. put up for approval.", False),
        ("The file was closed.", "The file is closed in e-Office.", True),
        (
            "A preliminary enquiry was proposed.",
            "It is proposed that an enquiry may be ordered.",
            True,
        ),
        (
            "The request was rejected and returned.",
            "The request is returned to the section.",
            False,
        ),
    ],
)
def test_a_sentence_may_not_claim_what_its_records_do_not_say(
    text: str, base: str, ok: bool
) -> None:
    from app.agents.conversation import claims_supported

    assert claims_supported(text, base) is ok


def test_the_holder_must_match_the_e_office_record() -> None:
    from app.agents.conversation import holder_contradicts

    rec_no = "The file is open in e-Office. The file is not with you now."
    rec_yes = "The file is open in e-Office. The file is with you now."
    assert holder_contradicts("Yes, the file is with you now.", rec_no)
    assert not holder_contradicts("No, the file is not with you.", rec_no)
    assert holder_contradicts("No, it is not with you.", rec_yes)
    assert not holder_contradicts("The Secretary approved it.", rec_yes)


@pytest.mark.parametrize(
    ("msg", "kind"),
    [
        ("hello", "hello"), ("Hi there!", "hello"), ("good morning", "hello"),
        ("what can you do", "help"), ("how can you help me?", "help"), ("help", "help"),
        ("thanks", "thanks"), ("ok thank you", "thanks"),
        ("hello, is G.O.Ms.No.31 of 2025 still in force", None),
        ("what are the rules on transfers", None), ("ok so who approved the transfer", None),
    ],
)  # fmt: skip
def test_small_talk_gets_a_fixed_reply_and_questions_do_not(msg: str, kind: str | None) -> None:
    from app.agents.conversation import small_talk

    got = small_talk(msg)
    want = {"hello": "Hello!", "help": "I answer from the records", "thanks": "You're welcome"}
    assert (got is None) if kind is None else (got or "").startswith(want[kind])


def test_the_officer_is_never_made_the_author_of_a_note() -> None:
    """Regression (25 Nov, 17:01): "You approved the preliminary enquiry on 18-04-2025" — note #3
    was signed by the Secretary to Government; the asking officer holds that post now."""
    from app.agents.conversation import summarise_file

    llm = Fake({
        "lead": "This file is about a complaint on tender evaluation; the Secretary to Government approved a preliminary enquiry on 18-04-2025.",
        "lead_notes": [1, 3],
        "points": [
            {"text": "You approved the preliminary enquiry on 18-04-2025.", "notes": [3]},
            {"text": "The Secretary to Government approved the preliminary enquiry on 18-04-2025.", "notes": [3]},
            {"text": "The file is with you now.", "notes": [0]},
        ],
    })  # fmt: skip
    facts = ["This file is about tender complaint.", "The file is with you now."]
    out = summarise_file(llm, "summarise the info about the file", NOTES, facts)
    assert out is not None and out["lead"]
    assert [p["text"][:7] for p in out["points"]] == ["The Sec", "The fil"]


def test_a_reply_with_only_a_lead_is_kept() -> None:
    """A direct answer needs no points (v3/v4 prompts); it used to be dropped for having none."""
    from app.agents.conversation import summarise_file

    llm = Fake({"lead": "No. The file is not with you now.", "lead_notes": [0], "points": []})
    out = summarise_file(llm, "any action for me?", NOTES, ["The file is not with you now."])
    assert out == {"lead": "No. The file is not with you now.", "lead_notes": [0], "points": []}


def test_a_full_summary_keeps_its_sections_and_drops_unknown_ones() -> None:
    from app.agents.conversation import summarise_file

    llm = Fake({
        "lead": "This file is about a complaint on tender evaluation.",
        "lead_notes": [1],
        "points": [
            {"text": "A complaint alleged the technical evaluation of three tenders for drain works in 2024 was manipulated.", "notes": [1], "section": "about"},
            {"text": "The Secretary to Government approved a preliminary enquiry on 18-04-2025.", "notes": [3], "section": "decision"},
            {"text": "A preliminary enquiry was proposed with a report within 60 days.", "notes": [1], "section": "Advice"},
        ],
    })  # fmt: skip
    out = summarise_file(llm, "summarise this file end to end", NOTES)
    assert out is not None
    assert [p.get("section") for p in out["points"]] == ["about", "decision", None]


def test_a_plain_draft_request_follows_the_file_stage() -> None:
    from app.agents.conversation import choose_format

    fid, why = choose_format(NOTES, 3, "open")
    assert (
        fid == "go_rt"
        and "Secretary to Government approved the proposal in Note #3 on 18-04-2025" in why
    )
    fid, why = choose_format(NOTES[:1], 1, "open")
    assert fid == "note_proposal" and "No approval is recorded" in why
    assert "closed in e-Office" in choose_format(NOTES, 3, "closed")[1]


def test_closest_extracts_are_verbatim_and_follow_the_question() -> None:
    from app.agents.conversation import closest_extracts

    docs = [
        ("AP-A", "GOVERNMENT OF ANDHRA PRADESH\nThe financial powers of the Commissioner for "
                 "administrative sanction of works shall be up to Rs.1.00 crore. Other matters follow."),
        ("AP-B", "Leave rules apply to all employees. Casual leave may be granted for ten days in a year."),
    ]  # fmt: skip
    got = closest_extracts(
        "What are the financial powers of the Commissioner for sanction of works?", docs
    )
    assert got and got[0]["canonical_id"] == "AP-A"
    assert got[0]["quote"].startswith("The financial powers of the Commissioner")
    assert all(g["quote"] in d for g in got for c, d in docs if c == g["canonical_id"])
    assert closest_extracts("hello", docs) == []
