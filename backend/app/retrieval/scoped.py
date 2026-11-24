"""Permission-enforced retrieval for rungs L0 (exact ID) and L1 (filter) (plan §3.2, §5.2).

Every retriever method REQUIRES a `Scope` and applies it before matching, so restricted documents
are never candidates (CLAUDE.md §4.2). `retrieve` then re-checks each survivor against the
officer's current grants. The in-memory index is the reference/fake for BigQuery templates.
Metadata only: no document text passes through here.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from app.auth.models import AccessPolicy, DocumentAccessTags, Scope
from app.auth.policy import ScopeError, check, scope_for
from app.auth.store import AuthzStore
from app.config import Classification
from app.identifiers.canonical import InvalidCanonicalIdError, lookup_keys, parse_canonical_id

log = logging.getLogger(__name__)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class IndexedDocument(_Frozen):
    canonical_id: str
    tags: DocumentAccessTags
    doc_type: str
    issue_date: dt.date | None
    subject: str


class Rung(StrEnum):
    L0 = "L0"
    L1 = "L1"


class L1Criteria(_Frozen):
    """Fixed template slots (plan §3.2): the LLM fills slots, never writes queries."""

    department: str | None = None
    doc_types: frozenset[str] = frozenset()
    issued_from: dt.date | None = None
    issued_to: dt.date | None = None
    subject_terms: tuple[str, ...] = ()


class ScopedRetriever(Protocol):
    def exact(self, canonical_id: str, scope: Scope) -> list[IndexedDocument]: ...

    def filter(self, criteria: L1Criteria, scope: Scope) -> list[IndexedDocument]: ...


class InMemoryScopedIndex:
    """Reference ScopedRetriever. Scope is applied first, then the template's own predicate."""

    def __init__(self, docs: Iterable[IndexedDocument] = ()) -> None:
        self._docs = list(docs)
        self._ids: dict[str, list[IndexedDocument]] | None = None
        self._bases: dict[str, list[IndexedDocument]] | None = None

    def upsert(self, doc: IndexedDocument) -> None:
        """Insert or replace by canonical ID (ingestion; plan §7.4)."""
        self._docs = [d for d in self._docs if d.canonical_id != doc.canonical_id] + [doc]
        self._ids = self._bases = None

    def remove(self, canonical_id: str) -> None:
        self._docs = [d for d in self._docs if d.canonical_id != canonical_id]
        self._ids = self._bases = None

    def _by(self) -> tuple[dict[str, list[IndexedDocument]], dict[str, list[IndexedDocument]]]:
        """Records by canonical ID and by base ID, in store order; rebuilt after a change.
        A lookup then scope-checks only its own candidates, not every record held (24 Nov 2026:
        each L0 lookup used to check the whole store)."""
        if self._ids is None or self._bases is None:
            ids: dict[str, list[IndexedDocument]] = {}
            bases: dict[str, list[IndexedDocument]] = {}
            for d in self._docs:
                ids.setdefault(d.canonical_id, []).append(d)
                if (base := _base_id(d.canonical_id)) is not None:
                    bases.setdefault(base, []).append(d)
            self._ids, self._bases = ids, bases
        return self._ids, self._bases

    def __len__(self) -> int:
        return len(self._docs)

    def first(self, canonical_id: str) -> IndexedDocument | None:
        """The first record held under exactly this ID, unscoped — for internal bookkeeping only
        (e.g. a record's own access tags); never returned to an officer without a check."""
        hits = self._by()[0].get(canonical_id)
        return hits[0] if hits else None

    def _in_scope(self, scope: Scope) -> list[IndexedDocument]:
        return [d for d in self._docs if scope.admits(d.tags)]

    def exact(self, canonical_id: str, scope: Scope) -> list[IndexedDocument]:
        try:
            keys = lookup_keys(canonical_id)
        except InvalidCanonicalIdError:
            return []
        ids, bases = self._by()
        for key in keys:  # exact ID first, then pre-ADR-0007 form
            hits = [d for d in ids.get(key, ()) if scope.admits(d.tags)]
            if hits:
                return hits
        if len(keys) == 1:  # printed without its date: every dated record with that base, in scope
            return [d for d in bases.get(keys[0], ()) if scope.admits(d.tags)]
        return []

    def filter(self, criteria: L1Criteria, scope: Scope) -> list[IndexedDocument]:
        out = []
        for d in self._in_scope(scope):
            if criteria.department and d.tags.department != criteria.department:
                continue
            if criteria.doc_types and d.doc_type not in criteria.doc_types:
                continue
            if criteria.issued_from and (
                d.issue_date is None or d.issue_date < criteria.issued_from
            ):
                continue
            if criteria.issued_to and (d.issue_date is None or d.issue_date > criteria.issued_to):
                continue
            subj = d.subject.lower()
            if any(t.lower() not in subj for t in criteria.subject_terms):
                continue
            out.append(d)
        return sorted(
            out, key=lambda d: (d.issue_date or dt.date.min, d.canonical_id), reverse=True
        )


class RetrievalResult(_Frozen):
    rung: Rung
    scope_signature: str | None
    documents: tuple[IndexedDocument, ...]


def retrieve(
    user_id: str,
    rung: Rung,
    query: str | L1Criteria,
    *,
    retriever: ScopedRetriever,
    store: AuthzStore,
    policy: AccessPolicy,
    classification: Classification,
) -> RetrievalResult:
    """Both enforcement layers around one rung (plan §5.2, §5.9).

    1. scope from the officer's CURRENT grants (store) — failure → empty result, never unscoped;
    2. retriever runs inside the scope;
    3. every survivor is re-checked against the store before it can reach an evidence package.
    "Absent" and "not allowed" return the same empty result (no existence leak, plan §5.4).
    """
    try:
        scope = scope_for(user_id, store, policy, classification)
    except ScopeError:
        return RetrievalResult(rung=rung, scope_signature=None, documents=())
    if rung is Rung.L0 and isinstance(query, str):
        hits = retriever.exact(query, scope)
    elif rung is Rung.L1 and isinstance(query, L1Criteria):
        hits = retriever.filter(query, scope)
    else:
        raise TypeError("query type does not match rung")
    kept = tuple(d for d in hits if check(user_id, d.tags, store, policy, classification).allowed)
    if len(kept) != len(hits):  # scope and re-check disagree: a bug, never silently served
        log.error("re-check removed %d in-scope hits user=%s", len(hits) - len(kept), user_id)
    return RetrievalResult(rung=rung, scope_signature=scope.signature, documents=kept)


def count_authorised(result: RetrievalResult) -> int:
    """Counts are computed only over the authorised set (plan §5.4)."""
    return len(result.documents)


def _base_id(cid: str) -> str | None:
    """ADR-0007: the ID without its ``-D<yyyymmdd>`` tag. A reference printed without a date
    ("Circular Memo No.USD01-WRKS0/9/2023") names the base; one dated record in scope → found,
    several → the reference lookup reports AMBIGUOUS and asks the officer."""
    try:
        return parse_canonical_id(cid).base_id
    except InvalidCanonicalIdError:
        return None
