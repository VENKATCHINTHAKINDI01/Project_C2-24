"""Conflict type D — precedent inconsistency, review only (plan §6.2; app/precedent/consistency)."""

from __future__ import annotations

import datetime as dt

from app.conflict.deterministic import ConflictFlag, ConflictType
from app.precedent.consistency import Disposal, EarlierNote, disposal_of, precedent_flags

SUBJECT = "School Education – Guidelines for conducting AP-TET – Reg."
HEAD = "2) Orders are in G.O.Ms.No.91. 3) It is proposed that the request may be "
TAIL = " 4) Submitted for orders."
ALLOW = HEAD + "allowed in terms of the orders cited above." + TAIL
REFUSE = HEAD + "rejected, as it is not covered by the orders cited above." + TAIL


def earlier(text: str, **kw: object) -> EarlierNote:
    base: dict[str, object] = {
        "file_no": "ESE01-EXAM0EXM/22/2017-EXAMS",
        "doc_id": "AP-ESE01-NOTE-22-2017",
        "subject": "School Education - Guidelines for conducting AP-TET",
        "date": dt.date(2017, 12, 21),
        "text": text,
    }
    return EarlierNote(**{**base, **kw})


def flags(text: str, notes: list[EarlierNote]) -> list[ConflictFlag]:
    return precedent_flags(
        file_no="ESE01-EXAM0EXM/25/2018-EXAMS",
        subject=SUBJECT,
        note_date=dt.date(2018, 5, 10),
        text=text,
        earlier=notes,
    )


def test_disposal_is_read_from_the_last_proposal_only() -> None:
    assert disposal_of(ALLOW)[0] is Disposal.ALLOW and disposal_of(REFUSE)[0] is Disposal.REFUSE
    assert (
        disposal_of("3) It is proposed that the request may not be allowed.")[0] is Disposal.REFUSE
    )
    assert disposal_of("3) It is proposed that the file may be circulated.")[0] is None
    assert disposal_of("Submitted for orders.")[0] is None
    both = "It is proposed that leave may be allowed and the advance may be rejected."
    assert disposal_of(both)[0] is None  # mixed: never guessed


def test_opposite_disposal_on_the_same_matter_is_an_uncertain_type_d() -> None:
    (f,) = flags(REFUSE, [earlier(ALLOW)])
    assert (f.type, f.cited, f.certain) == (ConflictType.D, "ESE01-EXAM0EXM/22/2017-EXAMS", False)
    assert f.evidence_ids == ("AP-ESE01-NOTE-22-2017",)
    assert "Review recommended" in f.explanation and "proposed to allow" in f.explanation


def test_no_flag_when_consistent_referred_to_later_or_another_matter() -> None:
    assert flags(ALLOW, [earlier(ALLOW)]) == []  # same disposal
    referred = REFUSE + " The earlier File No.ESE01-EXAM0EXM/22/2017-EXAMS has been seen."
    assert flags(referred, [earlier(ALLOW)]) == []  # the note refers to it
    assert flags(REFUSE, [earlier(ALLOW, date=dt.date(2018, 6, 1))]) == []  # not earlier
    assert flags(REFUSE, [earlier(ALLOW, subject="Transfer of teachers")]) == []  # other matter
    assert flags(REFUSE, [earlier("Submitted for orders.")]) == []  # no disposal recorded
    assert flags("Submitted for orders.", [earlier(ALLOW)]) == []  # this note proposes nothing
    own = earlier(ALLOW, file_no="ESE01-EXAM0EXM/25/2018-EXAMS")
    assert flags(REFUSE, [own]) == []  # the file's own earlier note


def test_one_flag_and_one_vote_per_earlier_file() -> None:
    two = [earlier(ALLOW), earlier(ALLOW, doc_id="AP-ESE01-NOTE-22-2017-DRAFT")]
    assert len(flags(REFUSE, two)) == 1


def test_the_earlier_practice_is_what_most_earlier_files_did() -> None:
    stray = earlier(REFUSE, file_no="ESE01-EXAM0EXM/25/2018-EXAMS-X", doc_id="N25")
    usual = earlier(ALLOW)
    # a later file follows the usual line after one stray case: divided, no practice departed from
    assert flags(ALLOW, [usual, stray]) == []
    more = earlier(ALLOW, file_no="ESE01-EXAM0EXM/23/2017-EXAMS", doc_id="N23")
    (f,) = flags(REFUSE, [usual, more, stray])  # against 2 of 3
    assert "2 of 3 earlier files" in f.explanation and set(f.evidence_ids) == {
        "AP-ESE01-NOTE-22-2017",
        "N23",
    }
