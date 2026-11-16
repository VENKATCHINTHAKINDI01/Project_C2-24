"""Reading a PDF's pages once (plan §4.1 detection; ADR-0028 addendum 2): the fast image check
must say exactly what pypdf's `page.images` says, and a saved read is used only when it is
exactly what parsing would give."""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from app.ingestion import detect as d

FONT = DictionaryObject(
    {
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }
)


def _image(w: PdfWriter) -> object:
    img = DecodedStreamObject()
    img.set_data(b"\x00\x00\x00\xff\xff\xff")
    img.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(2),
            NameObject("/Height"): NumberObject(1),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    return w._add_object(img)  # noqa: SLF001 — test PDF construction


def _page(w: PdfWriter, content: bytes, xobjects: dict[str, object] | None = None) -> None:
    page = w.add_blank_page(200, 200)
    res = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): FONT})})
    if xobjects:
        res[NameObject("/XObject")] = DictionaryObject(
            {NameObject(k): v for k, v in xobjects.items()}
        )
    page[NameObject("/Resources")] = res
    stream = DecodedStreamObject()
    stream.set_data(content)
    page[NameObject("/Contents")] = w._add_object(stream)  # noqa: SLF001


def _pdf() -> bytes:
    w = PdfWriter()
    text = b"BT /F1 12 Tf 20 100 Td (G.O.Ms.No.31 BI test) Tj ET"
    _page(w, text)  # 1 text only; the string even holds "BI "
    _page(w, b"q 100 0 0 100 0 0 cm /Im1 Do Q", {"/Im1": _image(w)})  # 2 image XObject
    form = DecodedStreamObject()
    form.set_data(b"/Im2 Do")
    form.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject([NumberObject(0)] * 4),
            NameObject("/Resources"): DictionaryObject(
                {NameObject("/XObject"): DictionaryObject({NameObject("/Im2"): _image(w)})}
            ),
        }
    )
    _page(w, b"/Fm1 Do " + text, {"/Fm1": w._add_object(form)})  # noqa: SLF001 — 3 in a form
    _page(w, b"q BI /W 1 /H 1 /CS /G /BPC 8 ID \x80 EI Q")  # 4 inline image
    _page(w, b"")  # 5 blank
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _clean() -> Iterator[None]:
    d._SCANS.clear()  # noqa: SLF001
    yield
    d.use_saved_scans(None)
    d._SCANS.clear()  # noqa: SLF001


def test_the_fast_image_check_says_what_pypdf_says() -> None:
    data = _pdf()
    for page in PdfReader(io.BytesIO(data)).pages:
        try:
            slow = len(page.images) > 0
        except ImportError:
            slow = True
        fast = d._has_image(PdfReader(io.BytesIO(data)).pages[page.page_number])  # noqa: SLF001
        assert fast is slow, page.page_number
    det = d.detect(data, "x.pdf")
    assert det.ocr_pages == (2, 3, 4)  # XObject image, image inside a form, inline image
    assert det.pages[0] is d.PageKind.TEXT and det.pages[4] is d.PageKind.BLANK


def test_each_pdf_is_read_once_per_file() -> None:
    data = _pdf()
    calls = []
    real = d._read_pdf  # noqa: SLF001
    d._read_pdf = lambda b: calls.append(1) or real(b)  # type: ignore[assignment]
    try:
        d.detect(data, "a.pdf")
        d.pdf_scan(bytes(data))  # a copy of the same bytes
    finally:
        d._read_pdf = real  # type: ignore[assignment]
    assert calls == [1]


def test_a_saved_read_is_used_only_when_parsing_would_give_the_same(tmp_path: Path) -> None:
    data = _pdf()
    name, rec = d.scan_record(data)
    assert rec["pages"][0][0].startswith("G.O.Ms.No.31")
    (tmp_path / name).write_text(json.dumps(rec))
    d._SCANS.clear()  # noqa: SLF001
    d.use_saved_scans(tmp_path)
    real = d._read_pdf  # noqa: SLF001

    def no_parse(_b: bytes) -> tuple[tuple[str, bool], ...]:
        raise AssertionError("parsed although a saved read exists")

    d._read_pdf = no_parse  # type: ignore[assignment]
    try:
        assert d.pdf_scan(data) == tuple((t, im) for t, im in rec["pages"])
    finally:
        d._read_pdf = real  # type: ignore[assignment]
    # made by another pypdf version, or damaged: parsed as usual
    for bad in ({**rec, "pypdf": "0.0.1"}, {**rec, "pages": [["x", "yes"]]}, "not json"):
        d._SCANS.clear()  # noqa: SLF001
        (tmp_path / name).write_text(bad if isinstance(bad, str) else json.dumps(bad))
        assert d.pdf_scan(data) == tuple((t, im) for t, im in rec["pages"])
