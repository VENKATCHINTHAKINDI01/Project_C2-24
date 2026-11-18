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
from collections.abc import MutableMapping
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.auth.models import DocumentAccessTags
from app.cache.answers import AnswerCache, InMemoryAnswerCache
from app.cache.semantic import SemanticIndex
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
from app.ingestion.document_store import media_type
from app.ingestion.extract import (
    ExtractedDocument,
    ExtractionError,
    PageSource,
    extract_native,
    pdf_text_layer,
)
from app.ingestion.gate import Extraction, gate, indexable
from app.ingestion.metadata import (
    GAZETTE_DEPARTMENT,
    DocType,
    DocumentMetadata,
    RelKind,
    extract_metadata,
    with_printed_masthead,
)
from app.ingestion.ocr import OcrEngine, OcrError, OcrPage, OcrResult
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
    DocType.FILE_RECORD: "FILE",
}
_TEMPORAL = {
    RelKind.SUPERSEDES: RelationKind.SUPERSEDES,
    RelKind.AMENDS: RelationKind.AMENDS,
    RelKind.CLARIFIES: RelationKind.CLARIFIES,
    RelKind.REPEALS: RelationKind.REPEALS,
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
_EMPTY = OcrPage(page=0, text="")
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
    # A paper the officer attached to an e-File. One without a number of its own (a letter, a
    # statement) is filed under the e-File's number as an annexure (ANX + registry suffix); one
    # whose own number cannot be resolved is held for review as before — never renumbered.
    attachment: bool = False
    event: str = "loaded"  # what brought it in: loaded / file_created / note_confirmed / issued …


class RecordVersion(BaseModel):
    """One version of a record as it entered institutional memory (CLAUDE.md §5.8: kept, never
    deleted). The newest is the one indexed; status (in force / superseded) is worked out from
    the temporal facts on the day asked, never stored here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    source_uri: str
    received_at: dt.datetime
    event: str


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
    cache: AnswerCache = field(default_factory=InMemoryAnswerCache)
    # reworded repeats (plan §10.3; ADR-0053): off until the runtime config turns it on
    reworded: SemanticIndex = field(default_factory=lambda: SemanticIndex(enabled=False))
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
    # source doc id → its access tags, while the record waits in review (not indexed). Lets the
    # citation review say "may be awaiting review" instead of "not found" (type E); never shown.
    awaiting: dict[str, DocumentAccessTags] = field(default_factory=dict)
    # OCR drafts by file version (plan §4.2): what the reviewer sees; never indexed until confirmed.
    # Content-addressed, so the same scan is never OCR'd (or billed) twice.
    ocr_drafts: dict[str, OcrResult] = field(default_factory=dict)
    # Reviewer-confirmed (possibly corrected) text by file version; what gets indexed.
    # A mapping, so it can be kept in Postgres (`PostgresConfirmedText`) and survive restarts.
    confirmed_text: MutableMapping[str, str] = field(default_factory=dict)
    # The text each indexed version was read from (native, OCR-confirmed or corrected).
    text_of: dict[str, str] = field(default_factory=dict)
    # canonical ID → its versions, oldest first (every version that was indexed)
    history: dict[str, list[RecordVersion]] = field(default_factory=dict)


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
    ocr: OcrEngine | None = None,
    after_review: bool = False,
) -> IngestResult:
    """Ingest one file (plan §4). With an `ocr` engine, image-only pages are OCR'd and the draft is
    kept for review; `after_review=True` re-runs a held file once its review items are decided."""
    version = _version(data)
    key = (src.source_uri, version)
    prior = stores.results.get(key)
    if prior is not None and not (after_review and prior.status is IngestStatus.HELD):
        return prior.model_copy(update={"status": IngestStatus.DUPLICATE})
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
        stores.awaiting[src.tags.doc_id] = src.tags
        return _record(stores, key, res)

    # 1-3 · detect, extract, gate
    detection = detect(data, src.filename)
    try:
        extracted = extract_native(data, detection)
    except ExtractionError as exc:
        return held([q.submit(ReviewKind.UNSUPPORTED_FILE, src.source_uri, version, str(exc), at)])
    need = [pg.page for pg in extracted.pages if pg.source is PageSource.NEEDS_OCR]
    draft = stores.ocr_drafts.get(version)
    if need and draft is None and ocr is not None:
        try:
            draft = ocr.read(data, media_type(data, src.filename), need)
        except OcrError as exc:  # fail closed: the file waits in review, nothing is guessed
            reason = f"OCR failed: {exc}"[:500]
            return held(
                [
                    q.submit(
                        ReviewKind.LOW_CONFIDENCE_EXTRACTION, src.source_uri, version, reason, at
                    )
                ]
            )
        stores.ocr_drafts[version] = draft
    confidence = dict(ocr_confidence or {})
    if draft is not None:
        confidence.update(
            {pg.page: pg.confidence for pg in draft.pages if pg.confidence is not None}
        )
    ex = Extraction(
        doc_id=src.source_uri,
        version=version,
        detection=detection,
        page_confidence=confidence,
    )
    decision = gate(ex, confidence_threshold, q, at)
    confirmed = stores.confirmed_text.get(version)
    ocr_complete = draft is not None and all(
        (op := draft.page(n)) is not None and op.text for n in need
    )
    readable = extracted.complete or confirmed is not None or ocr_complete
    if not indexable(ex, decision, q) or not readable:
        items = [decision.review_item] if decision.review_item else []
        return held(items)

    # 4 · metadata (reviewer-confirmed text wins; else native pages + OCR pages, in page order)
    if confirmed is not None:
        text = confirmed
    elif draft is not None and need:
        text = _merge(extracted, draft)
    else:
        text = extracted.native_text
    meta = extract_metadata(text, departments, source_department=src.tags.department)
    # A gazette scan whose OCR lost the masthead that page 1's text layer prints (plan §4.3).
    # Only for files filed as gazettes: a G.O. reprinted in a gazette keeps its own G.O. ID.
    if (
        src.tags.department == GAZETTE_DEPARTMENT
        and confirmed is None
        and extracted.pages
        and extracted.pages[0].source is PageSource.NEEDS_OCR
        and (merged := with_printed_masthead(text, pdf_text_layer(data, 1))) is not None
    ):
        text = merged
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
    own_unresolved = any(r.startswith("own reference") for r in meta.review_reasons)
    if base is None and src.attachment and src.tags.file_no and not own_unresolved:
        try:  # a paper filed in the e-File with no number of its own (the source says which file)
            base = efile_document_id(src.tags.file_no, "ANX")
            meta = meta.model_copy(update={"doc_type": DocType.ANNEXURE})
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
            # an order governs from its issue at the earliest: a stated later commencement counts
            # (not yet effective until then); a retrospective "with effect from" does not move it
            # earlier (nobody could apply it before it was issued)
            effective_from=max(meta.issue_date, meta.stated_effective_from)
            if meta.issue_date and meta.stated_effective_from
            else meta.issue_date,
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
    stores.text_of[version] = text
    stores.history.setdefault(cid, []).append(
        RecordVersion(version=version, source_uri=src.source_uri, received_at=at, event=src.event)
    )
    stores.awaiting.pop(src.tags.doc_id, None)
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


def _merge(extracted: ExtractedDocument, draft: OcrResult) -> str:
    """Native pages as extracted, OCR pages from the draft, in page order."""
    return "\n".join(
        (pg.text or "") if pg.source is PageSource.NATIVE else (draft.page(pg.page) or _EMPTY).text
        for pg in extracted.pages
    )


def review_text(data: bytes, filename: str, draft: OcrResult) -> str:
    """The whole document as it would be indexed if the reviewer confirms the draft unchanged
    (plan §4.2): what the review screen shows and lets the reviewer correct."""
    return _merge(extract_native(data, detect(data, filename)), draft)


class ConfirmError(Exception):
    """Nothing to confirm: no pending OCR review for this file version."""


def confirm_extraction(
    src: SourceDocument,
    data: bytes,
    *,
    reviewer: str,
    reason: str,
    at: dt.datetime,
    stores: IngestionStores,
    departments: DepartmentTable,
    hierarchy: Hierarchy,
    confidence_threshold: float | None,
    corrected_text: str | None = None,
    open_files: frozenset[str] = frozenset(),
) -> IngestResult:
    """Human review of an OCR'd file (plan §4.2, §9.1; CLAUDE.md §8). The reviewer confirms the
    draft, or confirms corrected text. The decision is recorded on the review item (who, when,
    why). The file is then re-run through the pipeline, so the rest of the checks still apply, and
    the indexed record keeps the scan's own version, so preview serves the scan (ADR-0014)."""
    version = _version(data)
    draft = stores.ocr_drafts.get(version)
    if draft is None and corrected_text is None:
        raise ConfirmError("no OCR draft for this file; run OCR or supply the confirmed text")
    pending = [
        i
        for i in stores.queue.pending(ReviewKind.LOW_CONFIDENCE_EXTRACTION)
        if i.subject == src.source_uri and i.version == version
    ]
    if not pending:
        raise ConfirmError("no pending extraction review for this file version")
    if corrected_text is not None and not corrected_text.strip():
        raise ConfirmError("confirmed text is empty")
    if corrected_text is None and draft is not None and not any(pg.text for pg in draft.pages):
        raise ConfirmError("the OCR draft is empty; supply the confirmed text")
    for item in pending:
        stores.queue.decide(item.item_id, reviewer=reviewer, confirm=True, reason=reason, at=at)
    if corrected_text is not None:  # the whole document as the reviewer confirmed it
        stores.confirmed_text[version] = corrected_text
    # else: native pages + the confirmed OCR pages, merged in page order by `ingest`
    return ingest(
        src,
        data,
        stores=stores,
        departments=departments,
        hierarchy=hierarchy,
        confidence_threshold=confidence_threshold,
        open_files=open_files,
        after_review=True,
    )
