"""Touchpoint 10 — local reference with a paragraph (plan §11.5), and the shared clause reader."""

from __future__ import annotations

import datetime as dt

import pytest

from app.agents.local_reference import SAME_NUMBER, local_reference
from app.agents.tools import ToolResult
from app.ingestion.clauses import clause_text, clauses, paragraph_label

OLD, NEW = "AP-FIN01-GOMS-88-2022", "AP-FIN01-GOMS-31-2025"
TEXT = {
    OLD: "1. Preamble.\n2. Guidelines:\n(iv) Station period five years.\n"
    "(v) Spouse cases, where both\nspouses are employees, get preference.\n3. Orders.",
    NEW: "Read the following:\n1. G.O.Ms.No.88.\n2. G.O.Ms.No.19.\nORDER:\n1. Background.\n"
    "2. Guidelines for 2025:\n(v) Spouse cases get preference subject to vacancy.\n",
}


def _status(**kw: object) -> ToolResult:
    base: dict[str, object] = {
        "tool": "check_document_status",
        "available": True,
        "status": "superseded",
        "by": NEW,
        "since": dt.date(2025, 5, 12),
    }
    return ToolResult.model_validate(base | kw)


@pytest.mark.parametrize(
    ("text", "want"),
    [
        ("G.O.Ms.No.88/2022 para 2(v)", "2.v"),
        ("para 2 (v) of GO 88", "2.v"),
        ("paragraph 3", "3"),
        ("Para. 2.iv", "2.iv"),
        ("G.O.Ms.No.88/2022", None),
    ],
)
def test_paragraph_label(text: str, want: str | None) -> None:
    assert paragraph_label(text) == want


def test_clauses_join_wrapped_lines_and_attach_sub_clauses() -> None:
    got = dict(clauses(TEXT[OLD]))
    assert got["2.v"].endswith("get preference.") and "both spouses" in got["2.v"]


def test_the_read_list_above_order_is_not_read_as_paragraphs() -> None:
    para2 = clause_text(TEXT[NEW], "2")  # "2." is also an item of the Read list above ORDER:
    assert para2 is not None and para2.startswith("2. Guidelines for 2025")
    assert clause_text(TEXT[NEW], "2.v") is not None


def test_a_repeated_paragraph_number_is_never_guessed() -> None:
    no_heading = TEXT[NEW].replace("ORDER:\n", "")
    assert clause_text(no_heading, "2") is None  # Read list "2." and order "2." both count
    assert clause_text(no_heading, "2.v") is not None  # (v) belongs to the later para 2 only


def test_superseded_order_shows_both_paragraphs_without_claiming_current() -> None:
    loc = local_reference("G.O.Ms.No.88/2022 para 2(v)", OLD, _status(), TEXT.__getitem__)
    assert loc.cited_clause and loc.cited_clause.clause_id == f"{OLD}#para-2.v"
    assert loc.successor_clause and loc.successor_clause.clause_id == f"{NEW}#para-2.v"
    assert not loc.successor_is_current and loc.note == SAME_NUMBER


def test_successor_is_current_only_when_the_status_tool_confirmed_it() -> None:
    loc = local_reference("88/2022 para 2(v)", OLD, _status(current_version=NEW), TEXT.__getitem__)
    assert loc.successor_is_current and loc.note is None


def test_in_force_order_shows_only_its_own_paragraph() -> None:
    st = _status(status="in_force", by=None, since=None, current_version=NEW)
    loc = local_reference("31/2025 para 2(v)", NEW, st, TEXT.__getitem__)
    assert loc.cited_clause is not None and loc.successor_clause is None


def test_missing_paragraph_and_no_paragraph() -> None:
    gone = local_reference("88/2022 para 9", OLD, _status(), TEXT.__getitem__)
    assert gone.cited_clause is None and gone.successor_clause is None and gone.note
    none = local_reference("88/2022", OLD, _status(), TEXT.__getitem__)
    assert none.paragraph is None and none.cited_clause is None and none.note is None


def test_nothing_is_read_when_the_order_is_not_available() -> None:
    read: list[str] = []

    def text_of(c: str) -> str:
        read.append(c)
        return TEXT[c]

    loc = local_reference("88/2022 para 2(v)", OLD, _status(available=False), text_of)
    assert loc.cited_clause is None and read == []
