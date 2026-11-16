"""OCR accuracy suite (evaluation/ocr_scans.py): metrics and the run over the synthetic scans, with
a fake engine that returns the hand transcription (TEST ONLY: no Document AI call)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from evaluation.ocr_scans import CORPUS, char_similarity, markdown, run, wer

from app.ingestion.ocr import OcrError, OcrPage, OcrResult


def test_wer_and_similarity() -> None:
    assert wer("a b c d", "a b c d") == 0.0
    assert wer("a b c d", "a x c") == 0.5  # one substitution + one deletion over 4 words
    assert wer("G.O.Ms.No.88  Dt.03-06-2022", "G.O.Ms.No.88 Dt.03-06-2022") == 0.0  # whitespace
    assert char_similarity("abc", "abc") == 1.0 and char_similarity("abc", "xyz") == 0.0


class Transcription:
    """Returns each scan's hand transcription as page-1 text (perfect OCR), except D13."""

    def read(self, data: bytes, media_type: str, pages: Sequence[int]) -> OcrResult:
        import csv

        with (CORPUS / "documents_index.csv").open(encoding="utf-8") as f:
            did = next(
                r["id"] for r in csv.DictReader(f) if (CORPUS / r["file"]).read_bytes() == data
            )
        if did == "D13":
            raise OcrError("no recorded OCR response for this file")
        text = (CORPUS / "ground_truth" / "text" / f"{did}.txt").read_text("utf-8")
        return OcrResult(
            engine="fake",
            pages=tuple(
                OcrPage(page=n, text=text if n == pages[0] else "", confidence=0.9) for n in pages
            ),
        )


def test_suite_covers_every_scan_and_reports_not_run() -> None:
    rep = run(Transcription())
    docs = {r["doc"] for r in rep["documents"]}
    assert docs == {"D01", "D02", "D09", "D11", "D13", "D15", "D16", "D22"}
    s = rep["summary"]
    assert s["not_run"] == ["D13"] and s["ocr_run"] == 7
    d09 = next(r for r in rep["documents"] if r["doc"] == "D09")
    assert d09["wer"] == 0.0 and d09["canonical_id_match"] and d09["min_confidence"] == 0.9
    assert "not run" in markdown(rep)


def test_recall_ignores_text_the_transcription_left_out() -> None:
    from evaluation.ocr_scans import recall

    assert recall("a b c", "a b c d e f") == 1.0  # extra signature block / footer: not an error
    assert recall("a b c d", "a c d") == 0.75
    assert (
        recall("Secretariat – Transfers Dt. 17-09-2009", "Secretariat - Transfers Dt.17-09-2009")
        == 1.0
    )


@pytest.mark.parametrize(
    "version", ["pretrained-ocr-v1.0-2020-09-23", "pretrained-ocr-v2.1.1-2025-01-31"]
)
def test_recorded_document_ai_output_recovers_seven_of_eight_identities(version: str) -> None:
    """Regression on the real Document AI runs (11 Nov 2026, asia-south1). Both models emit the
    right-aligned "Dated:" away from the number (v2.1.1 several lines later); rows are rebuilt from
    line geometry. D16 stays unresolved: v1.0 cannot read Telugu at all; v2.1.1 reads the body
    (recall ≥ 0.97) but misreads the marker ఆర్.సి.నెం. as "5.2.3.", so the ID is never guessed and
    the file goes to review."""
    from evaluation.ocr_scans import CACHE_ROOT

    from app.ingestion.ocr import RecordedOcr, load_recorded

    rep = run(RecordedOcr(load_recorded(CACHE_ROOT / version), "documentai:recorded"))
    bad = {r["doc"] for r in rep["documents"] if not r.get("canonical_id_match")}
    assert bad == {"D16"}
    # floor taken from the first run (lowest English page: D22 0.917); a drop means a regression
    assert all(r["recall"] >= 0.9 for r in rep["documents"] if r["doc"] not in {"D15", "D16"})
    d16 = next(r for r in rep["documents"] if r["doc"] == "D16")
    assert (d16["recall"] >= 0.97) is version.startswith("pretrained-ocr-v2")


def test_eval_stack_reads_scans_with_real_ocr_and_never_the_transcriptions() -> None:
    """`run_eval.py --ocr-recorded`: held scans go through recorded Document AI v2.1.1 and the
    production review path (simulated reviewer). D16 stays held: its reference marker is misread."""
    from evaluation.harness.stack import build_stack

    from app.retrieval.ladder import LadderConfig

    stack = build_stack(
        LadderConfig(l2_top_k=10, l2_min_score=1.0, l3_max_hops=2),
        ocr_version="pretrained-ocr-v2.1.1-2025-01-31",
    )
    assert stack.transcribed == ()
    assert set(stack.ocr_confirmed) == {"D01", "D02", "D09", "D11", "D13", "D15", "D22"}
    assert stack.held == {"D16": "unresolved_reference"} and stack.not_indexed == ("D16",)
    reviewed = [i for i in stack.stores.queue.history() if i.reviewer]
    assert {i.reviewer for i in reviewed} == {"EVAL-REVIEWER (simulated)"}
