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
import re
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from app.agents.intents import IntentSlots
from app.agents.llm import LLMClient, LLMError, load_prompt, stream_json
from app.agents.streaming import Emit, StatementStream
from app.agents.tools import (
    ToolContext,
    check_document_status,
    search_authorized_documents,
    visible_document,
)
from app.auth.policy import ScopeError, scope_for
from app.citation.verifier import NO_ANSWER, AnswerStatus, Claim, Verification, verify
from app.conflict.judgment import _spans, _terms
from app.graph.repository import Direction, EdgeKind
from app.identifiers.display import reference_text
from app.identifiers.resolver import DepartmentTable, reference_candidates
from app.retrieval.evidence import (
    CandidateSpan,
    EvidenceError,
    EvidencePackage,
    build_package,
    render_for_prompt,
)
from app.retrieval.graph_expansion import expand

PROMPT_ID = "answer_cited.v2"
MAX_DOCS = 8  # records sent to the model
SPANS_PER_DOC = 2
SPAN_CHARS = 700
MAX_STATEMENTS = 5
ENGINE_OFF = "No answer was written: the answer engine is not configured. Records found are listed."
INSTRUCTIONS_NOTICE = (
    "Some text in {ids} is addressed to an AI system rather than to officers. It was treated as "
    "data and nothing was stated on its authority; please read that record yourself."
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
    for a, b in spans:
        piece = text[a:b].strip()
        low = piece.lower()
        hit = len(_terms(piece) & want) + 3 * sum(m in low for m in marks)
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
    if named:
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
        named += [h.canonical_id for h in exp.hits]
    return list(dict.fromkeys(named))


def evidence_for(
    ctx: ToolContext,
    question: str,
    texts: Mapping[str, str],
    request_id: str,
    seeds: Sequence[str] = (),
) -> tuple[EvidencePackage, str | None]:
    """Named records first (L0 / L3), then the scoped plain-language search (L2) → passages →
    re-checked evidence package."""
    found = search_authorized_documents(ctx, IntentSlots(text=question[:500]))
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


def status_statements(
    ctx: ToolContext,
    question: str,
    departments: DepartmentTable | None,
    pkg: EvidencePackage,
    recalled: Sequence[str] = (),
) -> tuple[Statement, ...]:
    """For a question about whether a NAMED order still holds: the status the temporal engine
    finds in the order records on the as-of date (plan §6.1-§6.2: status is a fact, never a model
    guess). Only for orders this officer may see, and only when the status may be reported to
    them (the coverage rule of `check_document_status`)."""
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

    def out(status: AskStatus, pkg: EvidencePackage | None = None, **kw: Any) -> Answer:
        docs = tuple(sorted(pkg.canonical_ids)) if pkg else ()
        odd = sorted({i.canonical_id for i in pkg.items if i.addressed_to_ai}) if pkg else []
        notices = (INSTRUCTIONS_NOTICE.format(ids=", ".join(odd)),) if odd else ()
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
    try:
        seeds = seeds_for(ctx, question, departments, file_papers, recalled)
        pkg, level = evidence_for(ctx, question, texts, request_id, seeds)
        if trace is not None:
            trace.package, trace.seeds = pkg, tuple(seeds)
    except EvidenceError:
        return out(AskStatus.NO_ANSWER, message=NO_ANSWER)
    if not pkg.items:
        return out(AskStatus.NO_ANSWER, message=NO_ANSWER)  # the model is not asked
    emit({"type": "stage", "stage": "found", "records": len(pkg.canonical_ids), "rung": level})
    facts = status_statements(ctx, question, departments, pkg, recalled)  # no model involved
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
    stream, seen = StatementStream(), [0]

    def on_text(chunk: str) -> None:
        for r in stream.feed(chunk):
            seen[0] += 1
            c = claim_of(r) if seen[0] <= MAX_STATEMENTS else None
            if c is None:
                continue
            one = verify(
                pkg, [c], store=ctx.store, policy=ctx.policy, classification=ctx.classification
            )
            for kind, got in (("statement", one.confirmed), ("review", one.review_needed)):
                for x in got:
                    emit({"type": kind, "statement": _statement(x, pkg).model_dump(mode="json")})

    emit({"type": "stage", "stage": "writing"})
    try:
        raw = stream_json(
            llm,
            prompt_id=PROMPT_ID,
            system=load_prompt(PROMPT_ID),
            user=user,
            schema=SCHEMA,
            on_text=on_text if on_event is not None else None,
        )
        rows = list(raw.get("statements") or [])[:MAX_STATEMENTS]
        claims = [c for r in rows if (c := claim_of(r)) is not None]
    except (LLMError, KeyError, TypeError, ValueError):
        return engine_missing(ENGINE_DOWN)
    emit({"type": "stage", "stage": "checking"})
    # a statement with no quote can never be confirmed: it would be the model's word alone
    v = verify(pkg, claims, store=ctx.store, policy=ctx.policy, classification=ctx.classification)
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
        removed=len(claims) - len(v.confirmed) - len(v.review_needed),
        message=message,
        ladder_level=level,
        engine=used,
    )
