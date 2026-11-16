"""Assist runtime: the reference stores the assistant answers from, built by the normal ingestion
pipeline from what the e-Office connector hands over (plan §11.3 'Events in', §3, §5.6).

One runtime per process. Per request, the officer's grants are re-read from the connector into a
fresh access store, so a permission change takes effect on the next call (CLAUDE.md §4.9).
Nothing here reads the evaluation ground truth: documents and their access tags come only from
the connector; scanned pages without OCR stay in the review queue, not in the index.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path

from app.agents.llm import LLMClient
from app.agents.tools import ToolContext
from app.auth.models import AccessPolicy, DocumentAccessTags
from app.auth.policy import ScopeError, load_access_policy, scope_for
from app.auth.store import InMemoryAuthzStore
from app.config import Classification, Hierarchy
from app.conflict.procedural import AuthorityRules, load_authority_rules
from app.connectors.eoffice import (
    EOfficeConnector,
    EventKind,
    OfficerContext,
    SourceArtefact,
    grants_from_context,
)
from app.graph.repository import WalkableGraph
from app.hitl.queue import ReviewItem, ReviewQueue
from app.identifiers.resolver import DepartmentTable, load_departments
from app.ingestion.detect import detect
from app.ingestion.document_store import (
    DocumentStore,
    InMemoryDocumentStore,
    StoredDocument,
    media_type,
)
from app.ingestion.extract import extract_native
from app.ingestion.ocr import OcrEngine
from app.ingestion.pipeline import (
    IngestionStores,
    IngestResult,
    IngestStatus,
    SourceDocument,
    confirm_extraction,
    ingest,
)
from app.noting.references import ReferenceConfig
from app.retrieval.cloud import CloudRungs
from app.retrieval.composite import CompositeGraph, CompositeHybrid, CompositeScopedIndex
from app.retrieval.ladder import HybridRetriever, InMemoryKeywordIndex, LadderConfig
from app.retrieval.scoped import IndexedDocument, ScopedRetriever
from app.temporal.windows import ActionWindow


class _FallbackTexts(Mapping[str, str]):
    """Memory first, then one cloud read per record asked for (never a listing)."""

    def __init__(self, first: Mapping[str, str], fetch: Callable[[str], str]) -> None:
        self._first, self._fetch = first, fetch
        self._seen: dict[str, str] = {}

    def __getitem__(self, cid: str) -> str:
        if cid in self._first:
            return self._first[cid]
        if cid not in self._seen:
            self._seen[cid] = self._fetch(cid)
        if not self._seen[cid]:
            raise KeyError(cid)
        return self._seen[cid]

    def __iter__(self) -> Iterator[str]:
        return iter(self._first)

    def __len__(self) -> int:
        return len(self._first)


@dataclass
class AssistRuntime:
    stores: IngestionStores
    departments: DepartmentTable
    hierarchy: Hierarchy
    classification: Classification
    policy: AccessPolicy
    rules: AuthorityRules
    cfg: LadderConfig
    calibrated: bool  # False: thresholds are labelled demo values, not calibrated (sandbox)
    l2: InMemoryKeywordIndex
    texts: dict[str, str]  # canonical ID → extracted text (L2 stand-in, evidence later)
    as_of: dt.date
    indexed: int
    held: int  # documents waiting in the review queue (e.g. scans with no OCR yet)
    held_by_file: dict[str, list[DocumentAccessTags]]  # e-File → access tags of held documents

    open_files: frozenset[str] = frozenset()
    references: ReferenceConfig | None = None  # touchpoint 7 matching; None = not configured
    cursor: dt.datetime = dt.datetime.min.replace(tzinfo=dt.UTC)  # last connector event seen
    # ADR-0014: the stored source bytes, and canonical ID → the version its text came from
    documents: DocumentStore = field(default_factory=InMemoryDocumentStore)
    sources: dict[str, str] = field(default_factory=dict)
    ocr: OcrEngine | None = None  # None: scans wait in review unread (no OCR configured)
    # source artefacts by URI, for human review of held files (plan §4.2)
    artefacts: dict[str, tuple[SourceArtefact, dt.datetime]] = field(default_factory=dict)
    # SANDBOX, owner decision 13 Nov 2026 (ADR-0020): real public orders (public://, UNCLASSIFIED)
    # whose lowest OCR page confidence reaches this value skip the review queue. NOT a calibrated
    # gate and NOT a human review: such documents are listed in `auto_passed`. None = off.
    public_ocr_auto_pass: float | None = None
    llm: LLMClient | None = None  # Gemini for B / G judgment (plan §6.5); None: not checked
    auto_passed: dict[str, float] = field(default_factory=dict)  # source URI → lowest confidence
    cloud: CloudRungs | None = None  # public corpus read from BigQuery / Cloud SQL (ADR-0028)

    @classmethod
    def build(
        cls,
        artefacts: Iterable[SourceArtefact],
        *,
        ontology_dir: Path,
        hierarchy: Hierarchy,
        classification: Classification,
        cfg: LadderConfig,
        calibrated: bool,
        as_of: dt.date,
        received_at: dt.datetime,
        open_files: frozenset[str] = frozenset(),
        references: ReferenceConfig | None = None,
        ocr: OcrEngine | None = None,
        documents: DocumentStore | None = None,
        queue: ReviewQueue | None = None,
        confirmed_text: MutableMapping[str, str] | None = None,
        public_ocr_auto_pass: float | None = None,
        llm: LLMClient | None = None,
        rules_file: str = "authority_rules.yaml",
    ) -> AssistRuntime:
        """`queue` / `confirmed_text`: persistent state (Postgres) so review decisions made before a
        restart still apply when the corpus is re-ingested; in memory when not given."""
        stores = IngestionStores(queue=queue or ReviewQueue())
        if confirmed_text is not None:
            stores.confirmed_text = confirmed_text
        run = cls(
            stores=stores,
            departments=load_departments(ontology_dir / "departments.yaml"),
            hierarchy=hierarchy,
            classification=classification,
            policy=load_access_policy(ontology_dir / "access_policy.yaml"),
            rules=load_authority_rules(ontology_dir / rules_file),
            cfg=cfg,
            calibrated=calibrated,
            l2=InMemoryKeywordIndex(()),
            texts={},
            as_of=as_of,
            indexed=0,
            held=0,
            held_by_file={},
            open_files=open_files,
            references=references,
            ocr=ocr,
            documents=documents or InMemoryDocumentStore(),
            public_ocr_auto_pass=public_ocr_auto_pass,
            llm=llm,
        )
        for a in artefacts:
            run._ingest(a, received_at)
        run._reindex_l2()
        return run

    def _ingest(self, a: SourceArtefact, received_at: dt.datetime) -> IngestResult:
        self.artefacts[a.source_uri] = (a, received_at)
        src = self._src(a, received_at)
        res = ingest(
            src,
            a.data,
            stores=self.stores,
            departments=self.departments,
            hierarchy=self.hierarchy,
            confidence_threshold=self._auto_pass_for(a),  # None (uncalibrated) → OCR'd pages wait
            open_files=self.open_files,
            ocr=self.ocr,
        )
        if self._auto_pass_for(a) is not None and res.status is IngestStatus.INDEXED:
            draft = self.stores.ocr_drafts.get(res.version)
            confs = [
                p.confidence for p in (draft.pages if draft else ()) if p.confidence is not None
            ]
            if confs:
                self.auto_passed[a.source_uri] = min(confs)
        return self._account(res, a, src)

    def _auto_pass_for(self, a: SourceArtefact) -> float | None:
        """Only the real public orders in the sandbox; never synthetic or classified material."""
        if (
            self.public_ocr_auto_pass is not None
            and a.source_uri.startswith("public://")
            and a.classification == self.policy.public_classification
        ):
            return self.public_ocr_auto_pass
        return None

    @staticmethod
    def _src(a: SourceArtefact, received_at: dt.datetime) -> SourceDocument:
        return SourceDocument(
            source_uri=a.source_uri,
            filename=a.filename,
            tags=DocumentAccessTags(
                doc_id=a.source_uri,
                department=a.department,
                section=a.section,
                classification=a.classification,
                file_no=a.file_no,
            ),
            received_at=received_at,
        )

    def _account(self, res: IngestResult, a: SourceArtefact, src: SourceDocument) -> IngestResult:
        if res.status is IngestStatus.INDEXED and res.canonical_id:
            self.indexed += 1
            self.texts[res.canonical_id] = (
                self.stores.text_of.get(res.version)
                or extract_native(a.data, detect(a.data, a.filename)).native_text
            )
            self.documents.put(
                StoredDocument(
                    version=res.version, media_type=media_type(a.data, a.filename), data=a.data
                )
            )
            self.sources[res.canonical_id] = res.version  # the exact version cited (rule 3)
        elif res.status is IngestStatus.HELD:
            self.held += 1
            if a.file_no:
                self.held_by_file.setdefault(a.file_no, []).append(src.tags)
        return res

    def review_ocr(
        self,
        item: ReviewItem,
        *,
        reviewer: str,
        confirm: bool,
        reason: str,
        at: dt.datetime,
        corrected_text: str | None = None,
    ) -> IngestResult | None:
        """Human review of an OCR'd file (plan §4.2; CLAUDE.md §8). Confirm (optionally with
        corrected text) re-runs the file through the pipeline; reject leaves it held for re-scan.
        The caller has already checked that the reviewer may see this file."""
        a, received_at = self.artefacts[item.subject]
        src = self._src(a, received_at)
        if not confirm:
            self.stores.queue.decide(
                item.item_id, reviewer=reviewer, confirm=False, reason=reason, at=at
            )
            return None
        was_held = self.stores.results.get((src.source_uri, item.version))
        res = confirm_extraction(
            src,
            a.data,
            reviewer=reviewer,
            reason=reason,
            at=at,
            stores=self.stores,
            departments=self.departments,
            hierarchy=self.hierarchy,
            confidence_threshold=None,
            corrected_text=corrected_text,
            open_files=self.open_files,
        )
        if res.status is IngestStatus.INDEXED and was_held is not None:
            self.held -= 1
            if a.file_no and a.file_no in self.held_by_file:
                rest = [t for t in self.held_by_file[a.file_no] if t.doc_id != src.tags.doc_id]
                self.held_by_file[a.file_no] = rest
            self._account(res, a, src)
            self._reindex_l2()
        return res

    def _reindex_l2(self) -> None:
        docs: list[IndexedDocument] = list(self.stores.index._docs)  # noqa: SLF001
        self.l2 = InMemoryKeywordIndex((d, self.texts.get(d.canonical_id, "")) for d in docs)

    def sync(self, connector: EOfficeConnector) -> list[IngestResult]:
        """Events in (plan §11.3): ingest documents that arrived since the last call — through
        the normal pipeline, so reconciliation, notices and cache invalidation all run."""
        events = connector.events_since(self.cursor)
        if not events:
            return []
        self.open_files = connector.open_files()
        by_uri = {a.source_uri: a for a in connector.documents()}
        out = []
        for ev in events:
            self.cursor = max(self.cursor, ev.occurred_at)
            art = by_uri.get(ev.source_uri)
            if art is not None and ev.kind in (
                EventKind.ORDER_RECEIVED,
                EventKind.RECEIPT_DIARISED,
                EventKind.FILE_CLOSED,  # the closing note sheet joins the precedent index (TP16)
            ):
                out.append(self._ingest(art, ev.occurred_at))
        self._reindex_l2()
        return out

    def letter_text(self, source_uri: str) -> tuple[str, bool, float | None] | None:
        """Text of an ingested letter: the indexed text, else the OCR draft of a scan waiting for
        review (for pre-filling only, touchpoint 1). (text, from_ocr, lowest page confidence)."""
        res = [r for (uri, _), r in self.stores.results.items() if uri == source_uri]
        if not res:
            return None
        r = res[-1]
        if r.canonical_id and r.canonical_id in self.texts:
            return self.texts[r.canonical_id], False, None
        draft = self.stores.ocr_drafts.get(r.version)
        if draft is None:
            return None
        confs = [p.confidence for p in draft.pages if p.confidence is not None]
        return "\n".join(p.text for p in draft.pages), True, (min(confs) if confs else None)

    def store_for(self, ctx: OfficerContext) -> InMemoryAuthzStore:
        """Fresh grants for this request only (never cached across requests)."""
        return InMemoryAuthzStore(grants_from_context(ctx))

    def tool_context(self, user_id: str, store: InMemoryAuthzStore) -> ToolContext:
        index: ScopedRetriever = self.stores.index
        l2: HybridRetriever = self.l2
        graph: WalkableGraph = self.stores.graph
        if self.cloud is not None:  # e-Office papers in memory + public corpus in the cloud
            index = CompositeScopedIndex((self.stores.index, self.cloud.index))
            graph = CompositeGraph((self.stores.graph, self.cloud.graph))
            if self.cloud.l2 is not None:
                l2 = CompositeHybrid(
                    ((self.l2, self.cfg.l2_min_score), (self.cloud.l2, self.cloud.l2_min_score)),
                    self.cfg.l2_min_score,
                )
        return ToolContext(
            user_id=user_id,
            as_of=self.as_of,
            index=index,
            l2=l2,
            graph=graph,
            cfg=self.cfg,
            store=store,
            policy=self.policy,
            classification=self.classification,
            hierarchy=self.hierarchy,
            instruments=self.stores.instruments,
            relations=tuple(self.stores.relations),
        )

    def evidence_texts(self, user_id: str, store: InMemoryAuthzStore) -> Mapping[str, str]:
        """Record texts for the evidence package: the in-memory texts, then (cloud backend) the
        passages of a public order held only in BigQuery, read within this officer's scope."""
        passages = self.cloud.passages if self.cloud is not None else None
        if passages is None:
            return self.texts
        try:
            scope = scope_for(user_id, store, self.policy, self.classification)
        except ScopeError:
            return self.texts  # fail closed: nothing beyond what memory re-checks per record
        return _FallbackTexts(self.texts, lambda cid: passages.text(cid, scope))

    def stored_source(
        self, canonical_id: str, user_id: str, store: InMemoryAuthzStore
    ) -> StoredDocument | None:
        """The file of a record the caller has ALREADY re-checked (ADR-0014): the version ingested
        here, else (cloud backend) the public order's file from the mounted corpus, read within
        this officer's scope and only if its bytes match the recorded hash."""
        if (version := self.sources.get(canonical_id)) is not None:
            return self.documents.get(version)
        files = self.cloud.sources if self.cloud is not None else None
        if files is None:
            return None
        try:
            scope = scope_for(user_id, store, self.policy, self.classification)
        except ScopeError:
            return None  # fail closed
        return files.get(canonical_id, scope)

    def tags(self, cid: str) -> DocumentAccessTags | None:
        node = self.stores.graph.node(cid)
        return node.tags if node else None

    def doc(self, cid: str) -> IndexedDocument | None:
        return next((d for d in self.stores.index._docs if d.canonical_id == cid), None)  # noqa: SLF001

    def windows(self) -> list[ActionWindow]:
        return [w for ws in self.stores.windows.values() for w in ws]
