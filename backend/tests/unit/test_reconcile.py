"""Relationship reconciliation: e-File citations, inferred supersession, open-file notices
(plan §7.2, §7.3, §11.5 touchpoint 4, §5.4)."""

from __future__ import annotations

import datetime as dt
import json

from app.graph.repository import EdgeKind
from app.hitl.queue import ReviewKind
from app.ingestion.pipeline import IngestionStores, IngestResult, IngestStatus, ingest
from app.temporal.engine import Status, status_as_of
from app.updates.reconcile import notices_for
from tests.unit.mock_access import CLASSES, CORPUS, POLICY, new_store
from tests.unit.test_ingestion_pipeline import DEPTS, HIER, IDX, _go, _ingest, _src

SEED = json.loads((CORPUS / "eoffice" / "seed.json").read_text(encoding="utf-8"))
OPEN = frozenset(f["file_no"] for f in SEED["files"] if f["state"] == "open")
TP = {
    s["id"]: s
    for s in json.loads((CORPUS / "ground_truth" / "touchpoint_scenarios.json").read_text("utf-8"))[
        "scenarios"
    ]
}
FILE_NO = {f["computer_no"]: f["file_no"] for f in SEED["files"]}


def test_note_citing_a_file_links_to_earlier_documents_only() -> None:
    """D20 (30-05-2025) cites file USD01-31/4/2025-VIG: D21 (18-04-2025) yes, D22 (25-07) no."""
    stores = IngestionStores()
    d21 = _ingest(stores, "D21")
    d20 = _ingest(stores, "D20")
    assert f"{d20.canonical_id}:CITES→{d21.canonical_id}" in d20.edges_added
    assert not any(p.startswith("CITES→file:") for p in d20.pending_edges)


def test_file_citation_attaches_when_the_earlier_document_arrives_later() -> None:
    stores = IngestionStores()
    d20 = _ingest(stores, "D20")
    d21 = _ingest(stores, "D21")
    assert f"{d20.canonical_id}:CITES→{d21.canonical_id}" in d21.edges_added


def test_no_inferred_supersession_on_the_mock_corpus() -> None:
    """Every real supersession in the corpus is explicit: no false 'inferred' review items."""
    stores = IngestionStores()
    for did in IDX:
        _ingest(stores, did)
    assert not stores.queue.pending(ReviewKind.INFERRED_SUPERSESSION)


def _ingest_go(stores: IngestionStores, uri: str, number: int, date: str, subject: str):  # type: ignore[no-untyped-def]
    text = _go(subject).replace(
        b"G.O.Ms.No.126 Dated: 15-03-2023", f"G.O.Ms.No.{number} Dated: {date}".encode()
    )
    src = _src("D04", uri=uri).model_copy(update={"filename": uri.rsplit("/", 1)[-1]})
    return ingest(
        src, text, stores=stores, departments=DEPTS, hierarchy=HIER, confidence_threshold=None
    )


def test_same_subject_newer_order_is_queued_not_applied() -> None:
    stores = IngestionStores()
    old = _ingest_go(
        stores, "mock://go/10.txt", 10, "01-04-2024", "Leave Travel Concession for the year 2024"
    )
    new = _ingest_go(
        stores, "mock://go/20.txt", 20, "01-04-2025", "Leave Travel Concession for the year 2025"
    )
    assert [i.kind for i in new.review_items] == [ReviewKind.INFERRED_SUPERSESSION]
    edge = next(
        e for e in stores.graph.edges_from(new.canonical_id or "") if e.kind is EdgeKind.SUPERSEDES
    )
    assert edge.target == old.canonical_id and not edge.confirmed
    st = status_as_of(
        old.canonical_id or "", dt.date(2025, 6, 1), stores.instruments, stores.relations
    )
    assert st.status is Status.IN_FORCE and st.pending_review == (new.canonical_id,)  # not flipped


def test_different_subject_or_explicit_link_is_not_inferred() -> None:
    stores = IngestionStores()
    _ingest_go(
        stores, "mock://go/10.txt", 10, "01-04-2024", "Leave Travel Concession for the year 2024"
    )
    other = _ingest_go(stores, "mock://go/30.txt", 30, "01-05-2025", "Medical reimbursement rules")
    assert other.review_items == ()
    s2 = IngestionStores()
    _ingest(s2, "D03")
    d04 = _ingest(s2, "D04")  # same subject shape as D03, but the text states the supersession
    assert not any(i.kind is ReviewKind.INFERRED_SUPERSESSION for i in d04.review_items)


# ---- touchpoint 4 replay ---------------------------------------------------------------------


def _replay() -> tuple[IngestionStores, IngestResult]:
    held = set(TP["TP04"]["setup"]["holdback"])
    stores = IngestionStores()
    for did in IDX:
        if did not in held:
            _ingest(stores, did, open_files=OPEN)
    arrival = _ingest(stores, "D04", open_files=OPEN)
    return stores, arrival


def test_tp04_new_order_lists_the_open_file_citing_the_old_one() -> None:
    stores, arrival = _replay()
    assert arrival.status is IngestStatus.INDEXED
    expected_files = {FILE_NO[c] for c in TP["TP04"]["expected"]["files"]}
    (notice,) = arrival.notices
    assert notice.change is EdgeKind.SUPERSEDES and notice.changed_doc == "AP-FIN01-GOMS-88-2022"
    assert {
        a.file_no for a in notice.affected
    } == expected_files  # decided 2022/2023 files are closed
    # explicit supersession is set directly (plan §7.3): status flips without a review item
    st = status_as_of(
        "AP-FIN01-GOMS-88-2022", dt.date(2026, 10, 2), stores.instruments, stores.relations
    )
    assert st.status is Status.SUPERSEDED


def test_tp04_notice_is_filtered_per_officer() -> None:
    stores, _ = _replay()
    store = new_store()
    view = {
        uid: notices_for(uid, stores.notices, store=store, policy=POLICY, classification=CLASSES)
        for uid in ("U01", "U02", "U03", "U07")
    }
    assert [a.file_no for n in view["U01"] for a in n.affected] == ["USD01-12/19/2026-ESTT.I"]
    assert (
        view["U02"] and view["U03"] == [] and view["U07"] == []
    )  # Works / Finance officers see nothing
