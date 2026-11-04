"""Relationship reconciliation after a document is indexed (plan §7.2, §7.3; touchpoint 4).

1. e-File citations: a note citing "file No.X" is linked to the documents of file X dated on or
   before the note (a note cannot cite later proceedings). Earlier documents that arrive later
   attach when they arrive.
2. Inferred supersession (§7.3): a newer order of the same department and type whose subject is
   identical once years, numbers and dates are removed, with no explicit relation either way, is
   queued for an officer to confirm. The edge is stored UNCONFIRMED and never flips a status alone.
   Exact match only — no similarity threshold to tune.
3. Open-file notices (touchpoint 4): when an order is explicitly superseded, repealed or amended,
   the OPEN files whose notes cite it are listed. Notices are filtered per officer: each officer
   sees only the files and documents they may access (plan §5.4).
"""

from __future__ import annotations

import datetime as dt
import re
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

from app.auth.models import AccessPolicy, DocumentAccessTags
from app.auth.policy import check
from app.auth.store import AuthzStore
from app.config import Classification
from app.graph.repository import EdgeKind, GraphEdge
from app.hitl.queue import ReviewItem, ReviewKind
from app.ingestion.metadata import DocumentMetadata, RelKind
from app.temporal.engine import RelationKind, TemporalRelation

if TYPE_CHECKING:
    from app.ingestion.pipeline import IngestionStores

ORDER_TYPES = frozenset(
    {"Government Order", "Amendment", "Circular", "Clarification", "Memo", "Standing Order"}
)
CHANGING = (EdgeKind.SUPERSEDES, EdgeKind.REPEALS, EdgeKind.AMENDS)
CITING = (EdgeKind.CITES, EdgeKind.REFERENCES)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AffectedFile(_Frozen):
    file_no: str
    citing_doc: str  # canonical ID of the note that cites the changed order
    citing_tags: DocumentAccessTags


class OpenFileNotice(_Frozen):
    """Touchpoint 4: an order changed; these open files rely on the old one."""

    new_doc: str
    changed_doc: str
    change: EdgeKind
    new_tags: DocumentAccessTags
    changed_tags: DocumentAccessTags
    affected: tuple[AffectedFile, ...]


class ReconcileOutcome(_Frozen):
    file_edges: tuple[str, ...] = ()
    inferred: tuple[ReviewItem, ...] = ()
    notices: tuple[OpenFileNotice, ...] = ()


def norm_subject(subject: str) -> str:
    s = subject.lower()
    s = re.sub(r"\d{1,2}[-./]\d{1,2}[-./]\d{2,4}", " ", s)
    s = re.sub(r"\d+", " ", s)
    s = re.sub(r"[^a-z]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def reconcile(
    stores: IngestionStores,
    cid: str,
    meta: DocumentMetadata,
    tags: DocumentAccessTags,
    *,
    version: str,
    at: dt.datetime,
    open_files: frozenset[str],
) -> ReconcileOutcome:
    file_edges = _file_citations(stores, cid, meta, tags)
    inferred = _infer_supersession(stores, cid, meta, tags, version, at)
    notices = _notices(stores, cid, open_files)
    stores.notices.extend(notices)
    return ReconcileOutcome(
        file_edges=tuple(file_edges), inferred=tuple(inferred), notices=tuple(notices)
    )


# ---- 1. e-File citations --------------------------------------------------------------------


def _link(stores: IngestionStores, source: str, target: str) -> str:
    stores.graph.upsert_edge(
        GraphEdge(source=source, kind=EdgeKind.CITES, target=target, confirmed=True)
    )
    return f"{source}:CITES→{target}"


def _file_citations(
    stores: IngestionStores, cid: str, meta: DocumentMetadata, tags: DocumentAccessTags
) -> list[str]:
    added: list[str] = []
    if tags.file_no:
        stores.files.setdefault(tags.file_no, []).append((cid, meta.issue_date))
        for src, file_no, cited_on in stores.pending_files:  # earlier proceedings arriving late
            if file_no == tags.file_no and src != cid and _not_after(meta.issue_date, cited_on):
                added.append(_link(stores, src, cid))
    for rel in meta.relations:
        if rel.kind is not RelKind.CITES or not rel.target.startswith("file:"):
            continue
        file_no = rel.target.removeprefix("file:")
        stores.pending_files.append((cid, file_no, meta.issue_date))  # kept: later arrivals attach
        for target, issued in stores.files.get(file_no, []):
            if target != cid and _not_after(issued, meta.issue_date):
                added.append(_link(stores, cid, target))
    return added


def _not_after(issued: dt.date | None, cited_on: dt.date | None) -> bool:
    return issued is not None and cited_on is not None and issued <= cited_on


# ---- 2. inferred supersession (§7.3) --------------------------------------------------------


def _explicitly_linked(stores: IngestionStores, a: str, b: str) -> bool:
    return any(
        e.target in (a, b) and e.kind in CHANGING
        for n in (a, b)
        for e in stores.graph.edges_from(n)
        if (n, e.target) in ((a, b), (b, a))
    )


def _already_superseded(stores: IngestionStores, cid: str) -> bool:
    return any(e.kind in CHANGING and e.confirmed for e in stores.graph.edges_to(cid))


def _infer_supersession(
    stores: IngestionStores,
    cid: str,
    meta: DocumentMetadata,
    tags: DocumentAccessTags,
    version: str,
    at: dt.datetime,
) -> list[ReviewItem]:
    if meta.doc_type.value not in ORDER_TYPES or not meta.subject or meta.issue_date is None:
        return []
    key = norm_subject(meta.subject)
    items: list[ReviewItem] = []
    for other in list(stores.index._docs):  # noqa: SLF001 — reference store; a metadata query on GCP
        if (
            other.canonical_id == cid
            or other.issue_date is None
            or other.issue_date == meta.issue_date
        ):
            continue
        if (other.doc_type, other.tags.department) != (meta.doc_type.value, tags.department):
            continue
        if norm_subject(other.subject) != key or _explicitly_linked(
            stores, cid, other.canonical_id
        ):
            continue
        newer, older = (
            (cid, other.canonical_id)
            if meta.issue_date > other.issue_date
            else (other.canonical_id, cid)
        )
        if _already_superseded(stores, older):
            continue
        stores.graph.upsert_edge(
            GraphEdge(source=newer, kind=EdgeKind.SUPERSEDES, target=older, confirmed=False)
        )
        stores.relations.append(
            TemporalRelation(
                source=newer, kind=RelationKind.SUPERSEDES, target=older, confirmed=False
            )
        )
        items.append(
            stores.queue.submit(
                ReviewKind.INFERRED_SUPERSESSION,
                f"{newer}→{older}",
                version,
                "same department, type and subject, newer date, no explicit statement",
                at,
            )
        )
    return items


# ---- 3. open-file notices (touchpoint 4) ----------------------------------------------------


def _tags_of(stores: IngestionStores, cid: str) -> DocumentAccessTags | None:
    node = stores.graph.node(cid)
    return node.tags if node else None


def _notices(stores: IngestionStores, cid: str, open_files: frozenset[str]) -> list[OpenFileNotice]:
    out: list[OpenFileNotice] = []
    changes = [
        (cid, e.target, e.kind)
        for e in stores.graph.edges_from(cid)
        if e.kind in CHANGING and e.confirmed
    ]
    changes += [
        (e.source, cid, e.kind)
        for e in stores.graph.edges_to(cid)
        if e.kind in CHANGING and e.confirmed
    ]
    for new, changed, kind in changes:
        affected = []
        for e in stores.graph.edges_to(changed):
            if e.kind not in CITING:
                continue
            t = _tags_of(stores, e.source)
            if t and t.file_no and t.file_no in open_files:
                affected.append(AffectedFile(file_no=t.file_no, citing_doc=e.source, citing_tags=t))
        nt, ct = _tags_of(stores, new), _tags_of(stores, changed)
        if affected and nt and ct:
            out.append(
                OpenFileNotice(
                    new_doc=new,
                    changed_doc=changed,
                    change=kind,
                    new_tags=nt,
                    changed_tags=ct,
                    affected=tuple(affected),
                )
            )
    return out


def notices_for(
    user_id: str,
    notices: list[OpenFileNotice],
    *,
    store: AuthzStore,
    policy: AccessPolicy,
    classification: Classification,
) -> list[OpenFileNotice]:
    """Per-officer view: a notice appears only if the officer may see both orders, and lists only
    the affected files they may see. Nothing is said about files they cannot see."""

    def ok(t: DocumentAccessTags) -> bool:
        return check(user_id, t, store, policy, classification).allowed

    out = []
    for n in notices:
        if not (ok(n.new_tags) and ok(n.changed_tags)):
            continue
        visible = tuple(a for a in n.affected if ok(a.citing_tags))
        if visible:
            out.append(n.model_copy(update={"affected": visible}))
    return out
