"""Telugu order headers (plan §4.1 "Telugu/English", §4.3, §4.4): D16, the Commissioner's Rc. on
emergency works, is written in Telugu. Its number line, date, subject and reference must resolve
to the same canonical IDs as English orders — never by guessing a department."""

from __future__ import annotations

import datetime as dt

from app.identifiers.resolver import resolve_reference
from app.ingestion.metadata import DocType, RelKind, extract_metadata
from app.ingestion.pipeline import IngestionStores, IngestStatus
from tests.unit.mock_access import CORPUS
from tests.unit.test_ingestion_pipeline import DEPTS, _ingest, _src

D16 = (CORPUS / "ground_truth" / "text" / "D16.txt").read_text("utf-8")


def test_telugu_rc_header_resolves() -> None:
    m = extract_metadata(D16, DEPTS)
    assert m.canonical_id == "AP-USD01-RC-USD01WRKS0-22-2025-D20250602"  # ADR-0007 date tag
    assert m.doc_type is DocType.CIRCULAR
    assert m.issue_date == dt.date(2025, 6, 2)
    assert m.department == "USD01" and m.department_source == "text"
    assert (m.subject or "").startswith("వర్షాకాలం – అత్యవసర పనులు")
    assert m.review_reasons == ()


def test_telugu_reference_resolves_with_its_named_department() -> None:
    m = extract_metadata(D16, DEPTS)
    assert [r.canonical_id for r in m.references] == ["AP-USD01-GOMS-27-2024"]
    refs = [r for r in m.relations if r.kind is RelKind.REFERENCES]
    assert [r.target for r in refs] == ["AP-USD01-GOMS-27-2024"]


def test_unknown_telugu_department_is_never_guessed() -> None:
    raw = "జి.ఓ.ఎం.ఎస్.నెం.27, తెలియని శాఖ, తేది: 06.08.2024."
    assert resolve_reference(raw, DEPTS, "USD01").canonical_id is None  # names a dept we can't map
    named = "జి.ఓ.ఎం.ఎస్.నెం.27, పట్టణ సేవల (వర్క్స్) శాఖ, తేది: 06.08.2024."
    assert resolve_reference(named, DEPTS, "FIN01").canonical_id == "AP-USD01-GOMS-27-2024"


def test_english_headers_are_untouched() -> None:
    d04 = extract_metadata((CORPUS / "ground_truth" / "text" / "D04.txt").read_text(), DEPTS)
    assert d04.canonical_id == "AP-FIN01-GOMS-31-2025" and d04.subject is not None
    assert d04.subject.startswith("Public Services")


def test_d16_is_indexed_once_its_text_is_confirmed() -> None:
    stores = IngestionStores()
    photo = _ingest(stores, "D16")  # JPG: needs OCR → held, as before
    assert photo.status is IngestStatus.HELD
    res = _ingest(
        stores,
        "D16",
        data=D16.encode("utf-8"),
        src=_src("D16", uri="mock://D16#confirmed-text").model_copy(update={"filename": "D16.txt"}),
    )
    assert res.status is IngestStatus.INDEXED
    assert res.canonical_id == "AP-USD01-RC-USD01WRKS0-22-2025-D20250602"
