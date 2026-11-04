"""Regression tests for the gaps the 4 Nov 2026 evaluation baseline found on the pipeline stack
(PROGRESS ledger "Evaluation harness + first baseline"; ADR-0007, ADR-0011; plan §3.2, §4.3,
§6.4)."""

from __future__ import annotations

import datetime as dt

from app.auth.models import DocumentAccessTags
from app.hitl.queue import ReviewKind
from app.identifiers.resolver import reference_candidates, resolve_reference
from app.ingestion.detect import detect_file
from app.ingestion.extract import extract_native
from app.ingestion.metadata import DocType, extract_metadata
from app.ingestion.pipeline import IngestionStores, IngestStatus
from app.retrieval.references import LookupStatus, lookup_reference
from app.retrieval.scoped import IndexedDocument, InMemoryScopedIndex
from tests.unit.mock_access import CLASSES, CORPUS, POLICY, new_store
from tests.unit.test_ingestion_pipeline import DEPTS, IDX, _ingest, _src

TEXT = CORPUS / "ground_truth" / "text"


def _text(did: str) -> str:
    return (TEXT / f"{did}.txt").read_text("utf-8")


def _doc(cid: str, section: str = "WORKS", cls: str = "UNCLASSIFIED") -> IndexedDocument:
    tags = DocumentAccessTags(doc_id=cid, department="USD01", section=section, classification=cls)
    return IndexedDocument(
        canonical_id=cid, tags=tags, doc_type="Circular", issue_date=None, subject="x"
    )


def _lookup(index: InMemoryScopedIndex, text: str, user: str = "U03"):  # type: ignore[no-untyped-def]
    return lookup_reference(
        user,
        text,
        departments=DEPTS,
        retriever=index,
        store=new_store(),
        policy=POLICY,
        classification=CLASSES,
    )


# ---- 1 · a reference printed without its date finds the dated record (ADR-0007) --------------

MEMO = "Circular Memo No.USD01-WRKS0/9/2023"
BASE = "AP-USD01-CIRMEMO-USD01WRKS0-9-2023"


def test_base_reference_finds_the_one_dated_record() -> None:
    idx = InMemoryScopedIndex([_doc(f"{BASE}-D20230711")])
    look = _lookup(idx, f"Is {MEMO} still valid?")
    assert look.status is LookupStatus.FOUND and look.canonical_id == f"{BASE}-D20230711"


def test_two_dated_records_with_one_base_are_ambiguous_not_guessed() -> None:
    idx = InMemoryScopedIndex([_doc(f"{BASE}-D20230711"), _doc(f"{BASE}-D20230901")])
    look = _lookup(idx, MEMO)
    assert look.status is LookupStatus.AMBIGUOUS and len(look.choices) == 2


def test_base_match_never_reaches_outside_scope() -> None:
    """The second dated record is SECRET in Vigilance: the Works SO sees one match, nothing else."""
    idx = InMemoryScopedIndex(
        [_doc(f"{BASE}-D20230711"), _doc(f"{BASE}-D20230901", section="VIG", cls="SECRET")]
    )
    look = _lookup(idx, MEMO)
    assert look.status is LookupStatus.FOUND and look.canonical_id == f"{BASE}-D20230711"


def test_a_dated_reference_still_needs_its_own_date() -> None:
    idx = InMemoryScopedIndex([_doc(f"{BASE}-D20230711")])
    assert _lookup(idx, f"{MEMO}, Dt.01-09-2023").status is LookupStatus.NOT_FOUND


# ---- 2 · "G.O.Ms.No.31 of 2025" -------------------------------------------------------------


def test_go_number_of_year_is_a_reference() -> None:
    r = resolve_reference("What does G.O.Ms.No.31 of 2025 say?", DEPTS, "FIN01")
    assert r.canonical_id == "AP-FIN01-GOMS-31-2025"
    cands = reference_candidates("G.O.Ms.No.31 of 2025", DEPTS)
    assert "AP-FIN01-GOMS-31-2025" in cands and len(cands) > 1  # no department named → ask
    assert resolve_reference("G.O.Ms.No.31 of the Department", DEPTS, "FIN01").canonical_id is None


# ---- 3 · an order's own end date ------------------------------------------------------------


def test_validity_end_read_from_the_subject_only() -> None:
    d08 = extract_metadata(_text("D08"), DEPTS)
    assert d08.valid_until == dt.date(2026, 3, 31)  # "for the period from 01-04-2025 to 31-03-2026"
    d07 = extract_metadata(_text("D07"), DEPTS)
    assert d07.valid_until == dt.date(2025, 3, 31)  # "up to 31-03-2025"
    assert extract_metadata(_text("D04"), DEPTS).valid_until is None  # no period in its subject
    d29 = extract_metadata(_text("D29"), DEPTS)  # a note, not an order: never an end date
    assert d29.doc_type in (DocType.NOTING, DocType.NOTING_DRAFT) and d29.valid_until is None


def test_pipeline_records_the_end_date_so_type_f_can_fire() -> None:
    stores = IngestionStores()
    res = _ingest(stores, "D08")
    assert res.status is IngestStatus.INDEXED
    assert stores.instruments[res.canonical_id].valid_until == dt.date(2026, 3, 31)


# ---- 4 · subjects for abstracts without a rule line, reports and statements -----------------


def test_subjects_are_read() -> None:
    assert extract_metadata(_text("D01"), DEPTS).subject == (
        "Public Services – Human Resources – General Transfers of Employees for the year 2019 – "
        "Guidelines – Orders – Issued."
    )
    assert (extract_metadata(_text("D09"), DEPTS).subject or "").startswith("Secretariat Service")
    for did, start in (("D23", "Report of the Vigilance"), ("D26", "Statement of cadre")):
        path = CORPUS / IDX[did]["file"]
        meta = extract_metadata(
            extract_native(path.read_bytes(), detect_file(path)).native_text, DEPTS
        )
        assert (meta.subject or "").startswith(start), did


# ---- 5 · department from the source system (ADR-0011) --------------------------------------


def test_department_from_source_only_when_the_text_names_none() -> None:
    d11 = _text("D11")  # Standing Order: no department anywhere in the text
    assert extract_metadata(d11, DEPTS).canonical_id is None
    m = extract_metadata(d11, DEPTS, source_department="USD01")
    assert m.canonical_id == "AP-USD01-SO-2-2020" and m.department_source == "source_system"
    d04 = extract_metadata(_text("D04"), DEPTS, source_department="USD01")
    assert d04.department == "FIN01" and d04.department_source == "text"  # text wins


def test_text_and_source_disagree_goes_to_review() -> None:
    stores = IngestionStores()
    res = _ingest(stores, "D04", src=_src("D04", department="USD01"))
    assert res.status is IngestStatus.HELD
    assert ReviewKind.DEPARTMENT_MISMATCH in {i.kind for i in res.review_items}
    assert len(stores.index) == 0


def test_read_list_date_broken_after_its_hyphen() -> None:
    """G.O.Rt.1184/2025's PDF wraps "Dt.27-" / "03-2024": the cited circular keeps its date tag."""
    path = CORPUS / IDX["D08"]["file"]
    meta = extract_metadata(extract_native(path.read_bytes(), detect_file(path)).native_text, DEPTS)
    ids = [r.canonical_id for r in meta.references]
    assert "AP-FIN01-CIRMEMO-FIN01HROPDPPOUTS-7-2024-D20240327" in ids
