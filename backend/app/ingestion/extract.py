"""Native extraction: PDF text layer, DOCX, XLSX, TXT, CSV (plan §4.1). Standard library + pypdf.

Pages routed to OCR by `detect` are returned as NEEDS_OCR with no text: Document AI fills them in
later (GCP). Nothing here guesses text for an image. Layout is kept as line breaks so headers,
"Read the following" lists and numbered paragraphs survive for metadata extraction (§4.3).
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from enum import StrEnum
from xml.etree import ElementTree as ET  # noqa: S405 — parses only XML inside an uploaded zip

from pydantic import BaseModel, ConfigDict

from app.ingestion.detect import Detection, Kind, Route, pdf_scan


class PageSource(StrEnum):
    NATIVE = "native"
    NEEDS_OCR = "needs_ocr"


class ExtractedPage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    page: int
    source: PageSource
    text: str | None


class Table(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    rows: tuple[tuple[str, ...], ...]


class ExtractedDocument(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    pages: tuple[ExtractedPage, ...] = ()
    tables: tuple[Table, ...] = ()

    @property
    def native_text(self) -> str:
        return "\n".join(p.text for p in self.pages if p.text)

    @property
    def complete(self) -> bool:
        """False while any page still needs OCR."""
        return all(p.source is PageSource.NATIVE for p in self.pages)


class ExtractionError(Exception):
    """Content could not be read although detection accepted it; send the file to review."""


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_MAX_XML = 50_000_000  # refuse absurdly large parts (zip bombs)


def _xml(z: zipfile.ZipFile, name: str) -> ET.Element:
    info = z.getinfo(name)
    if info.file_size > _MAX_XML:
        raise ExtractionError(f"{name} too large")
    return ET.fromstring(z.read(name))  # noqa: S314 — stdlib parser does not resolve external entities


def _docx(data: bytes) -> ExtractedDocument:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        body = _xml(z, "word/document.xml")
    lines: list[str] = []
    for block in body.iter():
        if block.tag == f"{_W}p":
            lines.append(_para_text(block))
        elif block.tag == f"{_W}tr":
            cells = ["".join(t.text or "" for t in c.iter(f"{_W}t")) for c in block.iter(f"{_W}tc")]
            lines.append("\t".join(cells))
    # paragraphs inside table cells were also visited as <w:p>; keep the row form only
    text = "\n".join(_dedupe_table_paragraphs(lines))
    return ExtractedDocument(pages=(ExtractedPage(page=1, source=PageSource.NATIVE, text=text),))


def _para_text(p: ET.Element) -> str:
    """Run text in document order; <w:br/> → newline, <w:tab/> → tab (signature blocks use both)."""
    out: list[str] = []
    for el in p.iter():
        if el.tag == f"{_W}t":
            out.append(el.text or "")
        elif el.tag in (f"{_W}br", f"{_W}cr"):
            out.append("\n")
        elif el.tag == f"{_W}tab":
            out.append("\t")
    return "".join(out)


def _dedupe_table_paragraphs(lines: list[str]) -> list[str]:
    out: list[str] = []
    for ln in lines:
        if "\t" in ln:
            cells = [c for c in ln.split("\t") if c]
            while out and cells and out[-1] in cells:  # drop the cell paragraphs just emitted
                cells.remove(out.pop())
            out.append(ln)
        else:
            out.append(ln)
    return out


def _col(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref)
    n = 0
    for ch in letters.group(0) if letters else "A":
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _xlsx(data: bytes) -> ExtractedDocument:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in _xml(z, "xl/sharedStrings.xml").iter(f"{_S}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{_S}t")))
        wb = _xml(z, "xl/workbook.xml")
        names = [s.get("name", f"Sheet{i}") for i, s in enumerate(wb.iter(f"{_S}sheet"), 1)]
        sheets = sorted(n for n in z.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n))
        tables = []
        for i, part in enumerate(sorted(sheets, key=lambda n: int(re.findall(r"\d+", n)[-1]))):
            rows = []
            for row in _xml(z, part).iter(f"{_S}row"):
                cells: dict[int, str] = {}
                for c in row.iter(f"{_S}c"):
                    v = c.find(f"{_S}v")
                    f = c.find(f"{_S}f")
                    inline = c.find(f"{_S}is")
                    if c.get("t") == "s" and v is not None and v.text is not None:
                        val = shared[int(v.text)]
                    elif (v is None or v.text is None) and f is not None and f.text:
                        val = "=" + f.text  # formula without a cached result: keep, never invent
                    elif inline is not None:
                        val = "".join(t.text or "" for t in inline.iter(f"{_S}t"))
                    else:
                        val = v.text if v is not None and v.text is not None else ""
                    cells[_col(c.get("r", "A1"))] = val
                if cells:
                    rows.append(tuple(cells.get(j, "") for j in range(max(cells) + 1)))
            tables.append(Table(name=names[i] if i < len(names) else part, rows=tuple(rows)))
    text = "\n".join("\t".join(r) for t in tables for r in t.rows)
    return ExtractedDocument(
        pages=(ExtractedPage(page=1, source=PageSource.NATIVE, text=text),), tables=tuple(tables)
    )


def _pdf(data: bytes, detection: Detection) -> ExtractedDocument:
    ocr = set(detection.ocr_pages)
    pages = []
    for i, (text, _image) in enumerate(pdf_scan(data), 1):  # read once, shared with detect
        if i in ocr:
            pages.append(ExtractedPage(page=i, source=PageSource.NEEDS_OCR, text=None))
        else:
            pages.append(ExtractedPage(page=i, source=PageSource.NATIVE, text=text))
    return ExtractedDocument(pages=tuple(pages))


def pdf_text_layer(data: bytes, page: int) -> str:
    """The PDF's own text layer of one page, even on a page routed to OCR ("" when none or not a
    PDF). Printed text, not recognised text: used only where the metadata rules ask for it."""
    try:
        scan = pdf_scan(data)
        return scan[page - 1][0] if 1 <= page <= len(scan) else ""
    except Exception:  # noqa: BLE001 — not a PDF or unreadable: no layer, nothing guessed
        return ""


def extract_native(data: bytes, detection: Detection) -> ExtractedDocument:
    """Text for every natively readable page; OCR pages left empty and marked."""
    try:
        if detection.route is Route.UNSUPPORTED:
            raise ExtractionError(detection.reason or "unsupported")
        if detection.kind is Kind.PDF:
            return _pdf(data, detection)
        if detection.kind is Kind.DOCX:
            return _docx(data)
        if detection.kind is Kind.XLSX:
            return _xlsx(data)
        if detection.kind is Kind.CSV:
            rows = tuple(tuple(r) for r in csv.reader(io.StringIO(data.decode("utf-8"))))
            return ExtractedDocument(
                pages=(ExtractedPage(page=1, source=PageSource.NATIVE, text=data.decode("utf-8")),),
                tables=(Table(name="csv", rows=rows),),
            )
        if detection.kind is Kind.TXT:
            return ExtractedDocument(
                pages=(ExtractedPage(page=1, source=PageSource.NATIVE, text=data.decode("utf-8")),)
            )
        # photos: one page, OCR only
        return ExtractedDocument(
            pages=(ExtractedPage(page=1, source=PageSource.NEEDS_OCR, text=None),)
        )
    except ExtractionError:
        raise
    except (zipfile.BadZipFile, ET.ParseError, KeyError, ValueError, IndexError) as exc:
        raise ExtractionError(f"unreadable {detection.kind.value}: {type(exc).__name__}") from exc
