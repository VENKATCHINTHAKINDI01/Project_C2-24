"""Request and verified-fact extraction from real-layout notes (ADR-0060 addendum, owner
decision 19 Nov 2026): phrases only propose candidates; note structure and the file's context
decide; every quote is re-checked against its note; anything uncertain goes to the officer for
review and is never stated as a fact."""

from __future__ import annotations

import datetime as dt
import os
import threading
import uuid
from collections.abc import Iterator

import pytest

from app.config import get_settings
from app.noting.chain import NoteEntry, note_structure, parse_notes
from app.noting.draft_studio import DraftInputs, compose, load_formats
from app.noting.file_facts import FileParagraph, _validated, file_facts
from app.tracking.model_usage import (
    InMemoryModelUsage,
    ModelQuota,
    PostgresModelUsage,
    UsageEntry,
    UsageUnavailableError,
)

FORMATS = load_formats(get_settings().draft_formats_path)
NOTE = FORMATS.get("note_proposal")
SRC = "AP-ESE01-NOTE-TEST-1-2025"

# the e-Office layout of seed v2: a header with a numbered reference list, "* * *", then "1)"
V2 = """Note # 1
Sub: Transfer of a Headmaster Gr.II on request — orders by the Regional Joint Director – Reg.
Ref:
1. G.O.Ms.No.22, School Education (Services.II) Department, dated 20.05.2025.
2. Receipt No. 2793/2025-SER.II, dated 17.06.2025.
* * *
1) It is submitted that a reference has been received from the Regional Joint Director of
School Education, Kakinada regarding "Transfer of a Headmaster Gr.II on request" in respect of
K. Ramana Murthy (PUC, p.1).
2) The orders on the subject are in G.O.Ms.No.22, School Education (Services.II) Department,
dated 20.05.2025 (copies placed in References).
3) The individual has completed 6 years 2 months at the present station.
4) Approval Requested
   a) Approval for the proposal at the paras above.
   b) Orders on the action to be taken.
Note # 2
5) Sir, submitted for approval of Para 4.
"""
SUBJECT = "Transfer of a Headmaster Gr.II on request — orders by the Regional Joint Director – Reg."


def _notes(text: str = V2) -> list[NoteEntry]:
    return parse_notes(text, SRC)


def _n(no: int, paras: list[tuple[int, str]]) -> NoteEntry:
    return NoteEntry(
        note_no=no,
        paragraphs=(paras[0][0], paras[-1][0]) if paras else None,
        text=" ".join(t for _, t in paras),
        signer=None,
        post=None,
        signed_at=None,
        source=SRC,
        by_paragraph=tuple(paras),
    )


# ---- structure ---------------------------------------------------------------------------------


def test_the_reference_list_is_never_read_as_paragraphs() -> None:
    n1, n2 = _notes()
    assert n1.subject_line and n1.subject_line.startswith("Transfer of a Headmaster")
    assert [r[:20] for r in n1.references] == ["G.O.Ms.No.22, School", "Receipt No. 2793/202"]
    assert [p for p, _ in n1.by_paragraph] == [1, 2, 3, 4] and n1.paragraphs == (1, 4)
    assert "b) Orders on the action" in dict(n1.by_paragraph)[4]  # a sub-item stays in its para
    assert n2.paragraphs == (5, 5)
    # the older layout is unchanged: no header, "1." paragraphs
    subject, refs, paras = note_structure(["1. First.", "continued", "2. Second."])
    assert (
        subject is None and refs == () and paras == ((1, "1. First. continued"), (2, "2. Second."))
    )


# ---- the request: structure and context decide -------------------------------------------------


def test_a_request_worded_as_a_reference_received_is_found_with_its_reasons() -> None:
    ff = file_facts(_notes(), subject=SUBJECT)
    assert ff.request_status == "found" and [p.paragraph for p in ff.request] == [1]
    basis = set(ff.request[0].basis)
    assert {"states a request or a reference received", "refers to the PUC"} <= basis
    assert "in the first note on the file" in basis
    assert ff.next_paragraph == 6  # numbering continues after "5)", not after the reference list


def test_an_order_at_flag_a_is_not_taken_for_the_request() -> None:
    notes = [
        _n(
            1,
            [
                (1, "1. Fourteen Data Entry Operators are working on outsourcing basis."),
                (
                    2,
                    "2. Government, in G.O.Rt.No.1184, Finance (HR.I) Department, Dt.21-03-2025 "
                    "(Flag A), have permitted continuation of outsourcing services.",
                ),
            ],
        )
    ]
    ff = file_facts(notes, subject="Continuation of 14 outsourced Data Entry Operators – Reg.")
    assert ff.request == () and ff.request_status == "review"
    item = next(r for r in ff.review if r.kind == "request")
    assert item.paragraph.paragraph == 1  # offered for confirmation, not stated
    assert all(r.paragraph.paragraph != 2 for r in ff.review)  # an order is not a fact either


def test_no_request_in_the_file_is_said_so_and_the_gap_stays() -> None:
    notes = [_n(1, [(1, "1. Put up for orders."), (2, "2. Approved.")])]
    ff = file_facts(notes, subject="Something – Reg.")
    assert ff.request_status == "not_found" and ff.request == () and ff.review == ()
    assert NOTE is not None
    d = compose(
        NOTE, DraftInputs(), department="X", read_list=(), label=lambda c, _: c, file_facts=ff
    )
    req = next(p for p in d.parts if p.key == "request")
    assert req.origin == "blank" and "[What the PUC (Flag A) asks for.]" in req.text
    assert any(
        p.key == "confirm" and "could not be identified" in p.text and p.origin == "check"
        for p in d.parts
    )


def test_a_person_named_elsewhere_does_not_make_a_request() -> None:
    """The subject names one person; a paragraph about someone else gets no context signal."""
    notes = [_n(1, [(1, "1. Sri B. Other has requested leave (Flag A).")])]
    found = file_facts(notes, subject="Sri A. Test – Request for transfer – Reg.")
    assert (
        found.request[0].basis
        and "names the person in the file subject" not in found.request[0].basis
    )


# ---- facts: verified ones quoted, others put to the officer ------------------------------------


def test_a_fact_not_stated_as_verified_goes_to_review_never_to_facts() -> None:
    ff = file_facts(_notes(), subject=SUBJECT)
    assert ff.facts == ()
    item = next(r for r in ff.review if r.kind == "fact")
    assert item.paragraph.paragraph == 3 and "not stated as verified" in item.reason
    assert NOTE is not None
    d = compose(
        NOTE, DraftInputs(), department="ESE", read_list=(), label=lambda c, _: c, file_facts=ff
    )
    facts = next(p for p in d.parts if p.key == "facts")
    assert facts.origin == "blank"  # nothing stated as verified
    conf = [p for p in d.parts if p.key == "confirm"]
    assert any("6 years 2 months" in p.text and "to be verified" in p.text for p in conf)
    assert all(p.origin == "check" and p.refs for p in conf)
    # orders restated, submissions and approvals are neither facts nor review items
    assert {r.paragraph.paragraph for r in ff.review} == {3}


def test_the_officers_own_facts_replace_the_review_points() -> None:
    assert NOTE is not None
    ff = file_facts(_notes(), subject=SUBJECT)
    d = compose(
        NOTE,
        DraftInputs(facts="Station period verified from the SR: 6 years 2 months."),
        department="ESE",
        read_list=(),
        label=lambda c, _: c,
        file_facts=ff,
    )
    assert not any(p.key == "confirm" and "not stated as verified" in p.text for p in d.parts)


# ---- validation: a quote is the note's own words at that paragraph -----------------------------


def test_a_quote_that_does_not_match_its_note_is_rejected() -> None:
    (n1, *_) = _notes()
    good = FileParagraph(
        note_no=1,
        paragraph=3,
        text=dict(n1.by_paragraph)[3],
        source=SRC,
        ref=f"{SRC}#note-1-para-3",
    )
    by = {1: n1}
    assert _validated(good, by)
    assert not _validated(good.model_copy(update={"text": good.text.replace("6", "9")}), by)
    assert not _validated(good.model_copy(update={"paragraph": 2}), by)
    assert not _validated(good.model_copy(update={"source": "AP-OTHER"}), by)
    assert not _validated(good.model_copy(update={"note_no": 7}), by)


# ---- usage ledger: server-side, atomic, fail closed, logged ------------------------------------


def test_the_quota_fails_closed_when_the_count_cannot_be_kept() -> None:
    class _Down(InMemoryModelUsage):
        def take(self, user_id: str, action: str, day: dt.date, limit: int) -> int | None:
            raise OSError("database unreachable")

    with pytest.raises(UsageUnavailableError):
        ModelQuota(_Down(), 40).take("U01")


DSN = os.environ.get("C2_TEST_PG_DSN")


@pytest.fixture
def pg_usage() -> Iterator[PostgresModelUsage]:
    if not DSN:
        pytest.skip("C2_TEST_PG_DSN not set")
    psycopg = pytest.importorskip("psycopg")
    from pathlib import Path

    from app.pg import Pg, apply_migrations

    schema = f"t_{uuid.uuid4().hex[:10]}"
    admin = psycopg.connect(DSN, autocommit=True)
    admin.execute(f"CREATE SCHEMA {schema}")
    p = Pg(lambda: psycopg.connect(DSN, options=f"-c search_path={schema}"), size=8)
    try:
        apply_migrations(p, Path(__file__).resolve().parents[3] / "data" / "schemas" / "postgres")
        yield PostgresModelUsage(p)
    finally:
        p.close()
        admin.execute(f"DROP SCHEMA {schema} CASCADE")
        admin.close()


def test_the_postgres_count_holds_under_concurrent_requests(pg_usage: PostgresModelUsage) -> None:
    q = ModelQuota(pg_usage, 5)
    got: list[int | None] = []
    lock = threading.Lock()

    def one() -> None:
        r = q.take("U01")
        with lock:
            got.append(r)

    threads = [threading.Thread(target=one) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(x for x in got if x is not None) == [1, 2, 3, 4, 5]
    assert got.count(None) == 7 and q.used("U01") == 5 and q.used("U02") == 0
    at = dt.datetime(2026, 11, 19, 9, tzinfo=dt.UTC)
    q.log(
        UsageEntry(
            at=at,
            request_id="r1",
            user_id="U01",
            action=q.action,
            outcome="ok",
            engine="gemini@asia-south1",
            prompt_id="noting_draft.v3",
            target="2894562",
            kept=4,
            removed=1,
            used_today=5,
        )
    )
    (e,) = pg_usage.entries(at - dt.timedelta(minutes=1))
    assert (e.user_id, e.outcome, e.kept, e.removed, e.used_today) == ("U01", "ok", 4, 1, 5)
