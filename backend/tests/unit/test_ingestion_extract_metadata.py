"""Native extraction + type / metadata / relation extraction on every readable corpus file
(plan §4.1, §4.3, §13.2 'Extraction', 'Canonical IDs'). Expected values come from the corpus index
and ground_truth/relations.csv (tests only). Every known difference is listed and explained.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile

import pytest

from app.config import REPO_ROOT
from app.identifiers.canonical import lookup_keys
from app.identifiers.resolver import load_departments
from app.ingestion.detect import detect, detect_file
from app.ingestion.extract import ExtractionError, PageSource, extract_native
from app.ingestion.metadata import DocType, RelKind, extract_metadata
from tests.unit.mock_access import CORPUS, rows

DEPTS = load_departments(REPO_ROOT / "data" / "ontology" / "departments.yaml")
IDX = {r["id"]: r for r in rows("documents_index.csv")}
BY_CID = {r["canonical_id"]: d for d, r in IDX.items()}
RELS = rows("ground_truth/relations.csv")
EDGE_KINDS = {"SUPERSEDES", "AMENDS", "CLARIFIES", "REFERENCES", "CITES"}


def _extract(did: str):  # type: ignore[no-untyped-def]
    path = CORPUS / IDX[did]["file"]
    return extract_native(path.read_bytes(), detect_file(path))


NATIVE = [d for d in IDX if _extract(d).native_text.strip()]
OCR_ONLY = sorted(set(IDX) - set(NATIVE))
META = {d: extract_metadata(_extract(d).native_text, DEPTS) for d in NATIVE}

# Known, explained differences from the corpus index (never "fixed" by guessing):
TYPE_EXCEPTIONS = {"D28": "no draft marker in the PDF text; draft status is not inferable"}
EXTRA_OUTSIDE_CORPUS = {
    "D06": "AP-FIN01-GOMS-151-2006",  # cited order not in the mock corpus
    "D27": "AP-FIN01-GOMS-104-2026",  # the planted missing authority (type E)
}
FILE_CITATIONS = {"D20": ("file:USD01-31/4/2025-VIG", "D21")}  # resolved via the file index later


def test_scans_and_photos_produce_no_text_until_ocr() -> None:
    assert OCR_ONLY == ["D01", "D02", "D09", "D11", "D13", "D16", "D22"]
    for did in OCR_ONLY:
        assert all(p.source is PageSource.NEEDS_OCR and p.text is None for p in _extract(did).pages)


def test_mixed_pdf_keeps_page_order_and_leaves_scanned_page_for_ocr() -> None:
    ex = _extract("D15")
    assert [(p.page, p.source) for p in ex.pages] == [
        (1, PageSource.NATIVE),
        (2, PageSource.NEEDS_OCR),
    ]
    assert not ex.complete


@pytest.mark.parametrize("did", NATIVE)
def test_type_and_date_match_the_index(did: str) -> None:
    m, r = META[did], IDX[did]
    assert m.issue_date == dt.datetime.strptime(r["date"], "%d-%m-%Y").date(), did
    if did in TYPE_EXCEPTIONS:
        assert m.doc_type is DocType.NOTING  # the text says "Noting"; the index knows more
    else:
        assert m.doc_type.value == r["doc_type"], did


@pytest.mark.parametrize(
    "did", [d for d in NATIVE if not IDX[d]["raw_reference"].startswith("File No.")]
)
def test_own_canonical_id_matches(did: str) -> None:
    m = META[did]
    assert m.canonical_id is not None and IDX[did]["canonical_id"] in lookup_keys(m.canonical_id)
    assert m.department == IDX[did]["department"] and m.review_reasons == ()


@pytest.mark.parametrize("did", NATIVE)
def test_relations_match_ground_truth(did: str) -> None:
    expected = {
        (r["relation"], r["to_id"])
        for r in RELS
        if r["from_id"] == did and r["to_id"] and r["relation"] in EDGE_KINDS
    }
    got: set[tuple[str, str]] = set()
    for rel in META[did].relations:
        target = (
            next((BY_CID[k] for k in lookup_keys(rel.target) if k in BY_CID), None)
            if rel.resolved
            else None
        )
        got.add((rel.kind.value, target or rel.target))
    if did in FILE_CITATIONS:
        raw, doc = FILE_CITATIONS[did]
        assert (RelKind.CITES.value, raw) in got
        got = (got - {(RelKind.CITES.value, raw)}) | {(RelKind.CITES.value, doc)}
    extra = got - expected
    if did in EXTRA_OUTSIDE_CORPUS:
        assert extra == {
            (
                RelKind.CITES.value if did == "D27" else RelKind.REFERENCES.value,
                EXTRA_OUTSIDE_CORPUS[did],
            )
        }
        extra = set()
    assert expected - got == set(), did
    assert extra == set(), did


def test_explicit_supersession_is_marked_and_quoted() -> None:
    sup = [r for r in META["D14"].relations if r.kind is RelKind.SUPERSEDES]
    assert len(sup) == 1 and sup[0].explicit and "in supersession of" in sup[0].evidence
    assert sup[0].target == "AP-USD01-GOMS-14-2021"


def test_a_citation_never_swallows_the_next_reference() -> None:
    """'G.O.Ms.No.31 and Circular Memo No.X, Dt.14-08-2023' must not give the G.O. that date."""
    text = (
        "File No. USD01-12/1/2025-ESTT.I (Computer No. 1)\nNote # 1\n1. As per para 2(vii) of "
        "G.O.Ms.No.31 and Circular Memo No.GAD01-SERA0/3/2023, Dt.14-08-2023, clearance needed.\n"
        "A / Section Officer (Estt.I) / 01/06/2025 10:00 AM"
    )
    m = extract_metadata(text, DEPTS)
    targets = {r.target for r in m.relations}
    assert not any("GOMS-31-2023" in t for t in targets)
    assert any(t.startswith("AP-GAD01-CIRMEMO-GAD01SERA0-3-2023") for t in targets)


def test_unrecognised_text_goes_to_review() -> None:
    m = extract_metadata("Some unrelated letter text without any reference.", DEPTS)
    assert m.doc_type is DocType.UNKNOWN and m.canonical_id is None
    assert "document type not recognised" in m.review_reasons


# ---- extractor edge cases ------------------------------------------------------------------


def _docx(xml_body: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{xml_body}</w:body></w:document>",
        )
    return buf.getvalue()


def test_docx_line_breaks_and_tabs_are_kept() -> None:
    data = _docx(
        "<w:p><w:r><w:t>A. Name</w:t><w:br/><w:t>Section Officer</w:t><w:tab/>"
        "<w:t>01/06/2025 10:00 AM</w:t></w:r></w:p>"
    )
    text = extract_native(data, detect(data, "n.docx")).native_text
    assert text == "A. Name\nSection Officer\t01/06/2025 10:00 AM"


def test_xlsx_formula_without_cached_value_is_kept_not_invented() -> None:
    tables = _extract("D26").tables
    header, first = tables[0].rows[3], tables[0].rows[4]
    pct = header.index("% of cadre")
    assert first[pct].startswith("=")  # e.g. "=D5/C5": the formula, never a made-up number


def test_corrupt_docx_raises_extraction_error() -> None:
    bad = _docx("<w:p><w:r><w:t>unclosed")
    with pytest.raises(ExtractionError):
        extract_native(bad, detect(bad, "bad.docx"))


# ---- OCR layout: number and "Dated:" on separate lines (real Document AI output, 11 Nov 2026) ----


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("G.O.Ms.No.62\nDated: 14-06-2019", "AP-FIN01-GOMS-62-2019"),  # D01: number first
        ("Dated: 28-06-2019\nG.O.Ms.No.71", "AP-FIN01-GOMS-71-2019"),  # D02: date first
        ("G.O.Ms.No.19\n\nDated: 09-02-2018", "AP-FIN01-GOMS-19-2018"),  # blank line between
    ],
)
def test_split_header_lines_are_rejoined_for_the_own_reference(header: str, expected: str) -> None:
    head = "GOVERNMENT OF ANDHRA PRADESH\nFINANCE (HR.I-PLG. & POLICY) DEPARTMENT"
    text = f"{head}\n{header}\nORDER:\n1. x."
    meta = extract_metadata(text, DEPTS)
    assert meta.canonical_id == expected


def test_circular_memo_with_date_above_the_number() -> None:
    text = (
        "GOVERNMENT OF ANDHRA PRADESH\nURBAN SERVICES (WORKS) DEPARTMENT\nDated: 11-07-2023\n"
        "Circular Memo No.USD01-WRKS0/9/2023\nSub: Works - Reg.\n1. x."
    )
    assert (
        extract_metadata(text, DEPTS).canonical_id == "AP-USD01-CIRMEMO-USD01WRKS0-9-2023-D20230711"
    )


def test_a_date_far_from_the_number_is_not_joined() -> None:
    text = (
        "GOVERNMENT OF ANDHRA PRADESH\nFINANCE (HR.I) DEPARTMENT\nG.O.Ms.No.62\n"
        "Read the following:\n1. something\nDated: 14-06-2019\nORDER:\n1. x."
    )
    assert extract_metadata(text, DEPTS).canonical_id is None  # never guessed (CLAUDE.md §5.6)
