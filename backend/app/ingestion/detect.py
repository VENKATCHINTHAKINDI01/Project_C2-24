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
import hashlib
import io
import json
import re
import threading
import zipfile
from collections import OrderedDict
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict
from pypdf import PageObject, PdfReader
from pypdf import __version__ as pypdf_version
from pypdf.errors import PdfReadError
from pypdf.generic import DictionaryObject, StreamObject


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


_SCANS: OrderedDict[bytes, tuple[tuple[str, bool], ...]] = OrderedDict()
_SCANS_MAX = 32  # recent files only: keyed by digest, so the file bytes are not kept alive
_SCANS_LOCK = threading.Lock()


def pdf_scan(data: bytes) -> tuple[tuple[str, bool], ...]:
    """(text layer, carries an image) for each page of a PDF, read once per file.

    Detection, native extraction and the metadata rules all need a PDF's page texts; pypdf's
    text extraction is the slowest step of ingestion, so a file's pages are read once and the
    result reused while the same bytes are being ingested (the sandbox build read every PDF
    three times). Pure: the same bytes always give the same answer."""
    key = hashlib.sha256(data).digest()
    with _SCANS_LOCK:
        if key in _SCANS:
            _SCANS.move_to_end(key)
            return _SCANS[key]
    scan = _saved_scan(key) or _read_pdf(data)
    with _SCANS_LOCK:
        _SCANS[key] = scan
        while len(_SCANS) > _SCANS_MAX:
            _SCANS.popitem(last=False)
    return scan


_INLINE_IMAGE = re.compile(rb"(?:^|[\s\]\)>}])BI[\s/]")


def _xobject_image(obj: Any, seen: set[Any]) -> bool:
    """An image XObject in these resources or in any form inside them — the same set pypdf's
    `page.images` lists, without parsing the content stream."""
    if "/Resources" not in obj:
        return False
    res = obj["/Resources"]
    res = res.get_object() if res is not None else None
    if not isinstance(res, DictionaryObject) or "/XObject" not in res:
        return False
    xo = res["/XObject"].get_object()
    if not isinstance(xo, DictionaryObject):
        return False
    for name in xo:
        entry = xo[name]
        if not isinstance(entry, StreamObject):
            continue
        if entry.get("/Subtype", "") == "/Image":
            return True
        ref = entry.indirect_reference
        if ref is not None and ref in seen:
            continue
        seen.add(ref)
        if _xobject_image(entry, seen):
            return True
    return False


def _has_image(page: PageObject) -> bool:
    """Whether `page.images` would list anything (detection result unchanged), at a fraction of
    the cost: listing images makes pypdf parse the whole content stream a second time. Only a
    page whose content may hold an inline image (a `BI` operator) is asked the slow way."""
    try:
        if _xobject_image(page, {page.indirect_reference}):
            return True
        content = page.get_contents()
        raw = content.get_data() if content is not None else b""
        return bool(_INLINE_IMAGE.search(raw)) and len(page.images) > 0
    except ImportError:
        # pypdf needs an image library to list inline images; one is there, so the page is
        # treated as carrying an image (it goes to OCR rather than being trusted as text)
        return True


def _read_pdf(data: bytes) -> tuple[tuple[str, bool], ...]:
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        raise PdfReadError("encrypted PDF")
    return tuple((page.extract_text() or "", _has_image(page)) for page in reader.pages)


# Saved page reads (ADR-0028 addendum 2): the graph job writes `<sha256>.json` for every public
# order it reads; the sandbox service reads them (read-only mount) instead of parsing the same
# PDFs again at every cold start. A saved read is used only if it was made by the same pypdf
# version — then it is exactly what parsing would give — and is keyed by the file's own hash.
SCAN_FORMAT = 1
_SCAN_DIR: Path | None = None


def use_saved_scans(directory: Path | None) -> None:
    global _SCAN_DIR  # noqa: PLW0603 — process-wide setting made once at startup
    _SCAN_DIR = directory


def scan_record(data: bytes) -> tuple[str, dict[str, Any]]:
    """File name and content of a saved read of this PDF (for the graph job to write)."""
    pages = pdf_scan(data)
    return f"{hashlib.sha256(data).hexdigest()}.json", {
        "format": SCAN_FORMAT,
        "pypdf": pypdf_version,
        "pages": [[t, im] for t, im in pages],
    }


def _saved_scan(key: bytes) -> tuple[tuple[str, bool], ...] | None:
    if _SCAN_DIR is None:
        return None
    path = _SCAN_DIR / f"{key.hex()}.json"
    try:
        rec = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None  # not saved (or unreadable): parse the PDF as usual
    if rec.get("format") != SCAN_FORMAT or rec.get("pypdf") != pypdf_version:
        return None
    pages = rec.get("pages")
    if not isinstance(pages, list) or not all(
        isinstance(p, list) and len(p) == 2 and isinstance(p[0], str) and isinstance(p[1], bool)
        for p in pages
    ):
        return None
    return tuple((str(t), bool(im)) for t, im in pages)


def _pdf_pages(data: bytes) -> tuple[PageKind, ...]:
    out = []
    for text, has_image in pdf_scan(data):
        has_text = bool(text.strip())
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
