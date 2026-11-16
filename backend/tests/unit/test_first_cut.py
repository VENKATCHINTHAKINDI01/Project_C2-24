"""Touchpoint 6 — first-cut note: cited points for a Yellow Note (plan §11.5). Deterministic."""

from __future__ import annotations

import json
import re
from functools import cache

import pytest
from evaluation.harness.stack import build_stack
from evaluation.harness.suites import Harness, _load_seed

from app.agents.first_cut import NOTE_TEXT_PENDING, FirstCut, first_cut_note, ground_of
from app.config import REPO_ROOT
from app.conflict.facts import extract_proposal_facts
from app.noting.chain import parse_notes
from app.precedent.links import suggest_links
from app.retrieval.ladder import LadderConfig

SLOTS = json.loads((REPO_ROOT / "evaluation" / "slots_v1.json").read_text("utf-8"))
FILE = next(f for f in _load_seed()["files"] if f["computer_no"] == "2894562")


@cache
def _harness() -> Harness:
    cfg = LadderConfig(l2_top_k=10, l2_min_score=1.0, l3_max_hops=2)
    return Harness(build_stack(cfg, transcribe=True), SLOTS)


@cache
def _cut(user: str) -> FirstCut:
    h = _harness()
    cid = h.s.cid_of["D27"]
    text, meta = h._note(cid)  # noqa: SLF001 — evaluation helper
    facts = extract_proposal_facts(text, meta, h.rules, cid)
    ctx = h._tool_ctx(user, "2026-10-02")  # noqa: SLF001

    def file_of(c: str) -> str | None:
        t = h.s.tags(c)
        return t.file_no if t else None

    links = suggest_links(ctx, FILE["subject"], FILE["file_no"], file_of)
    return first_cut_note(
        ctx=ctx,
        file_no=FILE["file_no"],
        subject=FILE["subject"],
        draft_note=cid,
        meta=meta,
        action=facts.facts.action if facts.facts else None,
        flags=h.presend("D27", user).flags,
        precedents=[(lk.file_no, d.canonical_id) for lk in links for d in lk.documents],
        text_of=lambda c: h.s.text_of.get(c, ""),
        windows=[
            w
            for ws in h.s.stores.windows.values()
            for w in ws
            if h.visible(user, w.source.split("#", 1)[0])
        ],
    )


def _doc(cid: str) -> str:
    return _harness().s.doc_of.get(cid, cid)


@pytest.mark.parametrize(
    ("subject", "want"),
    [
        ("… Vijayawada on spouse grounds – Reg.", "spouse"),
        ("… on medical ground – Reg.", "medical"),
        ("Transfer of X – Reg.", None),
    ],
)
def test_ground_from_the_subject(subject: str, want: str | None) -> None:
    assert ground_of(subject) == want


def test_orders_are_the_current_ones_not_the_superseded() -> None:
    cut = _cut("U01")
    docs = {_doc(o.canonical_id) for o in cut.orders}
    assert {"D04", "D09", "D11"} <= docs and not docs & {"D01", "D02", "D03"}


def test_points_quote_the_governing_paragraphs_with_clause_ids() -> None:
    got = {p.clause_id: p.topic for p in _cut("U01").points}
    g = "AP-FIN01-GOMS-31-2025#para-"
    assert got[g + "2.i"] == "Ban / relaxation window"
    assert got[g + "3"] == "Ban / relaxation window"  # ban in force again after 31-05-2025
    assert got[g + "2.iv"] == "Ceiling"  # 15% ceiling, Finance concurrence
    assert got[g + "2.viii"] == "Competent authority"
    assert got[g + "2.v"] == "Spouse cases"


def test_precedent_decisions_are_quoted_and_set_against_the_windows() -> None:
    cut = _cut("U01")
    by = {_doc(p.source): p for p in cut.precedents}
    assert set(by) == {"D17", "D18", "D19"}  # D29 (not a transfer case) dropped; D20 not visible
    assert by["D17"].in_window is True and by["D19"].in_window is True
    assert by["D18"].in_window is False and "ban on transfers is in force" in by["D18"].decision
    assert by["D19"].windows == ("AP-FIN01-GOMS-31-2025#para-2.i",)


def test_every_factual_line_is_cited_and_prose_is_not_invented() -> None:
    body = _cut("U01").body
    for line in body.splitlines():
        if line.startswith("- ") and ("“" in line):
            assert re.search(r"\[AP-[A-Za-z0-9#.\-]+\]", line), line
    assert NOTE_TEXT_PENDING in body
    assert {f.type.value for f in _cut("U01").flags} == {"A", "C", "E", "F"}


def test_nothing_from_records_the_officer_cannot_see() -> None:
    h = _harness()
    cut = _cut("U01")
    for cid in cut.citations:
        assert h.visible("U01", cid.split("#", 1)[0]), cid
    assert not {_doc(c.split("#", 1)[0]) for c in cut.citations} & {"D20", "D21", "D22", "D23"}


def test_page_markings_are_not_part_of_a_quoted_paragraph() -> None:
    text = (
        "Note #1\n1. Since the continuation is on the same terms.\nRESTRICTED\n"
        "SO (Estt.I)\n12-08-2026"
    )
    notes = parse_notes(text, "x")
    assert notes and notes[0].by_paragraph
    assert all("RESTRICTED" not in w for n in notes for _, w in n.by_paragraph)
