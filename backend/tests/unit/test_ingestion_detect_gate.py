"""Detect-first routing on every corpus file, confidence gate and review queue (plan §4.1, §4.2,
§9.1; CLAUDE.md §5.1, §5.3, §8)."""

from __future__ import annotations

import datetime as dt
import io

import pytest
from pypdf import PdfReader, PdfWriter

from app.config import REPO_ROOT, load_runtime_config
from app.hitl.queue import ReviewError, ReviewKind, ReviewQueue, ReviewState
from app.ingestion.detect import Kind, PageKind, Route, detect, detect_file
from app.ingestion.gate import Extraction, GateOutcome, gate, indexable
from tests.unit.mock_access import CORPUS, rows

T0 = dt.datetime(2026, 11, 3, 12, tzinfo=dt.UTC)
EXPECTED = {
    "native_pdf": Route.NATIVE,
    "scanned_pdf": Route.OCR,
    "mixed_pdf": Route.PER_PAGE,
    "photo_jpg": Route.OCR_PREPROCESS,
    "docx": Route.NATIVE,
    "xlsx": Route.TABLE,
}
INDEX = rows("documents_index.csv")


@pytest.mark.parametrize("row", INDEX, ids=lambda r: r["id"])
def test_every_corpus_file_is_routed_as_the_manifest_says(row: dict[str, str]) -> None:
    d = detect_file(CORPUS / row["file"])
    assert d.route is EXPECTED[row["format"]], (row["id"], d)
    assert not d.extension_mismatch


def test_mixed_pdf_is_split_per_page() -> None:
    row = next(r for r in INDEX if r["format"] == "mixed_pdf")
    d = detect_file(CORPUS / row["file"])
    assert d.pages == (PageKind.TEXT, PageKind.IMAGE) and d.ocr_pages == (2,)


def test_extension_is_never_trusted() -> None:
    photo = next(r for r in INDEX if r["format"] == "photo_jpg")
    d = detect((CORPUS / photo["file"]).read_bytes(), "looks_like_a.pdf")
    assert d.kind is Kind.JPEG and d.route is Route.OCR_PREPROCESS and d.extension_mismatch


def _pdf_bytes(source: str, *, password: str | None = None, keep: int | None = None) -> bytes:
    w = PdfWriter()
    for i, p in enumerate(PdfReader(CORPUS / source).pages):
        if keep is None or i < keep:
            w.add_page(p)
    if password:
        w.encrypt(password)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_unreadable_inputs_are_unsupported_not_errors() -> None:
    native = next(r for r in INDEX if r["format"] == "native_pdf")["file"]
    assert detect(_pdf_bytes(native, password="x"), "a.pdf").route is Route.UNSUPPORTED
    assert detect(b"%PDF-1.7 garbage", "a.pdf").route is Route.UNSUPPORTED
    assert detect(b"", "a.txt").route is Route.UNSUPPORTED
    assert detect(b"\x00\x01\x02binary", "a.bin").route is Route.UNSUPPORTED
    assert detect(b"PK\x03\x04not really a zip", "a.docx").route is Route.UNSUPPORTED


def test_text_and_csv() -> None:
    assert detect(b"Memo No.1/2025\nSubject: test", "m.txt").route is Route.NATIVE
    table = b"name,post,station\nA,SA,Eluru\nB,JA,Guntur\n"
    assert detect(table, "t.csv").kind is Kind.CSV and detect(table, "t.csv").route is Route.TABLE


def test_heic_photo_is_sniffed() -> None:
    heic = b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + b"\x00" * 64
    assert detect(heic, "IMG_0001.HEIC").route is Route.OCR_PREPROCESS


# ---- confidence gate + review queue -------------------------------------------------------


def _ex(source: str, conf: dict[int, float] | None = None, version: str = "v1") -> Extraction:
    return Extraction(
        doc_id=source,
        version=version,
        detection=detect_file(CORPUS / source),
        page_confidence=conf or {},
    )


SCAN = next(r for r in INDEX if r["format"] == "scanned_pdf" and r["id"] == "D02")["file"]
MIXED = next(r for r in INDEX if r["format"] == "mixed_pdf")["file"]
NATIVE = next(r for r in INDEX if r["format"] == "native_pdf")["file"]


def test_native_text_is_indexed_without_review() -> None:
    q = ReviewQueue()
    d = gate(_ex(NATIVE), None, q, T0)
    assert d.outcome is GateOutcome.INDEX and q.pending() == ()


def test_uncalibrated_threshold_sends_every_ocr_extraction_to_review() -> None:
    """runtime.yaml extraction_confidence_min is null: no guessed number, everything OCR'd waits."""
    runtime = load_runtime_config(REPO_ROOT / "backend" / "config" / "runtime.yaml")
    assert runtime.ingestion.extraction_confidence_min is None
    q = ReviewQueue()
    d = gate(_ex(SCAN, {1: 0.99}), runtime.ingestion.extraction_confidence_min, q, T0)
    assert d.outcome is GateOutcome.HOLD and d.reason == "confidence threshold not calibrated"
    assert [i.kind for i in q.pending()] == [ReviewKind.LOW_CONFIDENCE_EXTRACTION]


@pytest.mark.parametrize(("conf", "outcome"), [(0.95, GateOutcome.INDEX), (0.70, GateOutcome.HOLD)])
def test_threshold_applies_to_ocr_pages_only(conf: float, outcome: GateOutcome) -> None:
    """Mixed PDF: page 1 is native, only page 2 (OCR) is gated. 0.8 is a test value only."""
    d = gate(_ex(MIXED, {2: conf}), 0.8, ReviewQueue(), T0)
    assert d.outcome is outcome and d.min_confidence == conf


def test_missing_page_confidence_is_held() -> None:
    q = ReviewQueue()
    d = gate(_ex(MIXED, {}), 0.8, q, T0)
    assert d.outcome is GateOutcome.HOLD and "pages [2]" in d.reason


def test_unsupported_file_is_held_for_review() -> None:
    q = ReviewQueue()
    ex = Extraction(doc_id="X", version="v1", detection=detect(b"\x00junk", "x.pdf"))
    d = gate(ex, 0.8, q, T0)
    assert d.outcome is GateOutcome.HOLD and q.pending()[0].kind is ReviewKind.UNSUPPORTED_FILE


def test_held_extraction_becomes_indexable_only_after_human_confirmation() -> None:
    q = ReviewQueue()
    ex = _ex(SCAN, {1: 0.6})
    d = gate(ex, 0.8, q, T0)
    assert not indexable(ex, d, q)
    item = d.review_item
    assert item is not None
    with pytest.raises(ReviewError):
        q.decide(item.item_id, reviewer=" ", confirm=True, reason="ok", at=T0)
    done = q.decide(
        item.item_id, reviewer="U01", confirm=True, reason="checked against paper copy", at=T0
    )
    assert done.state is ReviewState.CONFIRMED and done.reviewer == "U01" and done.decided_at == T0
    assert indexable(ex, d, q)
    with pytest.raises(ReviewError):
        q.decide(item.item_id, reviewer="U02", confirm=False, reason="changed mind", at=T0)


def test_rejected_or_new_version_stays_out() -> None:
    q = ReviewQueue()
    ex = _ex(SCAN, {1: 0.6})
    d = gate(ex, 0.8, q, T0)
    assert d.review_item is not None
    q.decide(d.review_item.item_id, reviewer="U01", confirm=False, reason="illegible", at=T0)
    assert not indexable(ex, d, q)
    rerun = _ex(SCAN, {1: 0.6}, version="v2")  # a new extraction is a new review, not a free pass
    assert gate(rerun, 0.8, q, T0).outcome is GateOutcome.HOLD


def test_resubmission_is_idempotent_and_history_kept() -> None:
    q = ReviewQueue()
    ex = _ex(SCAN, {1: 0.6})
    first = gate(ex, 0.8, q, T0).review_item
    second = gate(ex, 0.8, q, T0).review_item
    assert first == second and len(q.history()) == 1
