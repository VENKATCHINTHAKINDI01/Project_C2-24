"""The system under test, built the way production builds it: every corpus file goes through the
ingestion job (`app.ingestion.pipeline.ingest`) — detect, extract, gate, metadata, canonical ID,
index, graph, temporal facts, reconciliation. Nothing is read from the ground truth except where
stated below. EVALUATION ONLY (CLAUDE.md §9.2).

Stand-in, clearly labelled: scanned pages need Document AI (GCP, not available). The gate holds
them for review, as it should. To evaluate the rest of the stack on the whole corpus, a held scan
is then re-submitted as its hand transcription (`ground_truth/text/Dxx.txt`) — standing in for
"Document AI read it and a reviewer confirmed the text". This is the ONE place ground truth feeds
the stack; the report lists which documents it affected.

Alternative, real OCR (`ocr_version`): held scans are read from the recorded Document AI responses
(`data/synthetic/mock_v1/ocr/documentai/<version>/`, no GCP calls) and confirmed by a SIMULATED
reviewer through the production path (`confirm_extraction`), with no corrections. A scan whose
OCR text still fails a pipeline check (e.g. an unreadable reference) stays held, as it would in
the app. No ground truth feeds the stack in this mode.

Access profiles come from the synthetic sandbox users (`tests/unit/mock_access.py`, the same
fixture the unit tests use). The independent oracle for leakage is `access_matrix.csv`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from app.auth.models import DocumentAccessTags
from app.config import REPO_ROOT, load_hierarchy
from app.identifiers.resolver import DepartmentTable, load_departments
from app.ingestion.detect import detect_file
from app.ingestion.extract import extract_native
from app.ingestion.ocr import OcrEngine, RecordedOcr, load_recorded, version_dir
from app.ingestion.pipeline import (
    IngestionStores,
    IngestResult,
    IngestStatus,
    SourceDocument,
    confirm_extraction,
    ingest,
)
from app.retrieval.ladder import InMemoryKeywordIndex, LadderConfig
from app.retrieval.scoped import IndexedDocument
from tests.unit.mock_access import CORPUS, rows

ONTOLOGY = REPO_ROOT / "data" / "ontology"
T0 = dt.datetime(2026, 10, 2, 9, tzinfo=dt.UTC)


@dataclass
class Stack:
    stores: IngestionStores
    departments: DepartmentTable
    l2: InMemoryKeywordIndex
    cfg: LadderConfig
    cid_of: dict[str, str]  # corpus doc id (D01…) → canonical ID assigned at ingestion
    doc_of: dict[str, str]  # canonical ID → corpus doc id
    text_of: dict[str, str]  # canonical ID → text the index holds
    held: dict[str, str] = field(default_factory=dict)  # doc id → why the file itself was held
    transcribed: tuple[str, ...] = ()  # doc ids indexed from the hand transcription
    not_indexed: tuple[str, ...] = ()  # doc ids missing even after the stand-in
    arrived: dict[str, IngestResult] = field(default_factory=dict)  # replay arrivals
    transcribe: bool = True
    ocr_version: str | None = None  # real recorded Document AI OCR instead of transcriptions
    ocr_confirmed: tuple[str, ...] = ()  # doc ids indexed from OCR after simulated review

    def tags(self, cid: str) -> DocumentAccessTags | None:
        node = self.stores.graph.node(cid)
        return node.tags if node else None

    def documents(self) -> list[IndexedDocument]:
        return list(self.stores.index._docs)  # noqa: SLF001 — reference store, read-only here


def _source(row: dict[str, str], uri: str, filename: str) -> SourceDocument:
    ref = row["raw_reference"]
    return SourceDocument(
        source_uri=uri,
        filename=filename,
        tags=DocumentAccessTags(
            doc_id=row["id"],
            department=row["department"],
            section=row["section"],
            classification=row["classification"],
            file_no=ref.removeprefix("File No.") if ref.startswith("File No.") else None,
        ),
        received_at=T0,
    )


def build_stack(
    cfg: LadderConfig,
    corpus: Path = CORPUS,
    holdback: frozenset[str] = frozenset(),
    open_files: frozenset[str] = frozenset(),
    arrivals: tuple[str, ...] = (),
    transcribe: bool = True,
    ocr_version: str | None = None,
) -> Stack:
    """Replays (e.g. TP04): `holdback` doc ids are left out; `arrivals` are then ingested last,
    in order, and their results kept in `Stack.arrived`. `open_files` feeds reconciliation."""
    stores = IngestionStores()
    depts = load_departments(ONTOLOGY / "departments.yaml")
    hier = load_hierarchy(ONTOLOGY / "hierarchy.yaml")
    cid_of: dict[str, str] = {}
    text_of: dict[str, str] = {}
    held: dict[str, str] = {}
    transcribed: list[str] = []
    missing: list[str] = []
    arrived: dict[str, IngestResult] = {}
    last: list[IngestResult] = []
    ocr_confirmed: list[str] = []
    engine: OcrEngine | None = None
    if ocr_version:
        cache = corpus / "ocr" / "documentai"
        engine = RecordedOcr(load_recorded(version_dir(cache, ocr_version)), ocr_version)

    def run(src: SourceDocument, data: bytes) -> str | None:
        res = ingest(
            src,
            data,
            stores=stores,
            departments=depts,
            hierarchy=hier,
            confidence_threshold=None,
            open_files=open_files,
            ocr=engine,
        )
        if (
            engine is not None
            and res.status is IngestStatus.HELD
            and res.version in stores.ocr_drafts
        ):
            res = confirm_extraction(  # SIMULATED reviewer: confirms the OCR draft as read
                src,
                data,
                reviewer="EVAL-REVIEWER (simulated)",
                reason="evaluation: OCR draft accepted without correction",
                at=T0,
                stores=stores,
                departments=depts,
                hierarchy=hier,
                confidence_threshold=None,
                open_files=open_files,
            )
            if res.status is IngestStatus.INDEXED:
                ocr_confirmed.append(src.tags.doc_id)
        last[:] = [res]
        if res.status is IngestStatus.INDEXED and res.canonical_id:
            return res.canonical_id
        if res.status is IngestStatus.HELD:
            held[src.tags.doc_id] = "; ".join(i.kind.value for i in res.review_items) or "held"
        return None

    index_rows = {r["id"]: r for r in rows("documents_index.csv")}
    order = [d for d in index_rows if d not in holdback] + [d for d in arrivals if d in holdback]
    for did in order:
        row = index_rows[did]
        path = corpus / row["file"]
        data = path.read_bytes()
        cid = run(_source(row, f"mock://{row['file']}", path.name), data)
        if cid:
            text_of[cid] = (
                stores.text_of.get(last[0].version)
                or extract_native(data, detect_file(path)).native_text
            )
        elif not transcribe or engine is not None:  # no stand-in: the scan stays in review
            missing.append(did)
            continue
        else:  # stand-in for Document AI + reviewer-confirmed text (see module docstring)
            text = (corpus / "ground_truth" / "text" / f"{did}.txt").read_text("utf-8")
            cid = run(
                _source(row, f"mock://{row['file']}#confirmed-text", f"{did}.txt"),
                text.encode("utf-8"),
            )
            if cid:
                transcribed.append(did)
                text_of[cid] = text
            else:
                missing.append(did)
                continue
        cid_of[did] = cid
        if did in arrivals and last:
            arrived[did] = last[0]

    docs = list(stores.index._docs)  # noqa: SLF001
    l2 = InMemoryKeywordIndex((d, text_of.get(d.canonical_id, "")) for d in docs)
    return Stack(
        stores=stores,
        departments=depts,
        l2=l2,
        cfg=cfg,
        cid_of=cid_of,
        doc_of={v: k for k, v in cid_of.items()},
        text_of=text_of,
        held=held,
        transcribed=tuple(transcribed),
        not_indexed=tuple(missing),
        arrived=arrived,
        transcribe=transcribe,
        ocr_version=ocr_version,
        ocr_confirmed=tuple(ocr_confirmed),
    )
