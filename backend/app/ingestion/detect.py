"""Detect-first format routing (plan §4.1; CLAUDE.md §5.1).

The true type comes from the file's content, never its extension: a `.pdf` can be image-only, a
`.docx` can be anything. PDFs are inspected page by page so one document can use several paths.
No tuned thresholds: a page has a text layer, images, both, or neither.

Routes: native · ocr · ocr_preprocess (photos) · per_page (mixed PDF) · table · unsupported.
A page with BOTH text and images (e.g. a searchable scan) is routed to OCR: a text layer of unknown
origin is not trusted as exact text. Unsupported or unreadable files go to the review queue.
"""

from __future__ import annotations

import csv
import io
import zipfile
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict
from pypdf import PdfReader
from pypdf.errors import PdfReadError


class Kind(StrEnum):
    PDF = "pdf"
    JPEG = "jpeg"
    PNG = "png"
    HEIC = "heic"
    DOCX = "docx"
    XLSX = "xlsx"
    CSV = "csv"
    TXT = "txt"
    UNKNOWN = "unknown"


class PageKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    TEXT_AND_IMAGE = "text_and_image"  # searchable scan / figures: OCR, text layer not trusted
    BLANK = "blank"


class Route(StrEnum):
    NATIVE = "native"
    OCR = "ocr"
    OCR_PREPROCESS = "ocr_preprocess"
    PER_PAGE = "per_page"
    TABLE = "table"
    UNSUPPORTED = "unsupported"


class Detection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Kind
    route: Route
    pages: tuple[PageKind, ...] = ()  # PDFs only
    ocr_pages: tuple[int, ...] = ()  # 1-based page numbers that need OCR
    extension_mismatch: bool = False
    reason: str = ""


_EXT = {
    ".pdf": Kind.PDF,
    ".jpg": Kind.JPEG,
    ".jpeg": Kind.JPEG,
    ".png": Kind.PNG,
    ".heic": Kind.HEIC,
    ".heif": Kind.HEIC,
    ".docx": Kind.DOCX,
    ".xlsx": Kind.XLSX,
    ".csv": Kind.CSV,
    ".txt": Kind.TXT,
}


def _sniff(data: bytes) -> Kind:
    if not data.strip():
        return Kind.UNKNOWN
    if data.startswith(b"%PDF-"):
        return Kind.PDF
    if data.startswith(b"\xff\xd8\xff"):
        return Kind.JPEG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return Kind.PNG
    if data[4:8] == b"ftyp" and data[8:12] in {b"heic", b"heix", b"mif1", b"msf1", b"heif"}:
        return Kind.HEIC
    if data.startswith(b"PK\x03\x04"):
        try:
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
        except zipfile.BadZipFile:
            return Kind.UNKNOWN
        if "word/document.xml" in names:
            return Kind.DOCX
        if "xl/workbook.xml" in names:
            return Kind.XLSX
        return Kind.UNKNOWN
    try:
        text = data[:65536].decode("utf-8")
    except UnicodeDecodeError:
        return Kind.UNKNOWN
    if "\x00" in text:
        return Kind.UNKNOWN
    try:
        sample = text[:4096]
        if sample.strip() and "," in sample and csv.Sniffer().sniff(sample, delimiters=",;\t"):
            rows = list(csv.reader(io.StringIO(sample)))
            widths = {len(r) for r in rows[:10] if r}
            if len(widths) == 1 and widths.pop() > 1:
                return Kind.CSV
    except csv.Error:
        pass
    return Kind.TXT


def _pdf_pages(data: bytes) -> tuple[PageKind, ...]:
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise PdfReadError("encrypted PDF")
    out = []
    for page in reader.pages:
        has_text = bool((page.extract_text() or "").strip())
        has_image = len(page.images) > 0
        out.append(
            PageKind.TEXT_AND_IMAGE
            if has_text and has_image
            else PageKind.TEXT
            if has_text
            else PageKind.IMAGE
            if has_image
            else PageKind.BLANK
        )
    return tuple(out)


def detect(data: bytes, filename: str = "") -> Detection:
    """Route a file by its content (plan §4.1). Never raises: failures become UNSUPPORTED."""
    kind = _sniff(data)
    declared = _EXT.get(Path(filename).suffix.lower())
    mismatch = declared is not None and declared is not kind
    if kind is Kind.PDF:
        try:
            pages = _pdf_pages(data)
        except (PdfReadError, ValueError, KeyError, OSError) as exc:
            return Detection(
                kind=kind,
                route=Route.UNSUPPORTED,
                extension_mismatch=mismatch,
                reason=f"unreadable PDF: {type(exc).__name__}",
            )
        ocr = tuple(
            i for i, p in enumerate(pages, 1) if p in (PageKind.IMAGE, PageKind.TEXT_AND_IMAGE)
        )
        text = [p for p in pages if p is PageKind.TEXT]
        if not ocr and not text:
            route, reason = Route.UNSUPPORTED, "no text and no images on any page"
        elif not ocr:
            route, reason = Route.NATIVE, "text layer on every page"
        elif not text:
            route, reason = Route.OCR, "image-only pages"
        else:
            route, reason = Route.PER_PAGE, "text pages and image pages"
        return Detection(
            kind=kind,
            route=route,
            pages=pages,
            ocr_pages=ocr,
            extension_mismatch=mismatch,
            reason=reason,
        )
    route = {
        Kind.JPEG: Route.OCR_PREPROCESS,
        Kind.PNG: Route.OCR_PREPROCESS,
        Kind.HEIC: Route.OCR_PREPROCESS,
        Kind.DOCX: Route.NATIVE,
        Kind.TXT: Route.NATIVE,
        Kind.XLSX: Route.TABLE,
        Kind.CSV: Route.TABLE,
        Kind.UNKNOWN: Route.UNSUPPORTED,
    }[kind]
    return Detection(
        kind=kind, route=route, extension_mismatch=mismatch, reason="content type " + kind.value
    )


def detect_file(path: Path) -> Detection:
    return detect(path.read_bytes(), path.name)
