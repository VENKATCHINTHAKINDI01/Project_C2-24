"""First cited answer: question → scoped ladder → evidence package → model → citation check
(plan §3.3, §8.1-§8.3; CLAUDE.md §4, §7; milestone M4).

The model sees only the evidence package: passages of records this officer may see, re-checked
when the package is built. What it writes is not shown as is: every statement must cite package
passages and quote them, and the verifier decides — confirmed, review needed, or removed. The
permission filter is never the model's job, and neither is the final say on a citation.

If the model is not configured or fails, the officer still gets the records found (they were
authorised without it) and a plain message that no answer was written.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from app.agents.entity_facts import MAX_RECORDS, EntityMatch, NamedRecord
from app.agents.entity_facts import resolve as resolve_entities
from app.agents.graph_facts import (
    CROSS_Q,
    HISTORY_Q,
    FileCitation,
    IndirectLink,
    LinkedRecord,
    cross_department_links,
    file_cited_orders,
    order_history,
)
from app.agents.intents import IntentSlots
from app.agents.llm import LLMClient, LLMError, load_prompt, stream_json
from app.agents.streaming import Emit, StatementStream
from app.agents.tools import (
    STATUS_UNCONFIRMED,
    ToolContext,
    check_document_status,
    search_authorized_documents,
    visible_document,
    visible_facts,
)
from app.auth.policy import ScopeError, scope_for
from app.citation.confidence import Cited, Confidence, assess, overall
from app.citation.verifier import NO_ANSWER, AnswerStatus, Claim, Verification, verify
from app.conflict.judgment import _spans, _terms
from app.graph.repository import Direction, EdgeKind
from app.identifiers.display import reference_text
from app.identifiers.resolver import DepartmentTable, reference_candidates
from app.ingestion.clauses import clause_text, paragraph_label
from app.precedent.counts import count_ask, count_decisions, sentence
from app.retrieval.evidence import (
    CandidateSpan,
    EvidenceError,
    EvidencePackage,
    TextQuality,
    build_package,
    render_for_prompt,
)
from app.retrieval.graph_expansion import expand

PROMPT_ID = "answer_cited.v2"
# the same rules plus one for passages whose status is "not established" (owner, 25 Nov 2026: what
# a record says is answered, attributed to it; whether it is in force is never claimed). Used only
# when the package holds such a passage, so every other answer keeps its recorded replay.
PROMPT_ID_UNKNOWN_STATUS = "answer_cited.v4"
UNKNOWN_STATUS = "not established"
MAX_DOCS = 8  # records sent to the model
SPANS_PER_DOC = 2
SPAN_CHARS = 700
MAX_STATEMENTS = 5
ENGINE_OFF = "No answer was written: the answer engine is not configured. Records found are listed."
INSTRUCTIONS_NOTICE = (
    "Some text in {ids} is addressed to an AI system rather than to officers. It was treated as "
    "data and nothing was stated on its authority; please read that record yourself."
)
# plan §14.4: a store that failed is said, never hidden (shown with the answer, not instead of it)
DEGRADED = {
    "L2": "Search by meaning was unavailable just now: these records come from exact references, "
    "filters and relations only.",
    "L3": "Supersession status unverified: the relations store was unavailable just now, so later "
    "orders that may replace or amend these records were not looked up.",
    # ADR-0063 addendum: the bounded walk stopped at its limit (counted over the officer's own
    # records only, so this says nothing about records they cannot see)
    "L3-limit": "Not every related order was looked up: the relations lookup reached its limit, so "
    "later orders that replace or amend these records may not all be listed.",
}
UNCHECKED = (
    "The answer could not be checked against its sources just now, so it is withheld. "
    "Records found are listed."
)
ENGINE_DOWN = "No answer was written: the answer engine is unavailable. Records found are listed."

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "statements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    "quote": {"type": "string"},
                },
                "required": ["text", "evidence_ids", "quote"],
            },
        }
    },
    "required": ["statements"],
}

log = logging.getLogger(__name__)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


@dataclasses.dataclass
class AskTrace:
    """What the orchestrator records in `AgentState` (plan §3.4): the package and the check."""

    package: EvidencePackage | None = None
    verification: Verification | None = None
    seeds: tuple[str, ...] = ()


class AskStatus(StrEnum):
    ANSWERED = "answered"
    REVIEW_NEEDED = "review_needed"
    NO_ANSWER = "no_answer"
    NOT_RUN = "not_run"  # records found, but no model answer (engine off or failed)


class Citation(_Frozen):
    evidence_id: str
    canonical_id: str
    doc_type: str
    status: str
    page: int | None = None
    issue_date: dt.date | None = None
    # the order as an officer writes it in a note, e.g. "G.O.Ms.No.31, Finance Department, dated
    # 12-05-2025, para 2(v)" (ADR-0034); filled from the ID and the record's own date
    reference: str = ""

    @model_validator(mode="after")
    def _fill_reference(self) -> Citation:
        if not self.reference:
            object.__setattr__(
                self, "reference", reference_text(self.canonical_id, self.issue_date)
            )
        return self


class Statement(_Frozen):
    text: str
    quote: str | None
    citations: tuple[Citation, ...]
    # "evidence": written by the model and confirmed by the citation check;
    # "order records": stated by the temporal engine from the order records (no model involved)
    source: str = "evidence"
    confidence: Confidence | None = None  # ADR-0054: from the facts, never the model's own


class Answer(_Frozen):
    request_id: str
    status: AskStatus
    statements: tuple[Statement, ...] = ()  # confirmed against the cited text
    review_needed: tuple[Statement, ...] = ()  # shown only under a "Review needed" label
    removed: int = 0  # statements the citation check rejected (count only)
    message: str | None = None
    documents: tuple[str, ...] = ()  # records in the evidence package (all authorised)
    ladder_level: str | None = None
    engine: str | None = None
    notices: tuple[str, ...] = ()  # e.g. a record that carries instructions aimed at an AI
    as_of: dt.date
    confidence: Confidence | None = None  # the weakest statement's (ADR-0054)


_MARKER = re.compile(r"\b\d+(?:\.\d+)*(?:\([a-z0-9]+\))+|\b\d{2,}(?:[./-]\d+)*\b", re.I)


def _passages(text: str, question: str, named: bool = False) -> list[str]:
    """The windows of `text` that share most words and word pairs with the question. A paragraph
    marker or number the question names ("2(v)", "88/2022", "1.30") found verbatim counts
    three times. A record the question names gets one more window, and its opening window when
    nothing else matches (it says what the record is)."""
    want = _terms(question)
    marks = {m.group(0).lower() for m in _MARKER.finditer(question)}
    scored = []
    spans = _spans(text, SPAN_CHARS)
    # the paragraph the question names ("para 2(v)") of a record it names comes first: its words
    # are in the order as "2." … "(v) …", never as the verbatim "2(v)" a note quoting it uses
    # (golden Q18, ADR-0050 addendum 3)
    clause = None
    if named and (loc := paragraph_label(question)) and (body := clause_text(text, loc)):
        clause = " ".join(body.split())[:60].lower()
    for a, b in spans:
        piece = text[a:b].strip()
        low = piece.lower()
        hit = len(_terms(piece) & want) + 3 * sum(m in low for m in marks)
        if clause and clause in " ".join(low.split()):
            hit += 1000
        if piece and hit:
            scored.append((-hit, a, piece))
    if named and not scored and spans:
        a, b = spans[0]
        scored.append((0, a, text[a:b].strip()))
    limit = SPANS_PER_DOC + (1 if named else 0)
    out: list[str] = []
    taken: list[tuple[int, int]] = []
    for _, a, piece in sorted(scored):
        if any(a < e and s < a + len(piece) for s, e in taken):
            continue  # overlaps a better window of the same record
        out.append(piece)
        taken.append((a, a + len(piece)))
        if len(out) == limit:
            break
    return out


_FILE_NO = re.compile(r"\b[A-Z]{2,6}\d{2}-[A-Z0-9]+/\d+/\d{4}-[A-Z0-9.]+")
_AS_OF = re.compile(r"\bas (?:on|of|at)\s+(\d{1,2})[-./](\d{1,2})[-./](\d{4})\b", re.I)
SEED_KINDS = frozenset({EdgeKind.CITES, EdgeKind.REFERENCES, EdgeKind.SUPERSEDES, EdgeKind.AMENDS})


def asked_as_of(question: str) -> dt.date | None:
    """An explicit "as on DD-MM-YYYY" in the question (plan §6.2 as-of questions)."""
    m = _AS_OF.search(question)
    if not m:
        return None
    try:
        return dt.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def named_orders(ctx: ToolContext, question: str, departments: DepartmentTable | None) -> list[str]:
    """Orders the question cites, looked up exactly (L0) within the officer's scope. An L0 lookup
    by the base ID also finds a dated version ("…-9-2023" → "…-9-2023-D20230711")."""
    if departments is None:
        return []
    try:
        scope = scope_for(ctx.user_id, ctx.store, ctx.policy, ctx.classification)
    except ScopeError:
        return []  # fail closed: no scope, nothing named
    out: list[str] = []
    for cid in reference_candidates(question, departments):
        for d in ctx.index.exact(cid, scope):
            if visible_document(ctx, d.canonical_id) is not None:  # re-check per record
                out.append(d.canonical_id)
    return list(dict.fromkeys(out))


def seeds_for(
    ctx: ToolContext,
    question: str,
    departments: DepartmentTable | None,
    file_papers: Callable[[str], Sequence[str]] | None,
    recalled: Sequence[str] = (),
    down: set[str] | None = None,
) -> list[str]:
    """Records the question names, found deterministically before any search (plan §3.2 L0):
    what an earlier turn of the conversation found (`recalled`, re-checked), order references
    it cites (every department reading of an unnamed one), papers of an e-File
    it names, and what those papers cite or what replaced it (L3). Each is looked up within the
    officer's scope; nothing outside it is ever returned."""
    named = named_orders(ctx, question, departments)
    named += [c for c in recalled if visible_document(ctx, c) is not None]  # re-checked again
    if file_papers is not None:
        for file_no in dict.fromkeys(_FILE_NO.findall(question)):
            named += [c for c in file_papers(file_no) if visible_document(ctx, c) is not None]
    # people and offices the question names (ADR-0058): the records naming them, re-checked
    named += [r.canonical_id for m in resolve_entities(ctx, question) for r in m.records]
    if named:
        try:
            exp = expand(
                ctx.user_id,
                named,
                graph=ctx.graph,
                kinds=SEED_KINDS,
                direction=Direction.BOTH,
                max_hops=2,
                store=ctx.store,
                policy=ctx.policy,
                classification=ctx.classification,
            )
        except Exception as exc:  # noqa: BLE001 — plan §14.4: answer without the walk, say so
            log.error("L3 unavailable for named records: %s", type(exc).__name__)
            if down is not None:
                down.add("L3")
        else:
            if exp.unavailable and down is not None:
                down.add("L3")
            named += [h.canonical_id for h in exp.hits]
    return list(dict.fromkeys(named))


def evidence_for(
    ctx: ToolContext,
    question: str,
    texts: Mapping[str, str],
    request_id: str,
    seeds: Sequence[str] = (),
    down: set[str] | None = None,
) -> tuple[EvidencePackage, str | None]:
    """Named records first (L0 / L3), then the scoped plain-language search (L2) → passages →
    re-checked evidence package."""
    found = search_authorized_documents(ctx, IntentSlots(text=question[:500]))
    if down is not None:
        down.update(found.unavailable)
        if found.truncated:
            down.add("L3-limit")
    order = list(dict.fromkeys([*seeds, *(r.canonical_id for r in found.documents)]))
    level = "L0" if seeds else found.ladder_level
    cands: list[CandidateSpan] = []
    used = 0
    for cid in order:
        if used == MAX_DOCS:
            break
        doc = visible_document(ctx, cid)  # authorisation re-read; gives the tags
        if doc is None:
            continue
        text = texts.get(cid, "")  # read only for a record this officer may see
        if not text:
            continue
        used += 1
        st = check_document_status(ctx, cid)
        inst = ctx.instruments.get(cid)
        for piece in _passages(text, question, named=cid in seeds):
            cands.append(
                CandidateSpan(
                    canonical_id=doc.canonical_id,
                    span_text=piece,
                    source_uri=doc.tags.doc_id,
                    doc_type=doc.doc_type,
                    hierarchy_level=inst.hierarchy_level if inst else 0,
                    status=(st.status if st.available and st.status else "not established"),
                    effective_from=inst.effective_from if inst else None,
                    effective_to=inst.valid_until if inst else None,
                    issue_date=doc.issue_date,  # the record's own date (verifier: own numbers)
                    ladder_level=(level if cid in seeds else found.ladder_level) or "L2",
                    tags=doc.tags,
                )
            )
    pkg = build_package(
        request_id,
        ctx.user_id,
        ctx.as_of,
        cands,
        store=ctx.store,
        policy=ctx.policy,
        classification=ctx.classification,
    )
    return pkg, level


def _aliased(pkg: EvidencePackage) -> tuple[EvidencePackage, dict[str, str]]:
    """The prompt names passages EV-1, EV-2 … instead of their request-bound IDs, so the same
    evidence gives the same prompt (saved answers replay; ADR-0024 addendum). Map back after."""
    alias = {i.evidence_id: f"EV-{n}" for n, i in enumerate(pkg.items, 1)}
    items = tuple(i.model_copy(update={"evidence_id": alias[i.evidence_id]}) for i in pkg.items)
    return pkg.model_copy(update={"items": items}), {v: k for k, v in alias.items()}


def _statement(claim: Claim, pkg: EvidencePackage) -> Statement:
    cites = []
    for eid in claim.evidence_ids:
        item = pkg.get(eid)
        if item is not None:
            cites.append(
                Citation(
                    evidence_id=eid,
                    canonical_id=item.canonical_id,
                    doc_type=item.doc_type,
                    status=item.status,
                    page=item.page,
                    issue_date=item.issue_date,
                )
            )
    return Statement(text=claim.text, quote=claim.quote, citations=tuple(cites))


_STATUS_Q = re.compile(
    r"\b(valid|in force|current(?:ly)?|still|superseded|repealed|rescinded|status|applicable)\b",
    re.I,
)


# words that state whether an order holds (ADR-0050 addendum 2). While a named order's status may
# not be reported to this officer, no model statement using them is shown: the model must not say
# what the order records were not allowed to say ("not withdrawn", "remains in force", …)
_STATUS_CLAIM = re.compile(
    r"\b(valid|invalid|validity|in force|force|withdrawn|withdrawal|superseded|supersedes|"
    r"replaced|repealed|rescinded|cancell?ed|revoked|lapsed|expired|still|current(?:ly)?|active|"
    r"operative|inoperative|remains?|applicable|applies|amended|status)\b",
    re.I,
)


def status_claim(text: str) -> bool:
    return bool(_STATUS_CLAIM.search(text))


def status_statements(
    ctx: ToolContext,
    question: str,
    departments: DepartmentTable | None,
    pkg: EvidencePackage,
    recalled: Sequence[str] = (),
    unconfirmed: list[str] | None = None,
) -> tuple[Statement, ...]:
    """For a question about whether a NAMED order still holds: the status the temporal engine
    finds in the order records on the as-of date (plan §6.1-§6.2: status is a fact, never a model
    guess). Only for orders this officer may see, and only when the status may be reported to
    them (the coverage rule of `check_document_status`). A named order whose status may NOT be
    reported to them is added to `unconfirmed` (its officer-facing reference), so the answer says
    so in the neutral words of that rule instead of saying nothing."""
    if not _STATUS_Q.search(question):
        return ()
    first_item = {i.canonical_id: i.evidence_id for i in reversed(pkg.items)}
    out = []
    named = named_orders(ctx, question, departments) or [
        c
        for c in recalled
        if visible_document(ctx, c) is not None  # "is THAT order valid?"
    ]
    for cid in named:
        st = check_document_status(ctx, cid)
        if unconfirmed is not None and st.available and st.status_unconfirmed:
            d = st.status_unconfirmed[0]
            unconfirmed.append(reference_text(d.canonical_id, d.issue_date))
        if not (st.available and st.status and st.documents):
            continue
        ref = st.documents[0]
        text = f"On {ctx.as_of:%d-%m-%Y} the order records show {cid} as {st.status}"
        cites = [
            Citation(
                evidence_id=first_item.get(cid, ""),
                canonical_id=cid,
                doc_type=ref.doc_type,
                status=st.status,
                issue_date=ref.issue_date,
            )
        ]
        if st.by:
            since = f" from {st.since:%d-%m-%Y}" if st.since else ""
            text += f", by {st.by}{since}"
            cites.append(
                Citation(
                    evidence_id=first_item.get(st.by, ""),
                    canonical_id=st.by,
                    doc_type="",
                    status="",
                    issue_date=by_doc.issue_date
                    if (by_doc := visible_document(ctx, st.by)) is not None
                    else None,
                )
            )
        out.append(
            Statement(text=text + ".", quote=None, citations=tuple(cites), source="order records")
        )
    return tuple(out)


def count_statements(
    ctx: ToolContext, question: str, texts: Mapping[str, str]
) -> tuple[Statement, ...]:
    """For "how many … were rejected in 2025?": the count of decided note files of that kind the
    officer may see (ADR-0051), stated from the file records — no model involved. Counted only
    over the authorised records; nothing hints at a record outside them."""
    want = count_ask(question)
    if want is None:
        return ()
    try:
        scope = scope_for(ctx.user_id, ctx.store, ctx.policy, ctx.classification)
    except ScopeError:
        return ()  # fail closed: no scope, no count
    r = count_decisions(
        want, scope, ctx.index, texts, lambda cid: visible_document(ctx, cid) is not None
    )
    cites = tuple(
        Citation(
            evidence_id="",
            canonical_id=d.canonical_id,
            doc_type="Noting",
            status=d.outcome.value,
            issue_date=d.issue_date,
        )
        for d in (r.counted or r.decided)
    )
    return (Statement(text=sentence(r), quote=None, citations=cites, source="file records"),)


MAX_HISTORY_EVENTS = 10  # the most recent changes of a lineage; older ones are summarised
MAX_LINEAGES = 2  # lineages / link sets described for one question
MAX_FILE_LINEAGES = 4  # lineages of the orders one e-File cites
_KIND_VERB = {
    EdgeKind.CITES: "cites",
    EdgeKind.REFERENCES: "refers to",
    EdgeKind.AMENDS: "amends",
    EdgeKind.CLARIFIES: "clarifies",
    EdgeKind.SUPERSEDES: "supersedes",
    EdgeKind.REPEALS: "withdraws",
}


def _subjects(
    ctx: ToolContext,
    question: str,
    departments: DepartmentTable | None,
    pkg: EvidencePackage,
    recalled: Sequence[str],
    *,
    orders_only: bool,
) -> tuple[list[str], bool]:
    """What a graph question is about: the orders it names (or the one an earlier turn found),
    else the records the search found, best first. The flag says whether they were named."""
    named = named_orders(ctx, question, departments) or [
        c for c in recalled if visible_document(ctx, c) is not None
    ]
    if named:
        return named, True
    if departments is not None and reference_candidates(question, departments):
        # the question names an order this officer cannot see (or that does not exist): the
        # answer is about THAT order, so no other record is described in its place (and nothing
        # tells the two cases apart)
        return [], True
    found = [i.canonical_id for i in pkg.items]
    if orders_only:
        found = [c for c in found if c in ctx.instruments]
    return list(dict.fromkeys(found)), False


def _cite(ctx: ToolContext, cid: str, first_item: Mapping[str, str], status: str = "") -> Citation:
    """A citation of a record this officer may see (re-checked), with its own type and date."""
    doc = visible_document(ctx, cid)
    return Citation(
        evidence_id=first_item.get(cid, ""),
        canonical_id=cid,
        doc_type=doc.doc_type if doc else "",
        status=status,
        issue_date=doc.issue_date if doc else None,
    )


def history_statements(
    ctx: ToolContext,
    question: str,
    departments: DepartmentTable | None,
    pkg: EvidencePackage,
    recalled: Sequence[str] = (),
    unconfirmed: list[str] | None = None,
    file_papers: Callable[[str], Sequence[str]] | None = None,
    down: set[str] | None = None,
) -> tuple[Statement, ...]:
    """For "how has this order changed over time?": the order's lineage — every amendment,
    clarification, replacement and withdrawal joined to it by a confirmed link — as dated events
    from the order records, then what is in force on the as-of date (ADR-0056; plan §6.1). Built
    only from the facts this officer may see. When the officer's scope does not cover the order's
    status, nothing is said about what is in force (the coverage rule of `check_document_status`)
    and the answer carries the neutral notice instead."""
    if not HISTORY_Q.search(question):
        return ()
    first_item = {i.canonical_id: i.evidence_id for i in reversed(pkg.items)}
    out: list[Statement] = []
    cited: list[FileCitation] = []
    files = list(dict.fromkeys(_FILE_NO.findall(question))) if file_papers is not None else []
    if files and file_papers is not None:
        # "how have the orders this file relies on changed?": the orders its papers cite, each
        # told with what changed after the paper cited it (ADR-0056, history across files)
        for file_no in files:
            papers = [c for c in file_papers(file_no) if visible_document(ctx, c) is not None]
            got = file_cited_orders(ctx, papers)
            if got is None:
                if down is not None:
                    down.add("L3")
                continue
            cited += got
        subjects, named = list(dict.fromkeys(f.order for f in cited)), True
        limit = MAX_FILE_LINEAGES
    else:
        subjects, named = _subjects(ctx, question, departments, pkg, recalled, orders_only=True)
        limit = MAX_LINEAGES
    done: set[str] = set()
    told = 0
    for cid in subjects:
        if told == limit or cid in done:
            continue
        oh = order_history(ctx, cid)
        if oh is None:
            continue
        h = oh.history
        members = h.members
        done.update(h.lineage)
        if len(members) < 2 and not named:
            continue  # a found record with no recorded changes says nothing about the question
        doc = visible_document(ctx, cid)
        if doc is None:
            continue
        ref = reference_text(cid, doc.issue_date)
        if not oh.covered and unconfirmed is not None:
            unconfirmed.append(ref)
        if len(members) < 2:
            if oh.covered:
                out.append(
                    Statement(
                        text=f"Up to {h.as_of:%d-%m-%Y} the order records show no amendment, "
                        f"clarification or replacement of {ref}.",
                        quote=None,
                        citations=(_cite(ctx, cid, first_item),),
                        source="order records",
                    )
                )
                told += 1
            continue
        told += 1
        told_papers: set[tuple[str, str]] = set()
        for f in (f for f in cited if f.order in h.lineage):
            paper = visible_document(ctx, f.paper)
            if paper is not None and paper.tags.file_no:
                # "Noting (draft proposal) in File No.X": a paper of the file, by its kind
                pref = f"The {paper.doc_type.lower()} in File No.{paper.tags.file_no}"
            else:
                pref = reference_text(f.paper, f.paper_date)
            if (pref, f.order) in told_papers:
                continue  # two papers of the same kind and file citing the same order: once
            told_papers.add((pref, f.order))
            oref = reference_text(
                f.order, d.issue_date if (d := visible_document(ctx, f.order)) else None
            )
            later = [e for e in h.events if f.paper_date is not None and e.on > f.paper_date]
            when = f", written on {f.paper_date:%d-%m-%Y}," if f.paper_date else ""
            text = f"{pref}{when} cites {oref}."
            if later:
                text += f" {len(later)} change(s) to these orders took effect after it was written."
            elif f.paper_date is not None:
                text += " The order records show no change to these orders after it was written."
            if paper is not None:
                out.append(
                    Statement(
                        text=text,
                        quote=None,
                        citations=(
                            _cite(ctx, f.paper, first_item),
                            _cite(ctx, f.order, first_item),
                        ),
                        source="order records",
                    )
                )
        events = h.events[-MAX_HISTORY_EVENTS:]
        if len(h.events) > len(events) or h.cut:
            out.append(
                Statement(
                    text=f"{ref} belongs to a longer series of orders; the "
                    f"{len(events)} most recent changes up to {h.as_of:%d-%m-%Y} follow.",
                    quote=None,
                    citations=(_cite(ctx, cid, first_item),),
                    source="order records",
                )
            )
        for e in events:
            by = visible_document(ctx, e.canonical_id)
            who = reference_text(e.canonical_id, by.issue_date if by else None)
            if e.targets:
                what = " and ".join(
                    reference_text(t, d.issue_date if (d := visible_document(ctx, t)) else None)
                    for t in e.targets
                )
                text = f"{e.on:%d-%m-%Y}: {who} {e.change.value} {what}."
            else:
                text = f"{e.on:%d-%m-%Y}: {who} took effect."
            out.append(
                Statement(
                    text=text,
                    quote=None,
                    citations=tuple(
                        _cite(ctx, c, first_item) for c in (e.canonical_id, *e.targets)
                    ),
                    source="order records",
                )
            )
        if oh.covered:
            if h.in_force:
                names = ", ".join(
                    reference_text(c, d.issue_date if (d := visible_document(ctx, c)) else None)
                    for c in h.in_force
                )
                text = f"In force on {h.as_of:%d-%m-%Y}: {names}."
            else:
                text = f"None of these orders is in force on {h.as_of:%d-%m-%Y}."
            out.append(
                Statement(
                    text=text,
                    quote=None,
                    citations=tuple(_cite(ctx, c, first_item, "in_force") for c in h.in_force)
                    or (_cite(ctx, cid, first_item),),
                    source="order records",
                )
            )
        if h.pending_review:
            out.append(
                Statement(
                    text=f"{len(h.pending_review)} further link(s) between these orders await "
                    "officer review and are not part of this account.",
                    quote=None,
                    citations=(_cite(ctx, cid, first_item),),
                    source="order records",
                )
            )
    return tuple(out)


def cross_department_statements(
    ctx: ToolContext,
    question: str,
    departments: DepartmentTable | None,
    pkg: EvidencePackage,
    recalled: Sequence[str] = (),
    down: set[str] | None = None,
) -> tuple[Statement, ...]:
    """For "which other departments refer to this circular?": records of other departments one
    link away from the record asked about, in either direction, grouped by department (ADR-0056;
    plan §12.3). Only the scope-constrained graph walk is used; every record is re-checked; a
    record outside the scope is never named, counted or hinted at."""
    if not CROSS_Q.search(question):
        return ()
    first_item = {i.canonical_id: i.evidence_id for i in reversed(pkg.items)}
    subjects, named = _subjects(ctx, question, departments, pkg, recalled, orders_only=False)
    names = {d.code: d.name for d in departments.departments} if departments else {}
    out: list[Statement] = []
    for cid in subjects[: MAX_LINEAGES if named else 1]:
        cd = cross_department_links(ctx, cid)
        if cd is None:
            continue
        if cd.unavailable:
            if down is not None:
                down.add("L3")  # the answer says the links could not be checked
            continue
        doc = visible_document(ctx, cid)
        ref = reference_text(cid, doc.issue_date if doc else None)
        if names:
            # only departments of the department table count: a Gazette publication of the same
            # order ("GAZ") is not another department relying on it
            cd = cd.model_copy(
                update={
                    "links": tuple(r for r in cd.links if r.department in names),
                    "indirect": tuple(i for i in cd.indirect if i.end.department in names),
                }
            )
        if not cd.links and not cd.indirect:
            out.append(
                Statement(
                    text=f"The link records show no record of another department linked to {ref}.",
                    quote=None,
                    citations=(_cite(ctx, cid, first_item),),
                    source="link records",
                )
            )
            continue
        by_dept: dict[str, list[LinkedRecord]] = {}
        for r in cd.links:
            by_dept.setdefault(r.department, []).append(r)
        for dept, recs in by_dept.items():
            parts = []
            for r in recs:
                other = reference_text(r.canonical_id, r.issue_date)
                verb = _KIND_VERB.get(r.kind, "is linked to")
                parts.append(f"{ref} {verb} {other}" if r.outward else f"{other} {verb} {ref}")
            label = f"{names[dept]} ({dept})" if dept in names else dept
            out.append(
                Statement(
                    text=f"{label}: " + "; ".join(parts) + ".",
                    quote=None,
                    citations=(
                        _cite(ctx, cid, first_item),
                        *(_cite(ctx, r.canonical_id, first_item) for r in recs),
                    ),
                    source="link records",
                )
            )
        chains: dict[tuple[str, str], list[IndirectLink]] = {}
        for i in cd.indirect:  # two links away, through a record the officer may see
            chains.setdefault((i.end.department, i.via.canonical_id), []).append(i)
        for (dept, _), group in chains.items():
            via = group[0].via
            mid = reference_text(via.canonical_id, via.issue_date)
            v1 = _KIND_VERB.get(via.kind, "is linked to")
            step1 = f"{ref} {v1} {mid}" if via.outward else f"{mid} {v1} {ref}"
            steps = []
            for i in group:
                end = reference_text(i.end.canonical_id, i.end.issue_date)
                v2 = _KIND_VERB.get(i.end.kind, "is linked to")
                steps.append(f"{mid} {v2} {end}" if i.end.outward else f"{end} {v2} {mid}")
            label = f"{names[dept]} ({dept})" if dept in names else dept
            out.append(
                Statement(
                    text=f"{label}, through {mid}: {step1}; " + "; ".join(steps) + ".",
                    quote=None,
                    citations=tuple(
                        _cite(ctx, c, first_item)
                        for c in dict.fromkeys(
                            (cid, via.canonical_id, *(i.end.canonical_id for i in group))
                        )
                    ),
                    source="link records",
                )
            )
    return tuple(out)


def _record_label(r: NamedRecord) -> str:
    when = f" ({r.issue_date:%d-%m-%Y})" if r.issue_date else ""
    if r.file_no:
        return f"{r.doc_type} in File No.{r.file_no}{when}"
    return reference_text(r.canonical_id, r.issue_date)


def entity_statements(
    ctx: ToolContext, question: str, pkg: EvidencePackage
) -> tuple[Statement, ...]:
    """For a question that names a person or an office: the records naming them, from the entity
    index, every record re-checked (ADR-0058). Said only through records this officer may see; a
    name found nowhere visible gives nothing, exactly like a name found nowhere at all."""
    first_item = {i.canonical_id: i.evidence_id for i in reversed(pkg.items)}
    out: list[Statement] = []
    for m in resolve_entities(ctx, question):
        out.append(_entity_statement(ctx, m, first_item))
    return tuple(out)


def _entity_statement(ctx: ToolContext, m: EntityMatch, first_item: Mapping[str, str]) -> Statement:
    recs = m.records[-MAX_RECORDS:]
    who = [m.roles[0]] if m.roles else []
    if m.officer_id:
        who.append(f"officer ID {m.officer_id}")  # two officers of the same name: told apart
    role = f" ({', '.join(who)})" if who else ""
    lead = f"{len(m.records)} record(s) name {m.shown_as}{role}"
    if m.partial:
        lead += f' (matched on the name "{m.asked}"; the question gave no initials)'
    if len(m.records) > len(recs):
        lead += f"; the {len(recs)} most recent"
    parts = [_record_label(r) + (", signed by them" if r.signed else "") for r in recs]
    return Statement(
        text=f"{lead}: " + "; ".join(parts) + ".",
        quote=None,
        citations=tuple(_cite(ctx, r.canonical_id, first_item) for r in recs),
        source="entity records",
    )


def ask(
    ctx: ToolContext,
    question: str,
    *,
    texts: Mapping[str, str],
    llm: LLMClient | None,
    request_id: str,
    departments: DepartmentTable | None = None,
    file_papers: Callable[[str], Sequence[str]] | None = None,
    recalled: Sequence[str] = (),
    trace: AskTrace | None = None,
    on_event: Emit | None = None,
) -> Answer:
    emit: Emit = on_event or (lambda _e: None)
    down: set[str] = set()  # stores that failed during this question (plan §14.4)
    unconfirmed: list[str] = []  # named orders whose status may not be reported to this officer

    def rated(st: Statement, pkg: EvidencePackage | None, verified: bool) -> Statement:
        """The statement with its confidence (ADR-0054), from facts the system holds."""
        cfg = ctx.confidence
        if cfg is None:
            return st
        items = {i.evidence_id: i for i in pkg.items} if pkg else {}
        cited = [
            Cited(
                canonical_id=c.canonical_id,
                rung=(it.ladder_level if (it := items.get(c.evidence_id)) else None),
                hierarchy_level=it.hierarchy_level
                if it
                else (ctx.instruments[c.canonical_id].hierarchy_level
                      if c.canonical_id in ctx.instruments else None),
                ocr=bool(it and it.text_quality is TextQuality.OCR),
                incomplete=bool(it and it.incomplete),
            )
            for c in st.citations
        ]  # fmt: skip
        inst, rels = visible_facts(ctx, {c.canonical_id for c in cited})
        conf = assess(
            st.text,
            cited,
            verified=verified,
            from_records=st.source != "evidence",
            as_of=ctx.as_of,
            instruments=inst,
            relations=rels,
            may_see=lambda cid: visible_document(ctx, cid) is not None,
            graph_down="L3" in down,
            cfg=cfg,
        )
        return st.model_copy(update={"confidence": conf})

    def out(status: AskStatus, pkg: EvidencePackage | None = None, **kw: Any) -> Answer:
        shown = tuple(rated(s, pkg, True) for s in kw.pop("statements", ()))
        review = tuple(rated(s, pkg, False) for s in kw.pop("review_needed", ()))
        kw |= {"statements": shown, "review_needed": review}
        kw.setdefault("confidence", overall([s.confidence for s in shown if s.confidence]))
        docs = tuple(sorted(pkg.canonical_ids)) if pkg else ()
        odd = sorted({i.canonical_id for i in pkg.items if i.addressed_to_ai}) if pkg else []
        notices: tuple[str, ...] = (INSTRUCTIONS_NOTICE.format(ids=", ".join(odd)),) if odd else ()
        notices += tuple(DEGRADED[r] for r in sorted(down) if r in DEGRADED)
        notices += tuple(f"{ref}: {STATUS_UNCONFIRMED}" for ref in dict.fromkeys(unconfirmed))
        return Answer(
            request_id=request_id,
            status=status,
            documents=docs,
            as_of=ctx.as_of,
            notices=notices,
            **kw,
        )

    if (day := asked_as_of(question)) is not None:
        ctx = dataclasses.replace(ctx, as_of=day)  # statuses are then computed for that date
    counts = count_statements(ctx, question, texts)  # no model involved
    try:
        seeds = seeds_for(ctx, question, departments, file_papers, recalled, down)
        pkg, level = evidence_for(ctx, question, texts, request_id, seeds, down)
        if trace is not None:
            trace.package, trace.seeds = pkg, tuple(seeds)
    except EvidenceError:
        if counts:
            return out(AskStatus.ANSWERED, statements=counts)
        return out(AskStatus.NO_ANSWER, message=NO_ANSWER)
    if not pkg.items:  # the model is not asked
        if counts:
            return out(AskStatus.ANSWERED, statements=counts)
        return out(AskStatus.NO_ANSWER, message=NO_ANSWER)
    emit({"type": "stage", "stage": "found", "records": len(pkg.canonical_ids), "rung": level})
    facts = status_statements(ctx, question, departments, pkg, recalled, unconfirmed)  # no model
    facts += history_statements(
        ctx, question, departments, pkg, recalled, unconfirmed, file_papers, down
    )
    facts += cross_department_statements(ctx, question, departments, pkg, recalled, down)
    facts += entity_statements(ctx, question, pkg)
    facts += counts
    for f in facts:
        emit({"type": "statement", "statement": f.model_dump(mode="json")})

    def engine_missing(message: str) -> Answer:
        # the records still answer a status question; nothing else is written
        status = AskStatus.ANSWERED if facts else AskStatus.NOT_RUN
        return out(status, pkg, statements=facts, message=message, ladder_level=level)

    if llm is None:
        return engine_missing(ENGINE_OFF)
    shown, back = _aliased(pkg)
    user = (
        f"Question: {question}\nAsked as of: {ctx.as_of.isoformat()}\n\n{render_for_prompt(shown)}"
    )

    def claim_of(r: Any) -> Claim | None:
        if not (isinstance(r, dict) and str(r.get("text") or "").strip()):
            return None
        return Claim(
            text=str(r["text"]).strip(),
            evidence_ids=tuple(back.get(str(e), str(e)) for e in r.get("evidence_ids") or ()),
            quote=(str(r.get("quote") or "").strip() or None),
        )

    # Streaming (ADR-0033): each statement is shown as soon as its JSON object is complete AND
    # it passes the same citation check as below — never the model's unchecked words
    stream, seen, unchecked = StatementStream(), [0], [False]

    def on_text(chunk: str) -> None:
        for r in stream.feed(chunk):
            seen[0] += 1
            c = claim_of(r) if seen[0] <= MAX_STATEMENTS else None
            if c is None or (unconfirmed and status_claim(c.text)):
                continue
            if unchecked[0]:
                continue
            try:
                one = verify(
                    pkg, [c], store=ctx.store, policy=ctx.policy, classification=ctx.classification
                )
            except ScopeError:
                raise
            except Exception as exc:  # noqa: BLE001 — plan §14.4: withhold, never show unchecked
                log.error("citation check failed while streaming: %s", type(exc).__name__)
                unchecked[0] = True
                continue
            for kind, got in (("statement", one.confirmed), ("review", one.review_needed)):
                for x in got:
                    emit({"type": kind, "statement": _statement(x, pkg).model_dump(mode="json")})

    emit({"type": "stage", "stage": "writing"})
    try:
        unknown = any(i.status == UNKNOWN_STATUS for i in pkg.items)
        prompt_id = PROMPT_ID_UNKNOWN_STATUS if unknown else PROMPT_ID
        raw = stream_json(
            llm,
            prompt_id=prompt_id,
            system=load_prompt(prompt_id),
            user=user,
            schema=SCHEMA,
            on_text=on_text if on_event is not None else None,
        )
        rows = list(raw.get("statements") or [])[:MAX_STATEMENTS]
        claims = [c for r in rows if (c := claim_of(r)) is not None]
        # a status the officer may not be told is never told by the model either; such a
        # statement counts as removed (it is never verified, streamed or shown)
        withheld = sum(status_claim(c.text) for c in claims) if unconfirmed else 0
        claims = [c for c in claims if not (unconfirmed and status_claim(c.text))]
    except (LLMError, KeyError, TypeError, ValueError) as exc:
        log.warning("answer generation failed: %s (%s)", type(exc).__name__, exc)
        return engine_missing(ENGINE_DOWN)
    emit({"type": "stage", "stage": "checking"})
    # a statement with no quote can never be confirmed: it would be the model's word alone
    try:
        if unchecked[0]:
            raise RuntimeError("citation check failed while streaming")
        v = verify(
            pkg, claims, store=ctx.store, policy=ctx.policy, classification=ctx.classification
        )
    except ScopeError:
        raise
    except Exception as exc:  # noqa: BLE001 — plan §14.4: no unchecked claim is ever shown
        log.error("citation check failed: %s", type(exc).__name__)
        # the order-record facts were stated by the temporal engine, not the model: they stay
        status = AskStatus.ANSWERED if facts else AskStatus.NOT_RUN
        return out(status, pkg, statements=facts, message=UNCHECKED, ladder_level=level)
    if trace is not None:
        trace.verification = v
    status = {
        AnswerStatus.ANSWERED: AskStatus.ANSWERED,
        AnswerStatus.REVIEW_NEEDED: AskStatus.REVIEW_NEEDED,
        AnswerStatus.NO_ANSWER: AskStatus.NO_ANSWER,
    }[v.answer_status]
    used = getattr(llm, "last_used", None) or llm.name
    message = v.message
    if facts and status is not AskStatus.ANSWERED:
        status, message = AskStatus.ANSWERED, None  # the records answer it, model or not
    return out(
        status,
        pkg,
        statements=facts + tuple(_statement(c, pkg) for c in v.confirmed),
        review_needed=tuple(_statement(c, pkg) for c in v.review_needed),
        removed=withheld + len(claims) - len(v.confirmed) - len(v.review_needed),
        message=message,
        ladder_level=level,
        engine=used,
    )
