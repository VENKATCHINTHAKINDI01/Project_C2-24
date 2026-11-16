"""OCR for scans (plan §4.1, §4.2; ADR-0017): Document AI response parsing, the engine's request
and error handling, caching, configuration, and the pipeline path: OCR draft → held for review →
reviewer confirms or corrects → indexed with the scan's own version. No GCP calls: a fake client
or engine stands in, and is labelled as such."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.hitl.queue import ReviewKind, ReviewState
from app.ingestion.ocr import (
    CachingOcr,
    DocumentAiOcr,
    OcrError,
    OcrPage,
    OcrResult,
    RecordedOcr,
    ocr_from_settings,
    parse_document,
)
from app.ingestion.pipeline import (
    ConfirmError,
    IngestionStores,
    IngestStatus,
    _version,
    confirm_extraction,
    ingest,
)
from tests.unit.mock_access import CORPUS
from tests.unit.test_ingestion_pipeline import DEPTS, HIER, IDX, T0, _src

TEXT = "ORDER:\n1. Spouse cases.\nతెలుగు"
DOC: dict[str, Any] = {  # trimmed Document AI response (JSON form: int64 as strings, 0 omitted)
    "text": TEXT,
    "pages": [
        {
            "page_number": 1,
            "layout": {"text_anchor": {"text_segments": [{"end_index": str(len(TEXT))}]}},
            "detected_languages": [{"language_code": "en"}, {"language_code": "te"}],
            "paragraphs": [
                {
                    "layout": {
                        "confidence": 0.9,
                        "text_anchor": {"text_segments": [{"start_index": "7", "end_index": "23"}]},
                    }
                }
            ],
            "tokens": [
                {
                    "layout": {
                        "confidence": 1.0,
                        "text_anchor": {"text_segments": [{"end_index": "6"}]},
                    }
                },
                {
                    "layout": {
                        "confidence": 0.5,
                        "text_anchor": {
                            "text_segments": [{"start_index": "24", "end_index": "30"}]
                        },
                    }
                },
            ],
        }
    ],
}


def test_parse_reads_text_confidence_languages_and_paragraphs() -> None:
    r = parse_document(DOC, "documentai:asia-south1:x", [1])
    p = r.pages[0]
    assert p.page == 1 and p.text == TEXT
    assert p.confidence == 0.75  # token confidences weighted by length: (6·1.0 + 6·0.5) / 12
    assert p.languages == ("en", "te")
    assert [q.text for q in p.paragraphs] == ["1. Spouse cases."]


def test_a_page_missing_from_the_response_is_empty_with_no_confidence() -> None:
    r = parse_document(DOC, "e", [1, 2])
    assert r.page(2) == OcrPage(page=2, text="", confidence=None)


def test_confidence_falls_back_to_paragraphs_then_page_then_none() -> None:
    no_tokens = json.loads(json.dumps(DOC))
    del no_tokens["pages"][0]["tokens"]
    assert parse_document(no_tokens, "e", [1]).pages[0].confidence == 0.9
    del no_tokens["pages"][0]["paragraphs"]
    assert parse_document(no_tokens, "e", [1]).pages[0].confidence is None
    no_tokens["pages"][0]["layout"]["confidence"] = 0.8
    assert parse_document(no_tokens, "e", [1]).pages[0].confidence == 0.8


# ---- the engine's request (fake client; no network) ------------------------------------------


class FakeClient:
    """Stands in for DocumentProcessorServiceClient: records the request, returns DOC."""

    def __init__(self, fail: bool = False) -> None:
        self.requests: list[Any] = []
        self.fail = fail

    def processor_path(self, project: str, location: str, processor: str) -> str:
        return f"projects/{project}/locations/{location}/processors/{processor}"

    def process_document(self, request: Any) -> Any:
        from google.cloud import documentai_v1 as d

        self.requests.append(request)
        if self.fail:
            raise RuntimeError("quota exceeded: secret text must not leak")
        return d.ProcessResponse(document=d.Document.from_json(json.dumps(DOC)))


def test_request_is_region_pinned_page_selected_and_language_hinted() -> None:
    pytest.importorskip("google.cloud.documentai_v1")
    client = FakeClient()
    eng = DocumentAiOcr("proj", "asia-south1", "abc", client=client)
    r = eng.read(b"%PDF-1.4", "application/pdf", [2, 3])
    req = client.requests[0]
    assert req.name == "projects/proj/locations/asia-south1/processors/abc"
    assert list(req.process_options.individual_page_selector.pages) == [2, 3]
    assert list(req.process_options.ocr_config.hints.language_hints) == ["te", "en"]
    assert req.raw_document.mime_type == "application/pdf"
    assert r.engine == "documentai:asia-south1:abc:default"
    p2 = r.page(2)
    assert p2 is not None and p2.text == ""  # only page 1 came back: nothing guessed


def test_photo_has_no_page_selector() -> None:
    pytest.importorskip("google.cloud.documentai_v1")
    client = FakeClient()
    DocumentAiOcr("p", "asia-south1", "a", client=client).read(b"\xff\xd8\xff", "image/jpeg", [1])
    assert not client.requests[0].process_options.individual_page_selector.pages


@pytest.mark.parametrize(
    ("media", "pages", "msg"),
    [
        ("application/pdf", [], "no pages"),
        ("application/pdf", list(range(1, 17)), "online limit"),
        ("application/msword", [1], "not supported"),
    ],
)
def test_requests_ocr_cannot_serve_are_refused(media: str, pages: list[int], msg: str) -> None:
    with pytest.raises(OcrError, match=msg):
        DocumentAiOcr("p", "l", "x", client=FakeClient()).read(b"x", media, pages)


def test_a_failed_call_names_the_error_type_only() -> None:
    pytest.importorskip("google.cloud.documentai_v1")
    with pytest.raises(OcrError) as e:
        DocumentAiOcr("p", "l", "x", client=FakeClient(fail=True)).read(
            b"%PDF", "application/pdf", [1]
        )
    assert "RuntimeError" in str(e.value) and "secret" not in str(e.value)


def test_engine_needs_project_location_and_processor() -> None:
    with pytest.raises(OcrError):
        DocumentAiOcr("p", "", "x")


# ---- caching and configuration ---------------------------------------------------------------


class CountingLive(DocumentAiOcr):
    def __init__(self) -> None:
        super().__init__("p", "asia-south1", "x")
        self.calls = 0

    def raw(self, data: bytes, media_type: str, pages: Sequence[int]) -> dict[str, Any]:
        self.calls += 1
        return DOC


def test_cache_bills_each_file_once_and_replays(tmp_path: Path) -> None:
    live = CountingLive()
    cached = CachingOcr(live, tmp_path)
    a = cached.read(b"scan-1", "application/pdf", [1])
    b = cached.read(b"scan-1", "application/pdf", [1])
    assert a == b and live.calls == 1 and len(list(tmp_path.glob("processor-default/*.json"))) == 1
    replay = RecordedOcr(
        {p.stem: json.loads(p.read_text()) for p in tmp_path.glob("*/*.json")}, "r"
    )
    assert replay.read(b"scan-1", "application/pdf", [1]).pages == a.pages
    with pytest.raises(OcrError):
        replay.read(b"never-seen", "application/pdf", [1])


def test_settings_pick_the_engine_and_fail_closed(tmp_path: Path) -> None:
    assert ocr_from_settings(Settings(ocr_provider="none")) is None
    rec = ocr_from_settings(Settings(ocr_provider="recorded", ocr_recorded_dir=tmp_path))
    assert isinstance(rec, RecordedOcr)
    with pytest.raises(OcrError):  # live without a processor ID: refuse at startup
        ocr_from_settings(Settings(ocr_provider="documentai", gcp_region="asia-south1"))
    live = ocr_from_settings(
        Settings(
            ocr_provider="documentai",
            gcp_project_id="p",
            gcp_region="asia-south1",
            docai_ocr_processor_id="93ce",
            ocr_recorded_dir=tmp_path,
        )
    )
    assert (
        isinstance(live, CachingOcr)
        and live.name == "documentai:asia-south1:93ce:pretrained-ocr-v2.1.1-2025-01-31"
    )  # pinned default


# ---- pipeline: draft → review → confirmed → indexed --------------------------------------------


class FakeEngine:
    """Stands in for Document AI: returns the hand transcription as the OCR text (TEST ONLY)."""

    def __init__(self, conf: float | None = 0.95, fail: bool = False) -> None:
        self.conf, self.fail, self.calls = conf, fail, 0

    def read(self, data: bytes, media_type: str, pages: Sequence[int]) -> OcrResult:
        self.calls += 1
        if self.fail:
            raise OcrError("Document AI call failed: DeadlineExceeded")
        did = next(d for d, r in IDX.items() if (CORPUS / r["file"]).read_bytes() == data)
        text = (CORPUS / "ground_truth" / "text" / f"{did}.txt").read_text("utf-8")
        return OcrResult(
            engine="fake",
            pages=tuple(
                OcrPage(page=n, text=text if n == pages[0] else "", confidence=self.conf)
                for n in pages
            ),
        )


def _run(stores: IngestionStores, did: str, engine: Any, threshold: float | None = None) -> Any:
    return ingest(
        _src(did),
        (CORPUS / IDX[did]["file"]).read_bytes(),
        stores=stores,
        departments=DEPTS,
        hierarchy=HIER,
        confidence_threshold=threshold,
        ocr=engine,
    )


def _confirm(stores: IngestionStores, did: str, **kw: Any) -> Any:
    return confirm_extraction(
        _src(did),
        (CORPUS / IDX[did]["file"]).read_bytes(),
        reviewer="U02",
        reason="checked against the scan",
        at=T0 + dt.timedelta(hours=1),
        stores=stores,
        departments=DEPTS,
        hierarchy=HIER,
        confidence_threshold=None,
        **kw,
    )


def test_ocr_draft_waits_for_review_while_the_gate_is_uncalibrated() -> None:
    stores, eng = IngestionStores(), FakeEngine()
    res = _run(stores, "D09", eng)
    data = (CORPUS / IDX["D09"]["file"]).read_bytes()
    assert res.status is IngestStatus.HELD and len(stores.index) == 0
    assert [i.kind for i in res.review_items] == [ReviewKind.LOW_CONFIDENCE_EXTRACTION]
    assert _version(data) in stores.ocr_drafts  # the reviewer has the draft to check
    assert _run(stores, "D09", eng).status is IngestStatus.DUPLICATE and eng.calls == 1


def test_reviewer_confirms_and_the_scan_is_indexed_under_its_own_version() -> None:
    stores = IngestionStores()
    held = _run(stores, "D09", FakeEngine())
    res = _confirm(stores, "D09")
    assert res.status is IngestStatus.INDEXED and res.canonical_id
    assert res.version == held.version  # preview serves the scan itself (ADR-0014)
    item = next(i for i in stores.queue.history() if i.item_id == held.review_items[0].item_id)
    assert (item.state, item.reviewer) == (ReviewState.CONFIRMED, "U02")
    assert "GOVERNMENT" in stores.text_of[res.version].upper()


def test_reviewer_correction_is_what_gets_indexed() -> None:
    stores = IngestionStores()
    _run(stores, "D09", FakeEngine())
    corrected = (CORPUS / "ground_truth" / "text" / "D09.txt").read_text("utf-8") + "\n(corrected)"
    res = _confirm(stores, "D09", corrected_text=corrected)
    assert res.status is IngestStatus.INDEXED and stores.text_of[res.version] == corrected


class MarkerEngine:
    """TEST ONLY: page text is a fixed marker, so the merge order is visible."""

    def read(self, data: bytes, media_type: str, pages: Sequence[int]) -> OcrResult:
        return OcrResult(
            engine="fake",
            pages=tuple(OcrPage(page=n, text=f"[OCR PAGE {n}]", confidence=0.9) for n in pages),
        )


def test_mixed_pdf_merges_native_and_ocr_pages_in_order() -> None:
    stores = IngestionStores()
    held = _run(stores, "D15", MarkerEngine())
    assert [p.page for p in stores.ocr_drafts[held.version].pages] == [2]  # only the scanned page
    res = _confirm(stores, "D15")
    text = stores.text_of[res.version]
    assert res.status is IngestStatus.INDEXED
    assert text.startswith("GOVERNMENT OF ANDHRA PRADESH") and text.endswith("[OCR PAGE 2]")


def test_ocr_failure_holds_the_file_and_stores_no_draft() -> None:
    stores = IngestionStores()
    res = _run(stores, "D09", FakeEngine(fail=True))
    assert res.status is IngestStatus.HELD and not stores.ocr_drafts
    assert res.review_items[0].reason == "OCR failed: Document AI call failed: DeadlineExceeded"
    with pytest.raises(ConfirmError):  # nothing to confirm without a draft or reviewer text
        _confirm(stores, "D09")


def test_calibrated_gate_indexes_confident_ocr_and_holds_weak_ocr() -> None:
    sure, weak = IngestionStores(), IngestionStores()
    assert _run(sure, "D09", FakeEngine(conf=0.97), threshold=0.9).status is IngestStatus.INDEXED
    assert _run(weak, "D09", FakeEngine(conf=0.6), threshold=0.9).status is IngestStatus.HELD


def test_no_confidence_from_the_engine_is_never_trusted() -> None:
    stores = IngestionStores()
    assert _run(stores, "D09", FakeEngine(conf=None), threshold=0.5).status is IngestStatus.HELD


def test_confirm_needs_a_pending_review_and_non_empty_text() -> None:
    stores = IngestionStores()
    with pytest.raises(ConfirmError):
        _confirm(stores, "D09")  # never ingested
    _run(stores, "D09", FakeEngine())
    with pytest.raises(ConfirmError):
        _confirm(stores, "D09", corrected_text="   ")
    _confirm(stores, "D09")
    with pytest.raises(ConfirmError):
        _confirm(stores, "D09")  # already decided


V2 = "pretrained-ocr-v2.1.1-2025-01-31"


class VersionClient(FakeClient):
    def processor_version_path(self, project: str, location: str, processor: str, v: str) -> str:
        return f"{self.processor_path(project, location, processor)}/processorVersions/{v}"


def test_a_pinned_model_version_is_what_gets_called_and_cached_apart(tmp_path: Path) -> None:
    """Probe, 11 Nov 2026: the processor default (OCR v1.0, 2020) cannot read Telugu; v2.1.1 can.
    The version is pinned in config, sent on every call, and its responses are cached separately."""
    pytest.importorskip("google.cloud.documentai_v1")
    client = VersionClient()
    eng = DocumentAiOcr("p", "asia-south1", "abc", processor_version=V2, client=client)
    r = eng.read(b"%PDF-1.4", "application/pdf", [1])
    assert client.requests[0].name.endswith(f"/processors/abc/processorVersions/{V2}")
    assert r.engine == f"documentai:asia-south1:abc:{V2}"
    cached = CachingOcr(eng, tmp_path)
    cached.read(b"scan-x", "application/pdf", [1])
    assert [p.parent.name for p in tmp_path.glob("*/*.json")] == [V2]
    rec = ocr_from_settings(
        Settings(ocr_provider="recorded", ocr_recorded_dir=tmp_path, docai_ocr_processor_version=V2)
    )
    assert isinstance(rec, RecordedOcr) and rec.read(b"scan-x", "application/pdf", [1]).pages


def _line(text: str, start: int, x0: float, y0: float, x1: float, y1: float) -> dict[str, Any]:
    box = [{"x": x0, "y": y0}, {"x": x1, "y": y0}, {"x": x1, "y": y1}, {"x": x0, "y": y1}]
    return {
        "layout": {
            "text_anchor": {
                "text_segments": [{"start_index": str(start), "end_index": str(start + len(text))}]
            },
            "bounding_poly": {"normalized_vertices": box},
        }
    }


def test_rows_are_rebuilt_from_geometry_so_dated_rejoins_its_number() -> None:
    """v2.1.1 emitted "Dated:" (right column) after the "Read the following" block; geometry puts it
    back on the number's row. Lines on different rows never merge."""
    parts = ["G.O.Ms.No.62", "Read the following:", "Dated: 14-06-2019"]
    text = "\n".join(parts)
    starts = [text.index(p) for p in parts]
    lines = [
        _line(parts[0], starts[0], 0.10, 0.200, 0.30, 0.212),
        _line(parts[1], starts[1], 0.10, 0.230, 0.40, 0.242),
        _line(parts[2], starts[2], 0.65, 0.201, 0.90, 0.213),
    ]
    doc = {"text": text, "pages": [{"page_number": 1, "lines": lines, "layout": {}}]}
    assert parse_document(doc, "e", [1]).pages[0].text == (
        "G.O.Ms.No.62 Dated: 14-06-2019\nRead the following:"
    )


def test_no_line_geometry_falls_back_to_text_order() -> None:
    assert parse_document(DOC, "e", [1]).pages[0].text == TEXT
