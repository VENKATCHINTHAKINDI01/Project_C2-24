"""Ingestion job: detect → extract → gate → metadata → canonical ID → review queue or index + graph
(plan §4, §7.4; CLAUDE.md §5.1-§5.10).

- Idempotent: the same bytes from the same source are processed once; a re-run returns the earlier
  result and adds no duplicate nodes, edges or review items.
- Versioned: new bytes for a known source become a new version; earlier versions are kept, never
  deleted (CLAUDE.md §5.8).
- Permission tags come from the SOURCE (e-Office / connector metadata), never from document text.
  A classification marking printed in the text that differs from the tag holds the document for
  review — it is never silently upgraded or downgraded.
- Only confirmed, gated text reaches the index; OCR'd pages wait for Document AI + human review.
- Explicit relations become confirmed graph edges; edges to documents not yet ingested wait as
  pending and attach when the target arrives (relationship reconciliation, plan §7.2).
- Indexing a document invalidates cached answers that cite it or the documents it changes.

Reference stores are in memory; BigQuery / Vertex AI Search / Spanner implementations follow the
same calls on GCP.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.auth.models import DocumentAccessTags
from app.cache.answers import InMemoryAnswerCache
from app.config import Hierarchy
from app.graph.repository import EdgeKind, GraphEdge, GraphNode, InMemoryGraphRepository
from app.hitl.queue import ReviewItem, ReviewKind, ReviewQueue
from app.identifiers.canonical import (
    InvalidCanonicalIdError,
    efile_document_id,
    lookup_keys,
    parse_canonical_id,
)
from app.identifiers.collisions import CollisionError, CollisionRegistry
from app.identifiers.resolver import DepartmentTable
from app.ingestion.detect import detect
from app.ingestion.extract import ExtractionError, extract_native
from app.ingestion.gate import Extraction, gate, indexable
from app.ingestion.metadata import DocType, DocumentMetadata, RelKind, extract_metadata
from app.retrieval.scoped import IndexedDocument, InMemoryScopedIndex
from app.temporal.engine import Instrument, RelationKind, TemporalRelation
from app.temporal.windows import ActionWindow, windows_from_text
from app.updates.reconcile import OpenFileNotice, reconcile

PIPELINE_VERSION = "ingest-2026-11-03"
_EFILE_TYPE = {
    DocType.NOTING: "NOTE",
    DocType.NOTING_DRAFT: "NOTE",
    DocType.REPORT: "RPT",
    DocType.ANNEXURE: "ANX",
}
_TEMPORAL = {
    RelKind.SUPERSEDES: RelationKind.SUPERSEDES,
    RelKind.AMENDS: RelationKind.AMENDS,
    RelKind.CLARIFIES: RelationKind.CLARIFIES,
}
_ORDER_DOC_TYPES = frozenset(  # instruments that can open a window for an action
    {
        DocType.GOVERNMENT_ORDER,
        DocType.AMENDMENT,
        DocType.CIRCULAR,
        DocType.MEMO,
        DocType.CLARIFICATION,
        DocType.STANDING_ORDER,
    }
)
_CLASS_MARK = re.compile(r"^\s*\[?\s*(UNCLASSIFIED|RESTRICTED|CONFIDENTIAL|SECRET)\s*\]?\s*$", re.M)


class IngestStatus(StrEnum):
    INDEXED = "indexed"
    HELD = "held"  # waiting in the review queue
    DUPLICATE = "duplicate"  # same source + same bytes: earlier result returned


class SourceDocument(BaseModel):
    """What the connector hands over (plan §11.3 'events in'). Tags come from the source system."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_uri: str
    filename: str
    tags: DocumentAccessTags
    received_at: dt.datetime


class IngestResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_uri: str
    version: str
    status: IngestStatus
    canonical_id: str | None = None
    doc_type: str | None = None
    review_items: tuple[ReviewItem, ...] = ()
    edges_added: tuple[str, ...] = ()
    pending_edges: tuple[str, ...] = ()
    invalidated_answers: int = 0
    notices: tuple[OpenFileNotice, ...] = ()


@dataclass
class IngestionStores:
    """The reference stores one ingestion run writes to."""

    index: InMemoryScopedIndex = field(default_factory=InMemoryScopedIndex)
    graph: InMemoryGraphRepository = field(default_factory=InMemoryGraphRepository)
    instruments: dict[str, Instrument] = field(default_factory=dict)
    relations: list[TemporalRelation] = field(default_factory=list)
    queue: ReviewQueue = field(default_factory=ReviewQueue)
    collisions: CollisionRegistry = field(default_factory=CollisionRegistry)
    cache: InMemoryAnswerCache = field(default_factory=InMemoryAnswerCache)
    results: dict[tuple[str, str], IngestResult] = field(default_factory=dict)  # (uri, version)
    by_content: dict[str, IngestResult] = field(
        default_factory=dict
    )  # version → first INDEXED result
    versions: dict[str, list[str]] = field(default_factory=dict)  # uri → versions, oldest first
    pending: list[GraphEdge] = field(default_factory=list)  # edges waiting for their target
    files: dict[str, list[tuple[str, dt.date | None]]] = field(default_factory=dict)  # file → docs
    pending_files: list[tuple[str, str, dt.date | None]] = field(default_factory=list)
    notices: list[OpenFileNotice] = field(default_factory=list)  # touchpoint 4
    windows: dict[str, tuple[ActionWindow, ...]] = field(default_factory=dict)  # cid → windows


def _version(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()[:16]}:{PIPELINE_VERSION}"


def _level(meta: DocumentMetadata, hierarchy: Hierarchy) -> int | None:
    return next((lv.level for lv in hierarchy.levels if lv.instrument == meta.instrument), None)


def ingest(
    src: SourceDocument,
    data: bytes,
    *,
    stores: IngestionStores,
    departments: DepartmentTable,
    hierarchy: Hierarchy,
    confidence_threshold: float | None,
    ocr_confidence: dict[int, float] | None = None,
    open_files: frozenset[str] = frozenset(),
) -> IngestResult:
    version = _version(data)
    key = (src.source_uri, version)
    if key in stores.results:
        return stores.results[key].model_copy(update={"status": IngestStatus.DUPLICATE})
    if (
        version in stores.by_content
    ):  # same bytes from another source: one document, not a collision
        first = stores.by_content[version]
        return _record(
            stores,
            key,
            first.model_copy(
                update={"source_uri": src.source_uri, "status": IngestStatus.DUPLICATE}
            ),
        )
    at = src.received_at
    q = stores.queue

    def held(
        reason_items: list[ReviewItem], meta: DocumentMetadata | None = None, cid: str | None = None
    ) -> IngestResult:
        res = IngestResult(
            source_uri=src.source_uri,
            version=version,
            status=IngestStatus.HELD,
            canonical_id=cid,
            doc_type=meta.doc_type.value if meta else None,
            review_items=tuple(reason_items),
        )
        return _record(stores, key, res)

    # 1-3 · detect, extract, gate
    detection = detect(data, src.filename)
    try:
        extracted = extract_native(data, detection)
    except ExtractionError as exc:
        return held([q.submit(ReviewKind.UNSUPPORTED_FILE, src.source_uri, version, str(exc), at)])
    ex = Extraction(
        doc_id=src.source_uri,
        version=version,
        detection=detection,
        page_confidence=ocr_confidence or {},
    )
    decision = gate(ex, confidence_threshold, q, at)
    if not indexable(ex, decision, q) or not extracted.complete:
        items = [decision.review_item] if decision.review_item else []
        return held(items)

    # 4 · metadata
    text = extracted.native_text
    meta = extract_metadata(text, departments, source_department=src.tags.department)
    reasons: list[ReviewItem] = []
    if meta.department_source == "text" and meta.department != src.tags.department:
        reasons.append(
            q.submit(
                ReviewKind.DEPARTMENT_MISMATCH,
                src.source_uri,
                version,
                f"text names {meta.department} ≠ source tag {src.tags.department}",
                at,
            )
        )
    marks = {m.group(1) for m in _CLASS_MARK.finditer("\n".join(text.splitlines()[:5]))}
    if marks and marks != {src.tags.classification}:
        reasons.append(
            q.submit(
                ReviewKind.CLASSIFICATION_MISMATCH,
                src.source_uri,
                version,
                f"classification marking {sorted(marks)} ≠ source tag {src.tags.classification}",
                at,
            )
        )

    # 5 · canonical ID (printed number, or e-File number for notes / reports / annexures)
    base: str | None = meta.canonical_id
    if base is None and meta.doc_type in _EFILE_TYPE and meta.file_no:
        try:
            base = efile_document_id(meta.file_no, _EFILE_TYPE[meta.doc_type])
        except InvalidCanonicalIdError:
            base = None
    if base is None:
        reasons.append(
            q.submit(
                ReviewKind.UNRESOLVED_REFERENCE,
                src.source_uri,
                version,
                "; ".join(meta.review_reasons) or "no canonical ID",
                at,
            )
        )
        return held(reasons, meta)
    try:
        assignment = stores.collisions.assign(base, src.source_uri, section_label=src.tags.section)
    except CollisionError as exc:
        reasons.append(q.submit(ReviewKind.ID_COLLISION, src.source_uri, version, str(exc), at))
        return held(reasons, meta)
    cid = assignment.canonical_id
    if reasons:
        return held(reasons, meta, cid)

    # 6 · index, graph, temporal facts (superseded versions of the same source are kept)
    tags = src.tags.model_copy(update={"doc_id": cid})
    stores.index.upsert(
        IndexedDocument(
            canonical_id=cid,
            tags=tags,
            doc_type=meta.doc_type.value,
            issue_date=meta.issue_date,
            subject=meta.subject or "",
        )
    )
    stores.graph.upsert_node(GraphNode(canonical_id=cid, tags=tags))
    level = _level(meta, hierarchy)
    if level is not None:
        stores.instruments[cid] = Instrument(
            canonical_id=cid,
            hierarchy_level=level,
            effective_from=meta.issue_date,
            valid_until=meta.valid_until,
        )
    if meta.doc_type in _ORDER_DOC_TYPES:
        stores.windows[cid] = windows_from_text(cid, text)
    added, pending = _add_edges(stores, cid, meta)
    added += _attach_pending(stores, cid)
    rec = reconcile(stores, cid, meta, tags, version=version, at=at, open_files=open_files)
    added += list(rec.file_edges)
    pending = [p for p in pending if not p.startswith("CITES→file:")]
    touched = {cid} | {r.target for r in meta.relations if r.kind in _TEMPORAL and r.resolved}
    invalidated = stores.cache.invalidate_documents(frozenset(touched))
    res = IngestResult(
        source_uri=src.source_uri,
        version=version,
        status=IngestStatus.INDEXED,
        canonical_id=cid,
        doc_type=meta.doc_type.value,
        edges_added=tuple(added),
        pending_edges=tuple(pending),
        invalidated_answers=invalidated,
        review_items=rec.inferred,
        notices=rec.notices,
    )
    stores.by_content.setdefault(version, res)
    return _record(stores, key, res)


def _record(stores: IngestionStores, key: tuple[str, str], res: IngestResult) -> IngestResult:
    stores.results[key] = res
    versions = stores.versions.setdefault(key[0], [])
    if key[1] not in versions:
        versions.append(key[1])
    return res


def _resolve_target(stores: IngestionStores, target: str) -> str | None:
    """Exact ID, then the ID without its date tag; a reference printed without a date (base ID)
    matches a dated stored ID only when exactly one stored ID has that base — else it waits."""
    try:
        keys = lookup_keys(target)
        base = parse_canonical_id(target).base_id
    except InvalidCanonicalIdError:
        return None
    if hit := next((k for k in keys if stores.graph.node(k) is not None), None):
        return hit
    same_base = [n for n in stores.graph.node_ids() if _base(n) == base]
    return same_base[0] if len(same_base) == 1 else None


def _base(cid: str) -> str | None:
    try:
        return parse_canonical_id(cid).base_id
    except InvalidCanonicalIdError:
        return None


def _add_edges(
    stores: IngestionStores, cid: str, meta: DocumentMetadata
) -> tuple[list[str], list[str]]:
    added: list[str] = []
    pending: list[str] = []
    for rel in meta.relations:
        if not rel.resolved:
            pending.append(f"{rel.kind.value}→{rel.target}")  # e.g. file:… (file-index match later)
            continue
        edge_kind = EdgeKind(rel.kind.value)
        target = _resolve_target(stores, rel.target)
        if target is None:
            stores.pending.append(
                GraphEdge(source=cid, kind=edge_kind, target=rel.target, confirmed=rel.explicit)
            )
            pending.append(f"{rel.kind.value}→{rel.target}")
            continue
        stores.graph.upsert_edge(
            GraphEdge(source=cid, kind=edge_kind, target=target, confirmed=rel.explicit)
        )
        if rel.kind in _TEMPORAL:
            stores.relations.append(
                TemporalRelation(
                    source=cid, kind=_TEMPORAL[rel.kind], target=target, confirmed=rel.explicit
                )
            )
        added.append(f"{rel.kind.value}→{target}")
    return added, pending


def _attach_pending(stores: IngestionStores, cid: str) -> list[str]:
    """Edges that were waiting for `cid` attach now (plan §7.2 reconciliation)."""
    attached: list[str] = []
    still: list[GraphEdge] = []
    for e in stores.pending:
        if _base(e.target) == _base(cid):
            stores.graph.upsert_edge(e.model_copy(update={"target": cid}))
            if e.kind.value in {k.value for k in _TEMPORAL}:
                stores.relations.append(
                    TemporalRelation(
                        source=e.source,
                        kind=RelationKind(e.kind.value),
                        target=cid,
                        confirmed=e.confirmed,
                    )
                )
            attached.append(f"{e.source}:{e.kind.value}→{cid}")
        else:
            still.append(e)
    stores.pending = still
    return attached
