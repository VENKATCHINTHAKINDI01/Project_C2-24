"""Assist runtime: the reference stores the assistant answers from, built by the normal ingestion
pipeline from what the e-Office connector hands over (plan §11.3 'Events in', §3, §5.6).

One runtime per process. Per request, the officer's grants are re-read from the connector into a
fresh access store, so a permission change takes effect on the next call (CLAUDE.md §4.9).
Nothing here reads the evaluation ground truth: documents and their access tags come only from
the connector; scanned pages without OCR stay in the review queue, not in the index.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from app.agents.tools import ToolContext
from app.auth.models import AccessPolicy, DocumentAccessTags
from app.auth.policy import load_access_policy
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
from app.identifiers.resolver import DepartmentTable, load_departments
from app.ingestion.detect import detect
from app.ingestion.extract import extract_native
from app.ingestion.pipeline import (
    IngestionStores,
    IngestResult,
    IngestStatus,
    SourceDocument,
    ingest,
)
from app.retrieval.ladder import InMemoryKeywordIndex, LadderConfig
from app.retrieval.scoped import IndexedDocument
from app.temporal.windows import ActionWindow


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
    cursor: dt.datetime = dt.datetime.min.replace(tzinfo=dt.UTC)  # last connector event seen

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
    ) -> AssistRuntime:
        run = cls(
            stores=IngestionStores(),
            departments=load_departments(ontology_dir / "departments.yaml"),
            hierarchy=hierarchy,
            classification=classification,
            policy=load_access_policy(ontology_dir / "access_policy.yaml"),
            rules=load_authority_rules(ontology_dir / "authority_rules.yaml"),
            cfg=cfg,
            calibrated=calibrated,
            l2=InMemoryKeywordIndex(()),
            texts={},
            as_of=as_of,
            indexed=0,
            held=0,
            held_by_file={},
            open_files=open_files,
        )
        for a in artefacts:
            run._ingest(a, received_at)
        run._reindex_l2()
        return run

    def _ingest(self, a: SourceArtefact, received_at: dt.datetime) -> IngestResult:
        src = SourceDocument(
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
        res = ingest(
            src,
            a.data,
            stores=self.stores,
            departments=self.departments,
            hierarchy=self.hierarchy,
            confidence_threshold=None,  # uncalibrated → every OCR'd page goes to review
            open_files=self.open_files,
        )
        if res.status is IngestStatus.INDEXED and res.canonical_id:
            self.indexed += 1
            self.texts[res.canonical_id] = extract_native(
                a.data, detect(a.data, a.filename)
            ).native_text
        elif res.status is IngestStatus.HELD:
            self.held += 1
            if a.file_no:
                self.held_by_file.setdefault(a.file_no, []).append(src.tags)
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
            ):
                out.append(self._ingest(art, ev.occurred_at))
        self._reindex_l2()
        return out

    def store_for(self, ctx: OfficerContext) -> InMemoryAuthzStore:
        """Fresh grants for this request only (never cached across requests)."""
        return InMemoryAuthzStore(grants_from_context(ctx))

    def tool_context(self, user_id: str, store: InMemoryAuthzStore) -> ToolContext:
        return ToolContext(
            user_id=user_id,
            as_of=self.as_of,
            index=self.stores.index,
            l2=self.l2,
            graph=self.stores.graph,
            cfg=self.cfg,
            store=store,
            policy=self.policy,
            classification=self.classification,
            hierarchy=self.hierarchy,
            instruments=self.stores.instruments,
            relations=tuple(self.stores.relations),
        )

    def tags(self, cid: str) -> DocumentAccessTags | None:
        node = self.stores.graph.node(cid)
        return node.tags if node else None

    def doc(self, cid: str) -> IndexedDocument | None:
        return next((d for d in self.stores.index._docs if d.canonical_id == cid), None)  # noqa: SLF001

    def windows(self) -> list[ActionWindow]:
        return [w for ws in self.stores.windows.values() for w in ws]
