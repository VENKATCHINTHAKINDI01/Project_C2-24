"""Receipt inbox and Put in a file (plan §11.5 touchpoints 2 and 3). Deterministic.

- The receipt's diarised letter reference is resolved within the officer's scope (L0) to the
  indexed order. Not found → the receipt is shown without assistance; nothing is guessed.
- Two-line summary from the order's own record (type, sender, date, subject; what it cites).
  A model-written summary comes later (Gemini) on top of this.
- Validity: the order itself and every order it cites are checked as of `as_of` with the shared
  citation review (A / E / F over visible facts, status-coverage rule).
- Put in a file: a file is offered as THE file only when its subject is the receipt's subject
  once years and numbers are removed. Otherwise a new file is suggested, and files whose notes
  cite the order or its references are listed as related — never as the place to put it.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from app.auth.models import AccessPolicy, DocumentAccessTags
from app.auth.policy import ScopeError, check, scope_for
from app.auth.store import AuthzStore
from app.config import Classification
from app.conflict.citations import review_citations
from app.conflict.deterministic import Citation, ConflictFlag
from app.connectors.eoffice import ReceiptContext
from app.graph.repository import EdgeKind, InMemoryGraphRepository
from app.identifiers.canonical import InvalidCanonicalIdError, lookup_keys, parse_canonical_id
from app.identifiers.resolver import DepartmentTable
from app.ingestion.metadata import extract_metadata
from app.retrieval.references import LookupStatus, lookup_reference
from app.retrieval.scoped import IndexedDocument, ScopedRetriever
from app.temporal.engine import Instrument, TemporalRelation
from app.updates.reconcile import norm_subject


@dataclass(frozen=True)
class ReceiptReview:
    document: IndexedDocument | None
    summary: tuple[str, ...]
    cited: tuple[str, ...]  # canonical IDs the order cites that the officer may see
    flags: tuple[ConflictFlag, ...]
    flag_about: tuple[str, ...]  # "this order" | "cited order", parallel to flags
    status_unconfirmed: tuple[str, ...]
    put_in: tuple[str, ...]  # e-File numbers with the same subject
    related_files: tuple[str, ...]
    suggestion: str  # "existing_file" | "new_file" | "no_assistance"


def _base(cid: str) -> str | None:
    try:
        return parse_canonical_id(cid).base_id
    except InvalidCanonicalIdError:
        return None


def _fmt(d: dt.date | None) -> str:
    return d.strftime("%d-%m-%Y") if d else "undated"


def review_receipt(
    r: ReceiptContext,
    *,
    user_id: str,
    as_of: dt.date,
    departments: DepartmentTable,
    index: ScopedRetriever,
    documents: Callable[[], list[IndexedDocument]],
    graph: InMemoryGraphRepository,
    instruments: Mapping[str, Instrument],
    relations: list[TemporalRelation],
    text_of: Callable[[str], str],
    store: AuthzStore,
    policy: AccessPolicy,
    classification: Classification,
) -> ReceiptReview:
    none = ReceiptReview(None, (), (), (), (), (), (), (), "no_assistance")
    try:
        scope = scope_for(user_id, store, policy, classification)
    except ScopeError:
        return none
    # The diarised letter date completes a reference printed without its year ("G.O.Rt.No.1184").
    letter = r.letter_ref
    if letter and r.letter_date and not re.search(r"(?:19|20)\d{2}", letter):
        letter = f"{letter}, Dt.{r.letter_date:%d-%m-%Y}"
    look = (
        lookup_reference(
            user_id,
            letter,
            departments=departments,
            retriever=index,
            store=store,
            policy=policy,
            classification=classification,
        )
        if letter
        else None
    )
    if look is None or look.status is not LookupStatus.FOUND or look.canonical_id is None:
        return none
    cid = look.canonical_id
    docs = documents()
    by_id = {d.canonical_id: d for d in docs}
    doc = by_id.get(cid)
    if doc is None:
        return none

    def visible(c: str) -> bool:
        d = by_id.get(c)
        return d is not None and check(user_id, d.tags, store, policy, classification).allowed

    tags_of: dict[str, DocumentAccessTags] = {d.canonical_id: d.tags for d in docs}
    meta = extract_metadata(text_of(cid), departments)
    cited: list[str] = []
    for ref in meta.references:
        if ref.canonical_id is None or ref.raw.startswith("file:"):
            continue
        try:
            hit = next((k for k in lookup_keys(ref.canonical_id) if visible(k)), None)
            if hit is None:  # printed without its date: the one visible dated record (ADR-0007)
                base = parse_canonical_id(ref.canonical_id).base_id
                same = [d for d in by_id if _base(d) == base and visible(d)]
                hit = same[0] if len(same) == 1 else None
        except InvalidCanonicalIdError:
            hit = None
        if hit and hit != cid:
            cited.append(hit)
    cited = list(dict.fromkeys(cited))

    review = review_citations(
        [Citation(raw=cid, canonical_id=cid), *(Citation(raw=c, canonical_id=c) for c in cited)],
        as_of,
        user_id=user_id,
        scope=scope,
        instruments=instruments,
        relations=relations,
        tags_of=tags_of,
        store=store,
        policy=policy,
        classification=classification,
    )
    # The shared wording speaks of "the proposal"; for a receipt the date is the as-of date.
    flags = tuple(
        f.model_copy(
            update={"explanation": f.explanation.replace("the proposal is dated", "as of")}
        )
        for f in review.flags
    )
    about = tuple("this order" if f.cited == cid else "cited order" for f in flags)

    cites_line = (
        "Cites: " + "; ".join(f"{c} ({_fmt(by_id[c].issue_date)})" for c in cited) + "."
        if cited
        else "Cites no other order in the records available to you."
    )
    summary = (
        f"{doc.doc_type} from {r.sender}, dated {_fmt(doc.issue_date)}: {doc.subject}",
        cites_line,
    )

    # Put in a file: same subject (years / numbers removed) → that file; else related files.
    key = norm_subject(r.subject)
    notes = [
        d
        for d in docs
        if d.doc_type.startswith("Noting") and d.tags.file_no and visible(d.canonical_id)
    ]
    same = sorted(
        {d.tags.file_no for d in notes if d.tags.file_no and norm_subject(d.subject) == key}
    )
    targets = {cid, *cited}
    related: list[str] = []
    for t in targets:
        for e in graph.edges_to(t):
            if e.kind not in (EdgeKind.CITES, EdgeKind.REFERENCES):
                continue
            src = by_id.get(e.source)
            if (
                src
                and src.doc_type.startswith("Noting")
                and src.tags.file_no
                and visible(src.canonical_id)
            ):
                related.append(src.tags.file_no)
    related_files = tuple(f for f in dict.fromkeys(sorted(related)) if f not in same)
    return ReceiptReview(
        document=doc,
        summary=summary,
        cited=tuple(cited),
        flags=flags,
        flag_about=about,
        status_unconfirmed=tuple(review.unconfirmed),
        put_in=tuple(same),
        related_files=related_files,
        suggestion="existing_file" if same else "new_file",
    )
