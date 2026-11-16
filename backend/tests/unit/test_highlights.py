"""Citation spans, the highlight function's fail-closed path, and content sniffing for the document
store (ADR-0014, ADR-0015). HTTP behaviour and the leakage paths are in test_sandbox_api.py."""

from __future__ import annotations

import datetime as dt

import pytest

from app.auth.policy import ScopeError
from app.auth.store import InMemoryAuthzStore
from app.conflict.highlights import highlight_citations
from app.identifiers.resolver import load_departments
from app.ingestion.document_store import (
    InMemoryDocumentStore,
    StoredDocument,
    extension,
    media_type,
)
from app.ingestion.metadata import citation_spans
from tests.unit.mock_access import CLASSES, ONTOLOGY, POLICY

NOTE = (
    "2. As per para 2(v) of G.O.Ms.No.88, Finance (HR.I-Plg. & Policy) Department,\n"
    "   Dt.03-06-2022 (Flag B), spouse cases get preference. See also\n"
    "file No. FIN01-HRPLG0TRF/3/2025-HR.I and Standing Order No.2/2020."
)


def test_spans_point_at_citations_that_wrap_across_lines() -> None:
    spans = citation_spans(NOTE)
    assert [s.kind for s in spans] == ["order", "efile", "order"]
    go = spans[0]
    assert NOTE[go.start : go.end].startswith("G.O.Ms.No.88") and "\n" in NOTE[go.start : go.end]
    assert NOTE[go.end - 10 : go.end] == "03-06-2022"
    assert go.raw == "G.O.Ms.No.88, Finance (HR.I-Plg. & Policy) Department, Dt.03-06-2022"
    assert NOTE[spans[1].start : spans[1].end] == spans[1].raw == "FIN01-HRPLG0TRF/3/2025-HR.I"
    assert NOTE[spans[2].start : spans[2].end] == "Standing Order No.2/2020"


def test_no_citations_no_spans() -> None:
    assert citation_spans("1. Put up for orders.") == []
    assert citation_spans("") == []


def test_no_valid_scope_fails_closed() -> None:
    with pytest.raises(ScopeError):
        highlight_citations(
            NOTE,
            dt.date(2026, 10, 2),
            default_dept="FIN01",
            departments=load_departments(ONTOLOGY / "departments.yaml"),
            user_id="U99",
            instruments={},
            relations=[],
            tags_of={},
            store=InMemoryAuthzStore([]),
            policy=POLICY,
            classification=CLASSES,
        )


@pytest.mark.parametrize(
    ("data", "name", "expected"),
    [
        (b"%PDF-1.7\n...", "x.pdf", "application/pdf"),
        (b"%PDF-1.4", "looks.docx", "application/pdf"),  # content wins over the extension
        (b"\xff\xd8\xff\xe0....", "scan.jpg", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n...", "a.png", "image/png"),
        (
            b"PK\x03\x04...",
            "note.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            b"PK\x03\x04...",
            "sheet.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
        (b"PK\x03\x04...", "archive.zip", "application/octet-stream"),
        (b"<html>", "x.pdf", "application/octet-stream"),  # a .pdf name proves nothing
    ],
)
def test_media_type_is_sniffed_from_content(data: bytes, name: str, expected: str) -> None:
    assert media_type(data, name) == expected


def test_only_pdf_and_images_preview_and_names_follow_type() -> None:
    def doc(m: str) -> StoredDocument:
        return StoredDocument(version="v", media_type=m, data=b"")

    assert doc("application/pdf").previewable and doc("image/jpeg").previewable
    assert not doc(media_type(b"PK\x03\x04", "a.docx")).previewable
    assert extension("application/pdf") == ".pdf" and extension("text/html") == ".bin"


def test_store_is_content_addressed() -> None:
    s = InMemoryDocumentStore()
    s.put(StoredDocument(version="v1", media_type="application/pdf", data=b"%PDF-a"))
    s.put(StoredDocument(version="v1", media_type="application/pdf", data=b"%PDF-b"))
    got = s.get("v1")
    assert got is not None and got.data == b"%PDF-a"
    assert s.get("v2") is None
