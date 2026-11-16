"""Touchpoint 7 — referencing in a note (plan §11.5). Synthetic Vigilance file 2601155."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from app.auth.models import DocumentAccessTags
from app.config import REPO_ROOT
from app.connectors.eoffice import FileContext, NoteRef, PageRef
from app.eoffice_mock.adapter import adapter_from_seed, load_seed
from app.ingestion.detect import detect_file
from app.ingestion.extract import extract_native
from app.noting.references import (
    MatchedBy,
    ReferenceConfig,
    ReferenceResult,
    TargetKind,
    stems,
    suggest_references,
)
from tests.unit.test_ingestion_pipeline import IDX

CORPUS = REPO_ROOT / "data" / "synthetic" / "mock_v1"
CFG = ReferenceConfig(min_terms=2, max_suggestions=3)
D21 = IDX["D21"]
TAGS = DocumentAccessTags(
    doc_id="D21", department="USD01", section="VIG", classification="CONFIDENTIAL",
    file_no="USD01-31/4/2025-VIG",
)  # fmt: skip
TP07_AS_OF = dt.date(2025, 7, 21)


def _text() -> str:
    p = Path(CORPUS / D21["file"])
    return extract_native(p.read_bytes(), detect_file(p)).native_text


def _ctx(**kw: object) -> FileContext:
    adapter = adapter_from_seed(load_seed(CORPUS / "eoffice" / "seed.json"))
    ctx = adapter.file_context("2601155", "U04")
    return ctx.model_copy(update=kw) if kw else ctx


def _run(
    request: str,
    ctx: FileContext | None = None,
    *,
    as_of: dt.date = TP07_AS_OF,
    allowed: bool = True,
    visible: frozenset[str] = frozenset(),
) -> ReferenceResult:
    return suggest_references(
        request,
        ctx or _ctx(),
        [(D21["canonical_id"], _text(), TAGS)],
        as_of=as_of,
        allowed=lambda _t: allowed,
        order_visible=lambda c: c in visible,
        cfg=CFG,
    )


def test_mock_connector_gives_note_ids_and_paragraph_numbering_only() -> None:
    ctx = _ctx()
    assert [(n.note_id, n.note_no, n.paragraph_from) for n in ctx.notes][:3] == [
        ("2601155-N1", 1, 1),
        ("2601155-N2", 2, 4),
        ("2601155-N3", 3, 5),
    ]
    assert all(not hasattr(n, "text") for n in ctx.notes)


def test_tp07_earlier_proposal_points_to_note_1_para_3() -> None:
    res = _run("the earlier proposal for a preliminary enquiry")
    assert res.matched_by is MatchedBy.KEYWORDS
    top = res.suggestions[0]
    assert (top.kind, top.target_id, top.note_no, top.paragraph) == (
        TargetKind.PREVIOUS_NOTE,
        "2601155-N1",
        1,
        3,
    )
    assert top.source == D21["canonical_id"]
    assert "Enquiry Officer" in top.text and top.insert_text == "Note #1, para 3"
    assert set(top.matched_terms) >= {"propos", "preliminar"}


def test_a_named_note_and_paragraph_is_matched_exactly() -> None:
    assert [s.paragraph for s in _run("refer to Note #2").suggestions] == [4]
    assert [s.paragraph for s in _run("para 3 of Note #1").suggestions] == [3]
    assert [s.paragraph for s in _run("Note # 1, para 2").suggestions] == [2]
    miss = _run("Note #9")
    assert miss.matched_by is MatchedBy.NONE and miss.suggestions == ()


def test_notes_signed_after_the_date_are_not_offered() -> None:
    early = _run("approved order preliminary enquiry", as_of=dt.date(2025, 4, 12))
    assert {s.note_no for s in early.suggestions} <= {1, 2}


def test_a_note_the_officer_may_not_see_is_never_offered() -> None:
    assert _run("proposal preliminary enquiry", allowed=False).suggestions == ()


def test_yellow_notes_are_not_references() -> None:
    ctx = _ctx()
    drafts = tuple(n.model_copy(update={"confirmed": False}) for n in ctx.notes)
    res = _run("proposal preliminary enquiry", ctx.model_copy(update={"notes": drafts}))
    assert res.suggestions == ()


def test_correspondence_page_offered_only_when_its_order_is_visible() -> None:
    page = PageRef(
        correspondence_id="2601155-CX1", page_from=4, page_to=5,
        title="Complaint regarding tender evaluation for drain works", canonical_id="AP-X-1",
    )  # fmt: skip
    ctx = _ctx(pages=(page,))
    hidden = _run("complaint tender evaluation drain", ctx)
    assert all(s.kind is TargetKind.PREVIOUS_NOTE for s in hidden.suggestions)
    shown = _run("complaint tender evaluation drain", ctx, visible=frozenset({"AP-X-1"}))
    pages = [s for s in shown.suggestions if s.kind is TargetKind.CORRESPONDENCE_PAGE]
    assert pages and pages[0].insert_text == "pages 4–5/C"


def test_unrelated_request_finds_nothing() -> None:
    res = _run("budget for stationery")
    assert res.matched_by is MatchedBy.NONE and res.suggestions == ()


def test_stems_drop_request_words_and_join_word_forms() -> None:
    assert stems("the earlier proposal") == stems("proposed") == frozenset({"propos"})
    assert NoteRef(note_id="x", note_no=1, paragraph_from=1, confirmed=True).confirmed
