"""Ingestion job end to end on the whole mock corpus (plan §4, §7.2, §7.4; CLAUDE.md §5.8-§5.10)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.auth.models import DocumentAccessTags
from app.auth.policy import scope_for
from app.config import REPO_ROOT, load_hierarchy
from app.hitl.queue import ReviewKind
from app.identifiers.canonical import lookup_keys
from app.identifiers.resolver import load_departments
from app.ingestion.pipeline import IngestionStores, IngestStatus, SourceDocument, ingest
from app.retrieval.scoped import L1Criteria, Rung, retrieve
from app.temporal.engine import Status, status_as_of
from tests.unit.mock_access import CLASSES, CORPUS, MATRIX, POLICY, new_store, rows

DEPTS = load_departments(REPO_ROOT / "data" / "ontology" / "departments.yaml")
HIER = load_hierarchy(REPO_ROOT / "data" / "ontology" / "hierarchy.yaml")
IDX = {r["id"]: r for r in rows("documents_index.csv")}
T0 = dt.datetime(2026, 10, 2, 9, tzinfo=dt.UTC)
OCR_DOCS = {"D01", "D02", "D09", "D11", "D13", "D16", "D22"}
HELD = OCR_DOCS | {
    "D15"
}  # D15: page 1 native, page 2 scanned → held until the whole document is read
FILE_CITATIONS: set[tuple[str, str]] = set()  # D20 → D21 (cited by file number) now resolved


def _src(did: str, uri: str | None = None, **tag_changes: str) -> SourceDocument:
    r = IDX[did]
    ref = r["raw_reference"]
    tags = DocumentAccessTags(
        doc_id=did,
        department=r["department"],
        section=r["section"],
        classification=r["classification"],
        file_no=ref.removeprefix("File No.") if ref.startswith("File No.") else None,
    )
    return SourceDocument(
        source_uri=uri or f"mock://{r['file']}",
        filename=r["file"].split("/")[-1],
        tags=tags.model_copy(update=tag_changes),
        received_at=T0,
    )


def _ingest(stores: IngestionStores, did: str, **kw):  # type: ignore[no-untyped-def]
    data = kw.pop("data", None) or (CORPUS / IDX[did]["file"]).read_bytes()
    src = kw.pop("src", None) or _src(did)
    return ingest(
        src, data, stores=stores, departments=DEPTS, hierarchy=HIER, confidence_threshold=None, **kw
    )


@pytest.fixture(scope="module")
def corpus() -> tuple[IngestionStores, dict[str, object]]:
    stores = IngestionStores()
    results = {did: _ingest(stores, did) for did in IDX}
    return stores, results


def test_whole_corpus_native_indexed_scans_held(corpus) -> None:  # type: ignore[no-untyped-def]
    stores, res = corpus
    held = {d for d, r in res.items() if r.status is IngestStatus.HELD}
    assert held == HELD
    assert len(stores.index) == 21
    assert {i.kind for i in stores.queue.pending()} == {ReviewKind.LOW_CONFIDENCE_EXTRACTION}


def test_ingested_ids_match_the_corpus(corpus) -> None:  # type: ignore[no-untyped-def]
    _, res = corpus
    for did, r in res.items():
        if did in HELD:
            continue
        assert r.canonical_id is not None and IDX[did]["canonical_id"] in lookup_keys(
            r.canonical_id
        ), did


def test_graph_holds_every_explicit_edge_between_ingested_documents(corpus) -> None:  # type: ignore[no-untyped-def]
    stores, res = corpus
    cid = {d: r.canonical_id for d, r in res.items() if r.canonical_id}
    expected = {
        (cid[r["from_id"]], r["relation"], cid[r["to_id"]])
        for r in rows("ground_truth/relations.csv")
        if r["to_id"] in cid
        and r["from_id"] in cid
        and r["explicit_in_text"] == "True"
        and (r["from_id"], r["to_id"]) not in FILE_CITATIONS
        and r["relation"] in {"SUPERSEDES", "AMENDS", "CLARIFIES", "REFERENCES", "CITES"}
    }
    got = {
        (e.source, e.kind.value, e.target) for n in cid.values() for e in stores.graph.edges_from(n)
    }
    assert expected <= got
    assert got - expected == set()


def test_edges_to_held_scans_wait_as_pending(corpus) -> None:  # type: ignore[no-untyped-def]
    _, res = corpus
    assert (
        "SUPERSEDES→AP-FIN01-GOMS-62-2019" in res["D03"].pending_edges
    )  # D01 is a scan, still held


def test_temporal_facts_come_from_ingestion(corpus) -> None:  # type: ignore[no-untyped-def]
    stores, res = corpus
    d03, d04 = res["D03"].canonical_id, res["D04"].canonical_id
    st = status_as_of(d03, dt.date(2026, 10, 2), stores.instruments, stores.relations)
    assert st.status is Status.SUPERSEDED and st.by == d04


def test_ingested_index_is_permission_enforced(corpus) -> None:  # type: ignore[no-untyped-def]
    stores, _ = corpus
    store = new_store()
    for uid in ("U01", "U02", "U06"):
        got = retrieve(
            uid,
            Rung.L1,
            L1Criteria(),
            retriever=stores.index,
            store=store,
            policy=POLICY,
            classification=CLASSES,
        ).documents
        did_of = {r.canonical_id: d for d, r in corpus[1].items() if r.canonical_id}
        assert all(MATRIX[(did_of[d.canonical_id], uid)] for d in got), uid
    assert scope_for("U01", store, POLICY, CLASSES)


# ---- idempotency, versions, reconciliation ---------------------------------------------------


def test_rerun_is_idempotent() -> None:
    stores = IngestionStores()
    first = _ingest(stores, "D04")
    nodes, items = len(stores.index), len(stores.queue.history())
    again = _ingest(stores, "D04")
    assert again.status is IngestStatus.DUPLICATE and again.canonical_id == first.canonical_id
    assert len(stores.index) == nodes and len(stores.queue.history()) == items


def test_same_bytes_from_another_source_is_the_same_document() -> None:
    stores = IngestionStores()
    a = _ingest(stores, "D04")
    b = _ingest(stores, "D04", src=_src("D04", uri="mock://receipts/9100009.pdf"))
    assert b.status is IngestStatus.DUPLICATE and b.canonical_id == a.canonical_id
    assert stores.collisions.lookup(a.canonical_id or "").status.value == "found"  # no -C01 created


def test_new_bytes_for_a_known_source_are_a_new_version_and_old_is_kept() -> None:
    stores = IngestionStores()
    v1 = _ingest(stores, "D04")
    data = (CORPUS / IDX["D04"]["file"]).read_bytes() + b"\n% re-scan\n"
    v2 = _ingest(stores, "D04", data=data)
    assert v2.status is IngestStatus.INDEXED and v2.version != v1.version
    assert stores.versions[_src("D04").source_uri] == [v1.version, v2.version]
    assert v2.canonical_id == v1.canonical_id  # same source keeps its ID (never reassigned)


def test_out_of_order_arrival_attaches_pending_supersession() -> None:
    stores = IngestionStores()
    new = _ingest(stores, "D04")  # supersedes D03, which is not ingested yet
    assert any(p.startswith("SUPERSEDES→AP-FIN01-GOMS-88-2022") for p in new.pending_edges)
    old = _ingest(stores, "D03")
    assert any(
        "SUPERSEDES" in a for a in old.edges_added if a.startswith(new.canonical_id or "")
    ), old.edges_added
    st = status_as_of(
        old.canonical_id or "", dt.date(2026, 1, 1), stores.instruments, stores.relations
    )
    assert st.status is Status.SUPERSEDED


def test_new_order_invalidates_cached_answers_about_the_old_one() -> None:
    stores = IngestionStores()
    old = _ingest(stores, "D03")
    scope = scope_for("U01", new_store(), POLICY, CLASSES)
    stores.cache.put(
        "current transfer guidelines", scope, "per 88/2022 …", frozenset({old.canonical_id or ""})
    )
    new = _ingest(stores, "D04")
    assert (
        new.invalidated_answers == 1
        and stores.cache.get("current transfer guidelines", scope) is None
    )


# ---- review paths ----------------------------------------------------------------------------


def test_classification_marking_that_disagrees_with_the_source_is_held() -> None:
    stores = IngestionStores()
    res = _ingest(
        stores, "D27", src=_src("D27", classification="UNCLASSIFIED")
    )  # text says RESTRICTED
    assert res.status is IngestStatus.HELD
    assert res.review_items[0].kind is ReviewKind.CLASSIFICATION_MISMATCH
    assert len(stores.index) == 0


def test_confirming_a_scan_does_not_index_empty_text() -> None:
    stores = IngestionStores()
    held = _ingest(stores, "D02")
    item = held.review_items[0]
    stores.queue.decide(item.item_id, reviewer="U07", confirm=True, reason="looks fine", at=T0)
    again = ingest(
        _src("D02"),
        (CORPUS / IDX["D02"]["file"]).read_bytes() + b" ",
        stores=stores,
        departments=DEPTS,
        hierarchy=HIER,
        confidence_threshold=None,
    )
    assert again.status is IngestStatus.HELD and len(stores.index) == 0  # still needs OCR text


GO_TEXT = """GOVERNMENT OF ANDHRA PRADESH
ABSTRACT
Public Services – {subject} – Orders – Issued.
------------------------------------------------------------------------
FINANCE (HR.III) DEPARTMENT
G.O.Ms.No.126 Dated: 15-03-2023
ORDER:
1. Synthetic test order.
"""


def _go(subject: str) -> bytes:
    return GO_TEXT.format(subject=subject).encode()


def test_two_different_orders_with_one_number_get_distinct_ids() -> None:
    """Real-world case: two Finance G.O.Ms.126 of 2023 (ADR-0007). First keeps the bare ID."""
    stores = IngestionStores()
    src = _src("D04", uri="mock://go/126-a.txt").model_copy(update={"filename": "a.txt"})
    a = ingest(
        src,
        _go("Pensions"),
        stores=stores,
        departments=DEPTS,
        hierarchy=HIER,
        confidence_threshold=None,
    )
    src_b = _src("D04", uri="mock://go/126-b.txt", section="HR.III").model_copy(
        update={"filename": "b.txt"}
    )
    b = ingest(
        src_b,
        _go("Leave rules"),
        stores=stores,
        departments=DEPTS,
        hierarchy=HIER,
        confidence_threshold=None,
    )
    assert a.canonical_id == "AP-FIN01-GOMS-126-2023"
    assert b.status is IngestStatus.INDEXED and b.canonical_id == "AP-FIN01-GOMS-126-2023-HRIII"
    assert stores.collisions.lookup("AP-FIN01-GOMS-126-2023").status.value == "ambiguous"


def test_unsupported_file_is_held() -> None:
    stores = IngestionStores()
    res = ingest(
        _src("D04"),
        b"\x00\x01 not a document",
        stores=stores,
        departments=DEPTS,
        hierarchy=HIER,
        confidence_threshold=None,
    )
    assert (
        res.status is IngestStatus.HELD and res.review_items[0].kind is ReviewKind.UNSUPPORTED_FILE
    )
