"""Assist API — the C2-24 calls the e-Office screens make (plan §11.3 'Context in / Results out',
§11.5 touchpoints 10, 11, 15; drafts out).

- Identity comes from an injected `identify(request)` (sandbox: simulated sign-in; GCP: IAP).
  No identity, or one the connector does not know → 401 with a neutral message.
- Every call re-reads the officer's grants from the connector into a fresh access store.
- "Not available" is the same for unknown and unreachable files (plan §5.4).
- Write-back is limited to drafts, created only on the officer's click (CLAUDE.md §2.4).
- Every call is audited with IDs only — never question text or document text (plan §10.4).
"""

import contextlib
import datetime as dt
import logging
import queue
import re
import threading
import uuid
from collections.abc import Callable, Iterator
from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.agents.answer import AskStatus, ask
from app.agents.brief import approval_brief
from app.agents.dfa import draft_for_approval, governing_orders
from app.agents.first_cut import first_cut_note
from app.agents.intents import IntentSlots
from app.agents.local_reference import local_reference
from app.agents.orchestrator import Memory, TurnServices, run_turn
from app.agents.passage_context import context_of
from app.agents.receipts import review_receipt
from app.agents.runtime import AssistRuntime
from app.agents.streaming import Emit, Event, sse
from app.agents.tools import (
    ToolName,
    ToolResult,
    call_tool,
    check_document_status,
    visible_document,
    visible_facts,
)
from app.audit.log import AuditLog
from app.auth.messages import (
    CITED_NOT_FOUND,
    DOCUMENT_NOT_AVAILABLE,
    FILE_NOT_AVAILABLE,
    GUIDE,
    NEUTRAL_FAILURE,
    NOT_IN_COLLECTION,
    RECEIPT_NOT_AVAILABLE,
    REVIEW_ITEM_NOT_AVAILABLE,
    TOO_MANY,
)
from app.auth.models import DocumentAccessTags
from app.auth.policy import ScopeError, check, scope_for
from app.auth.rate_limit import RateLimiter
from app.auth.store import AuthzStore
from app.conflict.deterministic import ConflictFlag
from app.conflict.facts import extract_proposal_facts
from app.conflict.highlights import highlight_citations
from app.conflict.judgment import Evidence, contradiction_flags, settled_pairs
from app.conflict.presend import PreSendReport, presend_check
from app.connectors.eoffice import (
    ConnectorError,
    DraftKind,
    DraftRequest,
    EOfficeConnector,
    FileContext,
    OfficerContext,
)
from app.graph.repository import Direction, EdgeKind
from app.hitl.feedback import (
    Action,
    ActionLog,
    HumanAction,
    InMemoryActionLog,
    Reason,
    TargetKind,
)
from app.hitl.queue import ReviewItem, ReviewKind
from app.identifiers.canonical import InvalidCanonicalIdError, lookup_keys
from app.identifiers.display import department_names, reference_text
from app.ingestion.diarise import prefill
from app.ingestion.document_store import PREVIEWABLE, extension, media_type
from app.ingestion.metadata import (
    DocType,
    DocumentMetadata,
    cited_references,
    extract_metadata,
)
from app.ingestion.pipeline import ConfirmError, IngestStatus, review_text
from app.memory.session import SessionError, SessionMemory
from app.noting.chain import FileSoFar, file_so_far
from app.noting.closing import closing_remarks
from app.noting.draft_studio import (
    DraftInputs,
    FormatCatalogue,
    close_matches,
    compose,
    merge_read,
    read_items_for,
    standing_of,
    suggest_wording,
)
from app.noting.drafter import DraftNote, draft_note
from app.noting.movements import MovementSummary, movement_summary
from app.noting.references import suggest_references
from app.noting.workspace import (
    NEW_MATTER,
    InMemoryWorkspaceStore,
    Workspace,
    WorkspaceStore,
)
from app.precedent.consistency import EarlierNote, precedent_flags
from app.precedent.handover import SectionFile, build_handover
from app.precedent.links import suggest_links
from app.retrieval.graph_expansion import expand
from app.retrieval.references import LookupStatus, lookup_reference
from app.retrieval.scoped import L1Criteria
from app.temporal.since_decision import NewerOrder, since_decision
from app.tracking.monitor import MonitorData
from app.tracking.query_log import InMemoryQueryLog, QueryLog
from app.tracking.signals import SignalConfig
from app.tracking.usage import Usage
from app.updates.reconcile import notices_for

NOT_SIGNED_IN = "Not signed in."
NOT_AVAILABLE = FILE_NOT_AVAILABLE  # ADR-0016: same for unknown and hidden
NO_MATCH = (
    f"No matching order was found in the records available to you. {NOT_IN_COLLECTION} {GUIDE}"
)
NOT_CONFIGURED = "The assistant is not configured yet."
DOC_NOT_AVAILABLE = DOCUMENT_NOT_AVAILABLE
CANONICAL_ID = r"^[A-Za-z0-9][A-Za-z0-9.\-]{2,119}$"
# Why a paper of a file is not yet in institutional memory (ADR-0045), in the officer's words
WAITING_FOR = {
    ReviewKind.LOW_CONFIDENCE_EXTRACTION: "OCR review",
    ReviewKind.UNSUPPORTED_FILE: "a readable copy (this format cannot be read)",
    ReviewKind.UNRESOLVED_REFERENCE: "its number to be confirmed",
    ReviewKind.ID_COLLISION: "its number to be confirmed",
    ReviewKind.DATE_MISMATCH: "its date to be confirmed",
    ReviewKind.CLASSIFICATION_MISMATCH: "a check of its classification marking",
    ReviewKind.DEPARTMENT_MISMATCH: "a check of its department",
}


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchIn(_In):
    query: str = Field(min_length=1, max_length=500)


class AskIn(_In):
    question: str = Field(min_length=3, max_length=500)


_NO_NOTE = {
    "engine_off": "not drafted (needs Gemini)",
    "engine_down": "not drafted: the answer engine is unavailable",
    "no_sources": "not drafted: no order paragraph or earlier decision applies to write from",
    "all_removed": "not drafted: no line passed the citation check",
}


def _note_fields(note: DraftNote) -> dict[str, Any]:
    """The noting agent's text (ADR-0030), or why there is none. Lines the check removed are
    counted, never shown."""
    if not note.sections:
        text = _NO_NOTE.get(note.reason or "", "not drafted")
        return {"note_text": text, "note": note.model_dump(mode="json")}
    return {"note_text": note.text, "note": note.model_dump(mode="json")}


log = logging.getLogger(__name__)
_DRAFT = re.compile(r"\b(draft|prepare|write)\b.*\b(note|noting|yellow note)\b", re.I)


class ChatIn(_In):
    message: str = Field(min_length=2, max_length=500)
    session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{16,32}$")
    computer_no: str | None = Field(default=None, max_length=40)  # the file open in e-Office


class ReferenceIn(_In):
    text: str = Field(min_length=1, max_length=300)


class PresendIn(_In):
    computer_no: str = Field(pattern=r"^\d{4,12}$")
    text: str | None = Field(default=None, max_length=20000)  # the officer's draft, if edited


class FileIn(_In):
    computer_no: str = Field(pattern=r"^\d{4,12}$")


class NewFileIn(_In):
    subject: str = Field(min_length=10, max_length=500)


class ReceiptIn(_In):
    computer_no: str = Field(pattern=r"^\d{4,12}$")
    as_of: dt.date | None = None  # replay a past day in the sandbox; default: today's as-of date


class NoteReferenceIn(_In):
    computer_no: str = Field(pattern=r"^\d{4,12}$")
    text: str = Field(min_length=1, max_length=500)  # what the officer wants to refer to
    as_of: dt.date | None = None


class HighlightNoteIn(_In):
    note_id: str = Field(min_length=1, max_length=64)
    text: str = Field(max_length=20000)


class HighlightsIn(_In):
    computer_no: str = Field(pattern=r"^\d{4,12}$")
    notes: tuple[HighlightNoteIn, ...] = Field(max_length=60)
    as_of: dt.date | None = None


class FeedbackIn(_In):
    """Thumbs on an answer or a statement; accept / dismiss on a conflict flag (plan §9.2).
    IDs and fixed codes only — no free text."""

    kind: TargetKind
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")  # the output acted on
    action: Action
    session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{16,32}$")  # answers
    canonical_id: str | None = Field(default=None, max_length=160)  # statements; a flag's cited ID
    computer_no: str | None = Field(default=None, pattern=r"^\d{4,12}$")  # conflict flags
    flag_type: str | None = Field(default=None, pattern=r"^[A-G]$")
    reason: Reason | None = None


class AlertReviewIn(_In):
    """A monitoring officer's review of an alert (ADR-0036): fixed codes only."""

    action: Literal[Action.REVIEWED, Action.ESCALATED]
    reason: Reason | None = None


_FEEDBACK_ACTIONS = {
    TargetKind.ANSWER: {Action.THUMBS_UP, Action.THUMBS_DOWN},
    TargetKind.STATEMENT: {Action.THUMBS_UP, Action.THUMBS_DOWN},
    TargetKind.CONFLICT_FLAG: {Action.ACCEPTED, Action.DISMISSED},
}


class OcrReviewIn(_In):
    reason: str = Field(min_length=3, max_length=500)
    corrected_text: str | None = Field(default=None, max_length=200_000)


_REF_ID = r"^[A-Za-z0-9#._()-]{3,120}$"
_OWN_NUMBER = re.compile(r"^((?:Circular )?Memo No\.\s*\S+)\s+Dated:", re.M)


class WorkspaceTargetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    computer_no: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]{1,64}$")


class WorkspaceIn(WorkspaceTargetIn):
    workspace: Workspace


class DraftPrepareIn(_In):
    # None: a NEW matter — no file yet; "Create the file and save" opens one (touchpoint 5)
    computer_no: str | None = Field(default=None, pattern=r"^\d{4,12}$")
    format_id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,40}$")
    inputs: DraftInputs = DraftInputs()
    add_references: tuple[Annotated[str, Field(pattern=_REF_ID)], ...] = Field(
        default=(), max_length=20
    )
    drop_references: tuple[Annotated[str, Field(pattern=_REF_ID)], ...] = Field(
        default=(), max_length=40
    )
    suggest: bool = False  # ask the model for wording (Gemini, behind the circuit breaker)


class DraftIn(_In):
    computer_no: str = Field(pattern=r"^\d{4,12}$")
    kind: DraftKind
    body: str = Field(min_length=1, max_length=20000)
    citations: tuple[str, ...] = Field(default=(), max_length=50)
    request_id: str = Field(min_length=1, max_length=64)


class DocOut(BaseModel):
    canonical_id: str
    doc_type: str
    subject: str
    issue_date: dt.date | None
    file_no: str | None


class Officer:
    """Resolved per request."""

    def __init__(self, ctx: OfficerContext, request_id: str) -> None:
        self.ctx = ctx
        self.request_id = request_id


def contradiction_check(
    run: AssistRuntime,
) -> Callable[[list[str], str], tuple[list[ConflictFlag], bool]]:
    """B / G (plan §6.5) on the cited records the officer may see: their indexed texts only,
    pairs joined by a supersession / amendment link left to A / F."""
    assert run.llm is not None
    llm = run.llm

    def check(cited: list[str], note: str) -> tuple[list[ConflictFlag], bool]:
        docs = [
            Evidence(
                canonical_id=c,
                level=(
                    run.stores.instruments[c].hierarchy_level
                    if c in run.stores.instruments
                    else None
                ),
                text=run.texts.get(c, ""),
            )
            for c in cited
            if run.texts.get(c)
        ]
        linked = settled_pairs(run.stores.relations)
        res = contradiction_flags(docs, llm, linked, context=note)
        flags = list(res.flags)
        used = getattr(llm, "last_used", None)
        primary = getattr(getattr(llm, "primary", None), "name", None)
        if flags and used and primary and used != primary:  # say so: a weaker local model judged
            flags = [
                f.model_copy(
                    update={
                        "explanation": f"{f.explanation} (Judged by the fallback model {used}; "
                        "the main model was unavailable.)"
                    }
                )
                for f in flags
            ]
        return flags, res.failed == 0

    return check


def build_assist_router(
    *,
    connector: EOfficeConnector,
    runtime: Callable[[], AssistRuntime | None],
    audit: AuditLog,
    identify: Callable[[Request], str | None],
    memory: Memory | None = None,
    query_log: QueryLog | None = None,
    actions: ActionLog | None = None,
    usage: Callable[[dt.date], Usage] | None = None,
    monitoring_users: frozenset[str] = frozenset(),
    log_questions: bool = False,
    monitor: Callable[[dt.date, int], MonitorData] | None = None,
    signals: SignalConfig | None = None,
    limiter: RateLimiter | None = None,
    draft_formats: FormatCatalogue | None = None,
    workspaces: WorkspaceStore | None = None,
) -> APIRouter:
    r = APIRouter(prefix="/assist", tags=["assist"])
    saved_drafts: WorkspaceStore = (
        workspaces if workspaces is not None else InMemoryWorkspaceStore()
    )
    sessions: Memory = memory if memory is not None else SessionMemory()
    tracked: QueryLog = query_log if query_log is not None else InMemoryQueryLog()
    feedback_log: ActionLog = actions if actions is not None else InMemoryActionLog()

    def officer(request: Request) -> Officer:
        rid = getattr(request.state, "request_id", None) or uuid.uuid4().hex[:16]
        user_id = identify(request)
        try:
            if not user_id:
                raise ConnectorError("no identity")
            ctx = connector.officer_context(user_id)
        except ConnectorError:
            audit.record(rid, None, "assist.identify", "denied")
            raise HTTPException(status_code=401, detail=NOT_SIGNED_IN) from None
        return Officer(ctx, rid)

    def rt(o: Officer, action: str) -> AssistRuntime:
        wait = limiter.check(o.ctx.user_id, action) if limiter is not None else None
        if wait is not None:
            audit.record(o.request_id, o.ctx.user_id, action, "rate_limited")
            raise HTTPException(
                status_code=429,
                detail=TOO_MANY,
                headers={"Retry-After": str(int(wait + 0.999))},
            )
        got = runtime()
        if got is None:
            audit.record(o.request_id, o.ctx.user_id, action, "error", detail="not configured")
            raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
        return got

    def open_file(o: Officer, run: AssistRuntime, computer_no: str, action: str) -> FileContext:
        """e-Office reach (connector) AND C2-24's own check on the file's classification and
        location (plan §11.1 'same access as e-Office, plus classification'). Unknown, out of
        reach and not cleared all give the same 404."""
        try:
            fctx = connector.file_context(computer_no, o.ctx.user_id)
        except ConnectorError:
            fctx = None
        if fctx is not None:
            tags = DocumentAccessTags(
                doc_id=f"file:{fctx.file_no}",
                department=fctx.department,
                section=fctx.dealing_section,
                classification=fctx.classification,
                file_no=fctx.file_no,
            )
            store = run.store_for(o.ctx)
            if check(o.ctx.user_id, tags, store, run.policy, run.classification).allowed:
                return fctx
        audit.record(o.request_id, o.ctx.user_id, action, "not_available")
        raise HTTPException(status_code=404, detail=NOT_AVAILABLE)

    def docs_out(run: AssistRuntime, res: ToolResult) -> list[DocOut]:
        out = []
        for d in (*res.documents, *res.status_unconfirmed):
            tags = run.tags(d.canonical_id)
            out.append(
                DocOut(
                    canonical_id=d.canonical_id,
                    doc_type=d.doc_type,
                    subject=d.subject,
                    issue_date=d.issue_date,
                    file_no=tags.file_no if tags else None,
                )
            )
        return out

    def meta(run: AssistRuntime) -> dict[str, Any]:
        return {"calibrated": run.calibrated, "mock_rules": run.rules.status.value == "mock"}

    @r.post("/search")
    def search(body: SearchIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Touchpoint 15 — plain-language search within the officer's scope."""
        run = rt(o, "assist.search")
        store = run.store_for(o.ctx)
        res = call_tool(
            run.tool_context(o.ctx.user_id, store),
            ToolName.SEARCH_AUTHORIZED_DOCUMENTS,
            IntentSlots(text=body.query).model_dump(exclude_none=True, exclude_defaults=True),
        )
        docs = docs_out(run, res)
        audit.record(
            o.request_id,
            o.ctx.user_id,
            "assist.search",
            "ok" if docs else "no_answer",
            ids=tuple(d.canonical_id for d in docs),
        )
        return {
            "request_id": o.request_id,
            "documents": [d.model_dump() for d in docs],
            "files": sorted({d.file_no for d in docs if d.file_no}),
            "ladder_level": res.ladder_level,
            **meta(run),
        }

    def chat_turn(body: ChatIn, o: Officer, emit: Emit | None = None) -> dict[str, Any]:
        """One conversational turn (plan §8.1, §10.1, §10.6; ADR-0029): one LangGraph run over
        `AgentState`. A follow-up ("that order") uses what earlier turns found, re-checked
        against the officer's access NOW. A session belongs to the officer who opened it;
        anyone else gets a fresh one, never a hint that it exists."""
        run = rt(o, "assist.chat")
        store = run.store_for(o.ctx)
        sid = body.session_id or uuid.uuid4().hex
        try:
            sessions.turns(o.ctx.user_id, sid)
        except SessionError:
            sid = uuid.uuid4().hex  # not this officer's session: start a new one, say nothing
        svc = TurnServices(
            officer=o.ctx,
            ctx=run.tool_context(o.ctx.user_id, store),
            memory=sessions,
            cache=run.stores.cache,
            query_log=tracked,
            texts=run.evidence_texts(o.ctx.user_id, store),
            llm=run.llm,
            departments=run.departments,
            file_papers=lambda file_no: [
                d.canonical_id
                for d in run.stores.index._docs  # noqa: SLF001 — reference store, re-checked
                if d.tags.file_no == file_no
            ],
            tags_of=run.tags,
            emit=emit,
            log_question=log_questions,
            signals=signals,
            reworded=run.stores.reworded,
        )
        final = run_turn(svc, session_id=sid, message=body.message, request_id=o.request_id)
        audit.record(  # IDs and outcome only: never the message or the answer text
            o.request_id,
            o.ctx.user_id,
            "assist.chat",
            "ok" if final.outcome == "answered" else (final.outcome or "error"),
            ids=final.authorized_candidates,
        )
        draft = None
        if body.computer_no and _DRAFT.search(body.message):
            # "draft the noting (using that precedent)": the first-cut points for the open file,
            # with the precedents the conversation found; a preview, never inserted by itself
            draft = first_cut_payload(
                o, run, body.computer_no, "assist.chat.first_cut", final.recalled
            )
        return {
            "session_id": sid,
            "turn": final.turn,
            "from_cache": final.cache_hit,
            "used_earlier_turn": bool(final.recalled),
            **(final.result or {}),
            "first_cut": draft,
            **meta(run),
        }

    @r.post("/chat")
    def chat(body: ChatIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """The conversational assistant, answered in one piece."""
        return chat_turn(body, o)

    @r.post("/chat/stream")
    def chat_stream(body: ChatIn, o: Annotated[Officer, Depends(officer)]) -> StreamingResponse:
        """The same turn as `/chat`, streamed as Server-Sent Events (ADR-0033): `stage`
        (searching, found N records, writing, checking), `statement` / `review` (each one only
        after it passed the citation check), then `done` with exactly the `/chat` answer, which
        replaces what was streamed. Sign-in and the officer's access are checked before the
        stream opens; a failure inside it ends with a neutral `error` event."""
        events: queue.Queue[Event | None] = queue.Queue()

        def work() -> None:
            try:
                events.put({"type": "done", "answer": chat_turn(body, o, events.put)})
            except Exception as exc:  # noqa: BLE001 — fail closed with the neutral message
                log.error("chat stream failed: %s", type(exc).__name__)
                events.put({"type": "error", "message": NEUTRAL_FAILURE})
            finally:
                events.put(None)

        def stream() -> Iterator[str]:
            threading.Thread(target=work, daemon=True).start()
            while (e := events.get()) is not None:
                yield sse(e)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
        )

    @r.post("/ask")
    def ask_question(body: AskIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """A cited answer from the records this officer may see (plan §8; milestone M4).
        Every statement shown was checked against the passage it cites."""
        run = rt(o, "assist.ask")
        store = run.store_for(o.ctx)
        ans = ask(
            run.tool_context(o.ctx.user_id, store),
            body.question,
            texts=run.evidence_texts(o.ctx.user_id, store),
            llm=run.llm,
            request_id=o.request_id,
            departments=run.departments,
            file_papers=lambda file_no: [
                d.canonical_id
                for d in run.stores.index._docs  # noqa: SLF001 — reference store, re-checked
                if d.tags.file_no == file_no
            ],
        )
        audit.record(  # IDs and outcome only: never the question or the answer text
            o.request_id,
            o.ctx.user_id,
            "assist.ask",
            "ok" if ans.status is AskStatus.ANSWERED else ans.status.value,
            ids=ans.documents,
        )
        return {**ans.model_dump(mode="json"), **meta(run)}

    @r.post("/reference")
    def reference(body: ReferenceIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Touchpoint 10 — the current version of an order the officer cites."""
        run = rt(o, "assist.reference")
        store = run.store_for(o.ctx)
        ctx = run.tool_context(o.ctx.user_id, store)
        look = lookup_reference(
            o.ctx.user_id,
            body.text,
            departments=run.departments,
            retriever=ctx.index,  # e-Office papers + the public corpus (cloud when configured)
            store=store,
            policy=run.policy,
            classification=run.classification,
        )
        base: dict[str, Any] = {"request_id": o.request_id, **meta(run)}
        if look.status is LookupStatus.AMBIGUOUS:
            audit.record(o.request_id, o.ctx.user_id, "assist.reference", "ambiguous", look.choices)
            return {**base, "found": False, "choices": list(look.choices)}
        if look.status is not LookupStatus.FOUND or look.canonical_id is None:
            audit.record(o.request_id, o.ctx.user_id, "assist.reference", "no_answer")
            return {**base, "found": False, "message": NO_MATCH}
        res = call_tool(
            ctx,
            ToolName.CHECK_DOCUMENT_STATUS,
            {"canonical_ids": (look.canonical_id,)},
        )
        loc = local_reference(body.text, look.canonical_id, res, lambda c: run.texts.get(c, ""))
        audit.record(
            o.request_id,
            o.ctx.user_id,
            "assist.reference",
            "ok",
            ids=(look.canonical_id, *([res.by] if res.by else [])),
        )
        return {
            **base,
            "found": res.available,
            "documents": [d.model_dump() for d in docs_out(run, res)],
            "status": res.status,
            "by": res.by,
            "since": res.since.isoformat() if res.since else None,
            "current_version": res.current_version,
            "message": res.message,
            "paragraph": loc.paragraph,
            "cited_clause": loc.cited_clause.model_dump() if loc.cited_clause else None,
            "successor_clause": loc.successor_clause.model_dump() if loc.successor_clause else None,
            "successor_is_current": loc.successor_is_current,
            "clause_note": loc.note,
        }

    def latest_note(
        o: Officer, run: AssistRuntime, fctx: FileContext, store: AuthzStore
    ) -> tuple[str | None, str, str]:
        """The file's latest note document this officer may see, its text, and the text of the
        file's earlier notes this officer may see (oldest first)."""

        def visible(cid: str) -> bool:
            t = run.tags(cid)
            return (
                t is not None
                and check(o.ctx.user_id, t, store, run.policy, run.classification).allowed
            )

        notes = [
            (issued or dt.date.min, cid)
            for cid, issued in run.stores.files.get(fctx.file_no, [])
            if (d := run.doc(cid)) is not None and d.doc_type.startswith("Noting") and visible(cid)
        ]
        note_id = max(notes)[1] if notes else None
        earlier = "\n".join(run.texts.get(cid, "") for _, cid in sorted(notes) if cid != note_id)
        return note_id, run.texts.get(note_id, "") if note_id else "", earlier

    def precedent_check(
        o: Officer, run: AssistRuntime, store: AuthzStore, note_id: str
    ) -> Callable[[str, DocumentMetadata], list[ConflictFlag]]:
        """Type D: earlier notes of OTHER files in the officer's scope (L1 template: same
        department, dated up to the note), each re-checked, compared by `precedent_flags`."""
        own = run.tags(note_id)

        def check_d(sheet: str, meta: DocumentMetadata) -> list[ConflictFlag]:
            if own is None or not own.file_no or not meta.subject:
                return []
            try:
                scope = scope_for(o.ctx.user_id, store, run.policy, run.classification)
            except ScopeError:  # fail closed: no scope, nothing compared
                return []
            found = run.stores.index.filter(
                L1Criteria(department=own.department, issued_to=meta.issue_date), scope
            )
            earlier = [
                EarlierNote(
                    file_no=d.tags.file_no,
                    doc_id=d.canonical_id,
                    subject=d.subject,
                    date=d.issue_date,
                    text=run.texts.get(d.canonical_id, ""),
                )
                for d in found
                if d.doc_type.startswith("Noting")
                and d.tags.file_no
                and check(o.ctx.user_id, d.tags, store, run.policy, run.classification).allowed
            ]
            return precedent_flags(
                file_no=own.file_no,
                subject=meta.subject,
                note_date=meta.issue_date,
                text=sheet,
                earlier=earlier,
            )

        return check_d

    def run_presend(
        o: Officer,
        run: AssistRuntime,
        store: AuthzStore,
        note_id: str,
        text: str,
        earlier: str,
        meta: DocumentMetadata | None = None,
    ) -> PreSendReport:
        tags_of = {c: t for c in run.stores.graph.node_ids() if (t := run.tags(c))}
        return presend_check(
            note_id,
            text,
            meta or extract_metadata(text, run.departments),
            user_id=o.ctx.user_id,
            instruments=run.stores.instruments,
            relations=list(run.stores.relations),
            tags_of=tags_of,
            rules=run.rules,
            store=store,
            policy=run.policy,
            classification=run.classification,
            windows=run.windows(),
            awaiting_review=tuple(run.stores.awaiting.values()),
            contradictions=contradiction_check(run) if run.llm is not None else None,
            file_notes=earlier,
            precedents=precedent_check(o, run, store, note_id),
        )

    @r.post("/presend")
    def presend(body: PresendIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Touchpoint 11 — the pre-send check on the note about to be sent."""
        run = rt(o, "assist.presend")
        fctx = open_file(o, run, body.computer_no, "assist.presend")
        store = run.store_for(o.ctx)
        found, found_text, earlier = latest_note(o, run, fctx, store)
        note_id = found or f"draft:{body.computer_no}"
        text = body.text if body.text is not None else found_text
        if not text.strip():
            audit.record(o.request_id, o.ctx.user_id, "assist.presend", "no_answer")
            return {
                "request_id": o.request_id,
                "outcome": "review_needed",
                "message": "There is no note in this file to check yet.",
                **meta(run),
            }
        rep = run_presend(o, run, store, note_id, text, earlier)
        audit.record(
            o.request_id,
            o.ctx.user_id,
            "assist.presend",
            "ok",
            ids=(body.computer_no, note_id, *(e for f in rep.flags for e in f.evidence_ids)),
            detail=rep.outcome.value,
        )
        return {"request_id": o.request_id, **_report(rep), **meta(run)}

    def first_cut_payload(
        o: Officer,
        run: AssistRuntime,
        computer_no: str,
        action_name: str,
        extra_precedents: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        """Touchpoint 6 body, shared by `/first-cut` and the conversation ("draft the noting
        using that precedent": `extra_precedents` are the earlier turn's records, re-checked)."""
        fctx = open_file(o, run, computer_no, action_name)
        store = run.store_for(o.ctx)
        ctx = run.tool_context(o.ctx.user_id, store)
        note_id, text, earlier = latest_note(o, run, fctx, store)
        meta_ = extract_metadata(text, run.departments) if note_id else None
        facts = (
            extract_proposal_facts(text, meta_, run.rules, note_id) if note_id and meta_ else None
        )
        rep = (
            run_presend(o, run, store, note_id, text, earlier) if note_id and text.strip() else None
        )

        def visible(cid: str) -> bool:
            t = run.tags(cid)
            return (
                t is not None
                and check(o.ctx.user_id, t, store, run.policy, run.classification).allowed
            )

        def file_of(cid: str) -> str | None:
            t = run.tags(cid)
            return t.file_no if t else None

        links = suggest_links(ctx, fctx.subject, fctx.file_no, file_of)
        fc = first_cut_note(
            ctx=ctx,
            file_no=fctx.file_no,
            subject=fctx.subject,
            draft_note=note_id,
            meta=meta_,
            action=facts.facts.action if facts and facts.facts else None,
            flags=rep.flags if rep else (),
            precedents=[
                *(
                    (f, c)
                    for c in extra_precedents
                    if visible(c) and (f := file_of(c)) and f != fctx.file_no
                ),
                *((lk.file_no, d.canonical_id) for lk in links for d in lk.documents),
            ],
            text_of=lambda c: run.texts.get(c, ""),
            windows=[w for w in run.windows() if visible(w.source.split("#", 1)[0])],
        )
        audit.record(
            o.request_id,
            o.ctx.user_id,
            action_name,
            "ok",
            ids=(computer_no, *([note_id] if note_id else []), *fc.citations),
        )
        return {
            "request_id": o.request_id,
            "computer_no": computer_no,
            **fc.model_dump(mode="json", exclude={"flags"}),
            "flags": _report_flags(fc.flags),
            **_note_fields(draft_note(fc, fctx.subject, run.llm)),
        }

    @r.post("/first-cut")
    def first_cut(body: FileIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Touchpoint 6 — the cited points for a Yellow Note (orders, their paragraphs, earlier
        decisions, open points). A preview; "Insert as Yellow Note" is the officer's click."""
        run = rt(o, "assist.first_cut")
        return {**first_cut_payload(o, run, body.computer_no, "assist.first_cut"), **meta(run)}

    @r.post("/dfa")
    def dfa(body: FileIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Touchpoint 14 — the deterministic parts of a draft for approval (abstract, "Read the
        following", open points). A preview only; "Create DFA draft" is the officer's click."""
        run = rt(o, "assist.dfa")
        fctx = open_file(o, run, body.computer_no, "assist.dfa")
        store = run.store_for(o.ctx)
        note_id, text, earlier = latest_note(o, run, fctx, store)
        meta_ = extract_metadata(text, run.departments) if note_id else None
        facts = (
            extract_proposal_facts(text, meta_, run.rules, note_id) if note_id and meta_ else None
        )
        rep = (
            run_presend(o, run, store, note_id, text, earlier) if note_id and text.strip() else None
        )
        pv = draft_for_approval(
            ctx=run.tool_context(o.ctx.user_id, store),
            file_no=fctx.file_no,
            subject=fctx.subject,
            draft_note=note_id,
            meta=meta_,
            action=facts.facts.action if facts and facts.facts else None,
            flags=rep.flags if rep else (),
            awaiting_review=tuple(run.stores.awaiting.values()),
        )
        audit.record(
            o.request_id,
            o.ctx.user_id,
            "assist.dfa",
            "ok",
            ids=(body.computer_no, *([note_id] if note_id else []), *pv.citations),
        )
        return {
            "request_id": o.request_id,
            "computer_no": body.computer_no,
            **pv.model_dump(mode="json", exclude={"flags"}),
            "flags": _report_flags(pv.flags),
            "order_paragraphs": "not drafted (needs Gemini)",
            **meta(run),
        }

    @r.post("/file-so-far")
    def so_far(body: FileIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Touchpoint 8 — the note chain by post, the last direction, and what is missing."""
        run = rt(o, "assist.file_so_far")
        fctx = open_file(o, run, body.computer_no, "assist.file_so_far")
        store = run.store_for(o.ctx)

        def allowed(t: DocumentAccessTags) -> bool:
            return check(o.ctx.user_id, t, store, run.policy, run.classification).allowed

        docs = [
            (cid, run.texts.get(cid, ""))
            for cid, _ in run.stores.files.get(fctx.file_no, [])
            if (d := run.doc(cid)) is not None
            and d.doc_type.startswith("Noting")
            and (t := run.tags(cid)) is not None
            and allowed(t)
        ]
        fs = file_so_far(docs)
        pending = sum(allowed(t) for t in run.held_by_file.get(fctx.file_no, []))
        audit.record(
            o.request_id,
            o.ctx.user_id,
            "assist.file_so_far",
            "ok" if fs.notes else "no_answer",
            ids=(body.computer_no, *fs.sources),
        )
        return {
            "request_id": o.request_id,
            "computer_no": body.computer_no,
            "file_no": fctx.file_no,
            "notes": [
                {
                    "note_no": n.note_no,
                    "paragraphs": list(n.paragraphs) if n.paragraphs else None,
                    "post": n.post,
                    "signed_at": n.signed_at.isoformat() if n.signed_at else None,
                    "text": n.text,
                    "source": n.source,
                }
                for n in fs.notes
            ],
            "chain": list(fs.chain),
            "last_direction": fs.last_direction.note_no if fs.last_direction else None,
            "gaps": [list(g) for g in fs.gaps],
            "gap_message": (
                "Not available in the records available to you: "
                + ", ".join(f"Note #{a}" if a == b else f"Notes #{a}–#{b}" for a, b in fs.gaps)
                + ". Nothing is inferred for them."
                if fs.gaps
                else None
            ),
            "pending_documents": pending,
            "pending_message": (
                f"{pending} more document(s) in this file are scanned and waiting for text "
                "review; their notes are not shown yet."
                if pending
                else None
            ),
            **meta(run),
        }

    # --- extended touchpoints 12, 17, 19 (plan §11.5; ADR-0037) -------------------------------

    def readable_chain(o: Officer, run: AssistRuntime, file_no: str) -> FileSoFar:
        """The file's notes this officer may read now (as touchpoint 8)."""
        store = run.store_for(o.ctx)
        return file_so_far(
            (cid, run.texts.get(cid, ""))
            for cid, _ in run.stores.files.get(file_no, [])
            if (d := run.doc(cid)) is not None
            and d.doc_type.startswith("Noting")
            and (t := run.tags(cid)) is not None
            and check(o.ctx.user_id, t, store, run.policy, run.classification).allowed
        )

    def orders_relied_on(o: Officer, run: AssistRuntime, file_no: str) -> list[str]:
        """Orders the file's papers cite (L3, one hop out), each one the officer may see."""
        store = run.store_for(o.ctx)
        ctx = run.tool_context(o.ctx.user_id, store)
        papers = [
            cid
            for cid, _ in run.stores.files.get(file_no, [])
            if visible_document(ctx, cid) is not None
        ]
        cited = expand(
            o.ctx.user_id,
            papers,
            graph=ctx.graph,
            kinds=frozenset({EdgeKind.CITES, EdgeKind.REFERENCES}),
            direction=Direction.OUT,
            max_hops=1,
            store=store,
            policy=run.policy,
            classification=run.classification,
        )
        own = set(papers)
        return [
            c
            for c in dict.fromkeys(h.canonical_id for h in cited.hits)
            if c not in own and visible_document(ctx, c) is not None
        ]

    def moves_of(o: Officer, run: AssistRuntime, fctx: FileContext) -> MovementSummary:
        creator = None
        if fctx.created_by:
            with contextlib.suppress(ConnectorError):
                creator = connector.officer_context(fctx.created_by).post
        return movement_summary(
            file_no=fctx.file_no,
            state=fctx.state,
            movements=fctx.movements,
            chain=readable_chain(o, run, fctx.file_no),
            as_of=run.as_of,
            created_by=fctx.created_by,
            created_by_post=creator,
        )

    @r.post("/movements")
    def movements_view(body: FileIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Touchpoint 12 — "Initiate action": the remarks at each movement, the note each sender
        put up, and where the file is pending (e-Office's own records; nothing inferred)."""
        action = "assist.movements"
        run = rt(o, action)
        fctx = open_file(o, run, body.computer_no, action)
        m = moves_of(o, run, fctx)
        audit.record(
            o.request_id,
            o.ctx.user_id,
            action,
            "ok" if m.steps else "no_answer",
            ids=(body.computer_no, *(n.source for st in m.steps for n in st.notes)),
        )
        return {
            "request_id": o.request_id,
            "computer_no": body.computer_no,
            "subject": fctx.subject,
            **m.model_dump(mode="json"),
            **meta(run),
        }

    @r.post("/since-decision")
    def since_decision_view(
        body: FileIn, o: Annotated[Officer, Depends(officer)]
    ) -> dict[str, Any]:
        """Touchpoint 17 — "Reopening a file": what was decided (the last direction, its own
        note) and what has changed since in the orders it relied on (status, amendments,
        clarifications), all within the officer's access."""
        action = "assist.since_decision"
        run = rt(o, action)
        fctx = open_file(o, run, body.computer_no, action)
        store = run.store_for(o.ctx)
        ctx = run.tool_context(o.ctx.user_id, store)
        relied = orders_relied_on(o, run, fctx.file_no)
        newer_hits = expand(
            o.ctx.user_id,
            relied,
            graph=ctx.graph,
            kinds=frozenset({EdgeKind.AMENDS, EdgeKind.CLARIFIES}),
            direction=Direction.IN,
            max_hops=1,
            store=store,
            policy=run.policy,
            classification=run.classification,
        )
        newer: dict[str, list[NewerOrder]] = {}
        for h in newer_hits.hits:
            d = visible_document(ctx, h.canonical_id)
            if d is None or not h.path:
                continue
            newer.setdefault(h.path[0], []).append(
                NewerOrder(
                    canonical_id=h.canonical_id,
                    kind="amended" if h.via is EdgeKind.AMENDS else "clarified",
                    issue_date=d.issue_date,
                    subject=d.subject,
                )
            )

        def subject_of(cid: str) -> str | None:
            d = visible_document(ctx, cid)
            return d.subject if d else None

        def date_of(cid: str) -> dt.date | None:
            d = visible_document(ctx, cid)
            return d.issue_date if d else None

        sd = since_decision(
            file_no=fctx.file_no,
            state=fctx.state,
            chain=readable_chain(o, run, fctx.file_no),
            movements=fctx.movements,
            relied_on=relied,
            status_of=lambda c: check_document_status(ctx, c),
            newer=newer,
            subject_of=subject_of,
            date_of=date_of,
        )
        audit.record(
            o.request_id,
            o.ctx.user_id,
            action,
            "ok" if sd.decided or sd.relied_on else "no_answer",
            ids=(body.computer_no, *relied),
        )
        return {
            "request_id": o.request_id,
            "computer_no": body.computer_no,
            "subject": fctx.subject,
            **sd.model_dump(mode="json"),
            **meta(run),
        }

    @r.get("/handover")
    def handover_view(o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Touchpoint 19 — section handover for the officer's own dealing section: files in
        hand, standing orders, orders no longer in force, recent decisions. Only files the
        officer can open now and orders they may see are used or counted."""
        action = "assist.handover"
        run = rt(o, action)
        store = run.store_for(o.ctx)
        ctx = run.tool_context(o.ctx.user_id, store)
        section = o.ctx.section
        if not section:
            audit.record(o.request_id, o.ctx.user_id, action, "no_answer")
            return {
                "request_id": o.request_id,
                "section": None,
                "message": "You hold no dealing section, so there is nothing to hand over.",
                **meta(run),
            }
        files: list[SectionFile] = []
        for f in connector.section_files(o.ctx.user_id):
            try:
                fctx = open_file(o, run, f.computer_no, action)
            except HTTPException:
                continue  # not cleared for it now: left out and not counted
            relied = []
            for cid in orders_relied_on(o, run, fctx.file_no):
                d = visible_document(ctx, cid)
                relied.append(
                    (
                        cid,
                        check_document_status(ctx, cid),
                        d.issue_date if d else None,
                        d.subject if d else None,
                    )
                )
            files.append(SectionFile(file=f, moves=moves_of(o, run, fctx), relied_on=relied))
        h = build_handover(
            section=section,
            department=o.ctx.department,
            as_of=run.as_of,
            files=files,
            date_of=lambda c: d.issue_date if (d := visible_document(ctx, c)) else None,
        )
        audit.record(
            o.request_id,
            o.ctx.user_id,
            action,
            "ok" if files else "no_answer",
            ids=tuple(f.file.computer_no for f in files)[:50],
        )
        return {"request_id": o.request_id, **h.model_dump(mode="json"), **meta(run)}

    @r.post("/previous-references")
    def previous_references(
        body: NewFileIn, o: Annotated[Officer, Depends(officer)]
    ) -> dict[str, Any]:
        """Touchpoint 5 — creating a file: earlier files on the same subject to enter as Previous
        References (precedent lookup through the scoped ladder; ADR-0038). Only files the officer
        can open are offered; the officer chooses."""
        action = "assist.previous_references"
        run = rt(o, action)
        store = run.store_for(o.ctx)

        def file_of(cid: str) -> str | None:
            t = run.tags(cid)
            return t.file_no if t else None

        out: list[dict[str, Any]] = []
        for s_ in suggest_links(
            run.tool_context(o.ctx.user_id, store), body.subject, "", file_of, limit=8
        ):
            cno = connector.file_computer_no(s_.file_no, o.ctx.user_id)
            if cno is None:
                continue  # a paper the officer may see, on a file they cannot open: not offered
            out.append(
                {
                    "file_no": s_.file_no,
                    "computer_no": cno,
                    "rank": len(out) + 1,
                    "documents": [d.model_dump(mode="json") for d in s_.documents],
                }
            )
        out = out[:5]
        audit.record(
            o.request_id,
            o.ctx.user_id,
            action,
            "ok" if out else "no_answer",
            ids=tuple(str(x["computer_no"]) for x in out),
        )
        return {
            "request_id": o.request_id,
            "suggestions": out,
            "message": None
            if out
            else "No earlier file on this subject was found in the records available to you.",
            **meta(run),
        }

    @r.post("/closing-remarks")
    def closing_remarks_view(
        body: FileIn, o: Annotated[Officer, Depends(officer)]
    ) -> dict[str, Any]:
        """Touchpoint 16 — closing a file: suggested closing remarks from the file's own record
        (the last direction, orders issued after it) and what still stands in the way. A
        suggestion only: the officer edits it and closes the file in e-Office (ADR-0038)."""
        action = "assist.closing_remarks"
        run = rt(o, action)
        fctx = open_file(o, run, body.computer_no, action)
        store = run.store_for(o.ctx)
        ctx = run.tool_context(o.ctx.user_id, store)
        chain = readable_chain(o, run, fctx.file_no)
        issued = []
        for cid, _ in run.stores.files.get(fctx.file_no, []):
            d = visible_document(ctx, cid)
            if d is not None and not d.doc_type.startswith("Noting"):
                issued.append((cid, d.issue_date, d.doc_type))
        holder = fctx.movements[-1].to_user if fctx.movements else fctx.created_by
        cr = closing_remarks(
            state=fctx.state,
            chain=chain,
            issued=issued,
            yellow_notes=sum(1 for n in fctx.notes if not n.confirmed),
            holder=holder,
            user_id=o.ctx.user_id,
        )
        audit.record(
            o.request_id,
            o.ctx.user_id,
            action,
            "ok" if cr.text else "no_answer",
            ids=(body.computer_no, *cr.cited),
        )
        return {
            "request_id": o.request_id,
            "computer_no": body.computer_no,
            "file_no": fctx.file_no,
            **cr.model_dump(mode="json"),
            **meta(run),
        }

    @r.post("/note-reference")
    def note_reference(
        body: NoteReferenceIn, o: Annotated[Officer, Depends(officer)]
    ) -> dict[str, Any]:
        """Touchpoint 7 — a previous note paragraph or correspondence page of this file to cite.
        Suggestions only; inserting is the officer's click (`/assist/draft`, suggested_reference).
        """
        run = rt(o, "assist.note_reference")
        fctx = open_file(o, run, body.computer_no, "assist.note_reference")
        if run.references is None:  # not configured: fail closed, never guess a threshold
            audit.record(o.request_id, o.ctx.user_id, "assist.note_reference", "not_configured")
            raise HTTPException(status_code=503, detail="Reference matching is not configured.")
        store = run.store_for(o.ctx)

        def allowed(t: DocumentAccessTags) -> bool:
            return check(o.ctx.user_id, t, store, run.policy, run.classification).allowed

        docs = [
            (cid, run.texts.get(cid, ""), t)
            for cid, _ in run.stores.files.get(fctx.file_no, [])
            if (d := run.doc(cid)) is not None
            and d.doc_type.startswith("Noting")
            and (t := run.tags(cid)) is not None
        ]
        res = suggest_references(
            body.text,
            fctx,
            docs,
            as_of=body.as_of or run.as_of,
            allowed=allowed,
            order_visible=lambda c: (t := run.tags(c)) is not None and allowed(t),
            cfg=run.references,
        )
        audit.record(
            o.request_id,
            o.ctx.user_id,
            "assist.note_reference",
            "ok" if res.suggestions else "no_answer",
            ids=(body.computer_no, *(s.target_id for s in res.suggestions)),
            detail=res.matched_by.value,
        )
        return {
            "request_id": o.request_id,
            "computer_no": body.computer_no,
            "matched_by": res.matched_by.value,
            "suggestions": [s.model_dump(mode="json") for s in res.suggestions],
            "message": None
            if res.suggestions
            else "No matching note paragraph or page in this file is available to you.",
            "matching": "keyword stand-in (not semantic)",
            **meta(run),
        }

    @r.post("/link-suggestions")
    def link_suggestions(body: FileIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Touchpoint 9 — precedent files the officer may open, to link as read-only references."""
        run = rt(o, "assist.link_suggestions")
        fctx = open_file(o, run, body.computer_no, "assist.link_suggestions")
        store = run.store_for(o.ctx)

        def file_of(cid: str) -> str | None:
            t = run.tags(cid)
            return t.file_no if t else None

        links = suggest_links(
            run.tool_context(o.ctx.user_id, store), fctx.subject, fctx.file_no, file_of
        )
        audit.record(
            o.request_id,
            o.ctx.user_id,
            "assist.link_suggestions",
            "ok" if links else "no_answer",
            ids=(body.computer_no, *(d.canonical_id for s in links for d in s.documents)),
        )
        return {
            "request_id": o.request_id,
            "computer_no": body.computer_no,
            "suggestions": [
                {
                    "file_no": s.file_no,
                    "rank": s.rank,
                    "documents": [d.model_dump(mode="json") for d in s.documents],
                }
                for s in links
            ],
            "message": None
            if links
            else "No precedent files were found in the records available to you.",
            **meta(run),
        }

    @r.post("/receipt")
    def receipt(body: ReceiptIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Touchpoints 2 and 3 — receipt summary, validity of what it relies on, where to put it."""
        run = rt(o, "assist.receipt")
        try:
            rctx = connector.receipt_context(body.computer_no, o.ctx.user_id)
        except ConnectorError:
            audit.record(o.request_id, o.ctx.user_id, "assist.receipt", "not_available")
            raise HTTPException(status_code=404, detail=RECEIPT_NOT_AVAILABLE) from None
        store = run.store_for(o.ctx)
        rv = review_receipt(
            rctx,
            user_id=o.ctx.user_id,
            as_of=body.as_of or run.as_of,
            departments=run.departments,
            index=run.stores.index,
            documents=lambda: list(run.stores.index._docs),  # noqa: SLF001 — reference store
            graph=run.stores.graph,
            instruments=run.stores.instruments,
            relations=list(run.stores.relations),
            text_of=lambda c: run.texts.get(c, ""),
            store=store,
            policy=run.policy,
            classification=run.classification,
        )
        doc = rv.document
        audit.record(
            o.request_id,
            o.ctx.user_id,
            "assist.receipt",
            "ok" if doc else "no_answer",
            ids=(body.computer_no, *([doc.canonical_id] if doc else []), *rv.cited),
        )
        return {
            "request_id": o.request_id,
            "computer_no": body.computer_no,
            "as_of": (body.as_of or run.as_of).isoformat(),
            "document": DocOut(
                canonical_id=doc.canonical_id,
                doc_type=doc.doc_type,
                subject=doc.subject,
                issue_date=doc.issue_date,
                file_no=doc.tags.file_no,
            ).model_dump(mode="json")
            if doc
            else None,
            "summary": list(rv.summary),
            "cited": list(rv.cited),
            "flags": [
                {**f, "about": a}
                for f, a in zip(_report_flags(rv.flags), rv.flag_about, strict=True)
            ],
            "status_unconfirmed": list(rv.status_unconfirmed),
            "put_in": {
                "suggestion": rv.suggestion,
                "files": list(rv.put_in),
                "related_files": list(rv.related_files),
            },
            "message": None
            if doc
            else "The letter on this receipt was not found in the records available to you.",
            **meta(run),
        }

    @r.post("/diarise")
    def diarise(body: ReceiptIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Touchpoint 1 — pre-fill the diary fields from the letter on the receipt, for the clerk
        to verify (ADR-0038). Read from the letter's own text (an OCR draft for a scan, marked);
        a field the text does not give stays empty. Nothing is saved."""
        action = "assist.diarise"
        run = rt(o, action)
        try:
            rctx = connector.receipt_context(body.computer_no, o.ctx.user_id)
        except ConnectorError:
            audit.record(o.request_id, o.ctx.user_id, action, "not_available")
            raise HTTPException(status_code=404, detail=RECEIPT_NOT_AVAILABLE) from None
        art = run.artefacts.get(rctx.attachment_uri or "")
        store = run.store_for(o.ctx)
        if art is not None:
            tags = DocumentAccessTags(
                doc_id=art[0].source_uri,
                department=art[0].department,
                section=art[0].section,
                classification=art[0].classification,
                file_no=art[0].file_no,
            )
            if not check(o.ctx.user_id, tags, store, run.policy, run.classification).allowed:
                audit.record(o.request_id, o.ctx.user_id, action, "not_available")
                raise HTTPException(status_code=404, detail=RECEIPT_NOT_AVAILABLE)
        got = run.letter_text(rctx.attachment_uri) if rctx.attachment_uri else None
        if got is None:
            audit.record(o.request_id, o.ctx.user_id, action, "no_answer", ids=(body.computer_no,))
            return {
                "request_id": o.request_id,
                "computer_no": body.computer_no,
                "prefill": None,
                "message": "The letter on this receipt has not been read yet; fill the diary "
                "details from the letter.",
                **meta(run),
            }
        text, from_ocr, conf = got
        p = prefill(text, run.departments, from_ocr=from_ocr, ocr_confidence=conf)
        audit.record(o.request_id, o.ctx.user_id, action, "ok", ids=(body.computer_no, *p.missing))
        return {
            "request_id": o.request_id,
            "computer_no": body.computer_no,
            "prefill": p.model_dump(mode="json"),
            "message": None,
            **meta(run),
        }

    @r.post("/brief")
    def brief(body: FileIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Touchpoint 13 — approval brief for a senior opening the file."""
        run = rt(o, "assist.brief")
        fctx = open_file(o, run, body.computer_no, "assist.brief")
        store = run.store_for(o.ctx)
        docs = list(run.stores.index._docs)  # noqa: SLF001 — reference store
        b = approval_brief(
            ctx=run.tool_context(o.ctx.user_id, store),
            file_no=fctx.file_no,
            subject=fctx.subject,
            movement=fctx.movement_trail,
            documents=docs,
            text_of=lambda c: run.texts.get(c, ""),
            tags_of={d.canonical_id: d.tags for d in docs},
            rules=run.rules,
            windows=run.windows(),
            departments=run.departments,
            awaiting_review=tuple(run.stores.awaiting.values()),
        )
        f = b.facts.facts if b.facts else None
        audit.record(
            o.request_id,
            o.ctx.user_id,
            "assist.brief",
            "ok" if b.draft_id else "no_answer",
            ids=(body.computer_no, *([b.draft_id] if b.draft_id else [])),
        )
        return {
            "request_id": o.request_id,
            "computer_no": body.computer_no,
            "file_no": fctx.file_no,
            "subject": fctx.subject,
            "draft_id": b.draft_id,
            "proposal": {
                "action": f.action.value if f else None,
                "post_level": f.post_level.value if f and f.post_level else None,
                "amount_rupees": f.amount_rupees if f else None,
                "proposed_authority": run.rules.label(f.proposed_authority)
                if f and f.proposed_authority
                else None,
                "proposal_date": f.proposal_date.isoformat() if f else None,
                "evidence": b.facts.evidence if b.facts else {},
                "not_stated": list(b.facts.missing) if b.facts else [],
            },
            "chain": list(b.chain.chain),
            "put_up": (
                {
                    "post": b.chain.notes[0].post,
                    "signed_at": b.chain.notes[0].signed_at.isoformat()
                    if b.chain.notes[0].signed_at
                    else None,
                    "source": b.chain.notes[0].source,
                }
                if b.chain.notes
                else None
            ),
            "governing": [
                {
                    "cited": g.cited,
                    "found": g.found,
                    "status": g.status.status if g.status else None,
                    "by": g.status.by if g.status else None,
                    "current_version": g.status.current_version if g.status else None,
                    "message": (g.status.message if g.status else None)
                    or (None if g.found else CITED_NOT_FOUND),
                }
                for g in b.governing
            ],
            "presend": _report(b.presend) if b.presend else None,
            "precedents": [
                {
                    "file_no": p.file_no,
                    "documents": [d.model_dump(mode="json") for d in p.documents],
                }
                for p in b.precedents
            ],
            "movement": list(b.movement),
            **meta(run),
        }

    @r.get("/notices")
    def notices(o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Touchpoint 4 — an incoming order changed an earlier one; these OPEN files of yours rely
        on the old order. Filtered per officer (plan §5.4); explicit supersession is applied
        directly, inferred ones wait in the review queue (plan §7.3)."""
        run = rt(o, "assist.notices")
        run.sync(connector)
        store = run.store_for(o.ctx)
        mine = notices_for(
            o.ctx.user_id,
            run.stores.notices,
            store=store,
            policy=run.policy,
            classification=run.classification,
        )

        def ref(cid: str) -> dict[str, Any]:
            d = run.doc(cid)
            return {
                "canonical_id": cid,
                "doc_type": d.doc_type if d else None,
                "subject": d.subject if d else None,
                "issue_date": d.issue_date.isoformat() if d and d.issue_date else None,
            }

        audit.record(
            o.request_id,
            o.ctx.user_id,
            "assist.notices",
            "ok" if mine else "no_answer",
            ids=tuple(x for n in mine for x in (n.new_doc, n.changed_doc)),
        )
        return {
            "request_id": o.request_id,
            "notices": [
                {
                    "new": ref(n.new_doc),
                    "changed": ref(n.changed_doc),
                    "change": n.change.value,
                    "files": [
                        {"file_no": a.file_no, "citing_doc": a.citing_doc} for a in n.affected
                    ],
                }
                for n in mine
            ],
            **meta(run),
        }

    @r.post("/highlights")
    def highlights(body: HighlightsIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Citation highlights on the notes shown for an open file (ADR-0015): where each cited
        order sits in the text and its state for this officer; only visible orders get an ID."""
        run = rt(o, "assist.highlights")
        fctx = open_file(o, run, body.computer_no, "assist.highlights")
        store = run.store_for(o.ctx)
        tags_of = {c: t for c in run.stores.graph.node_ids() if (t := run.tags(c))}
        as_of = body.as_of or run.as_of
        try:
            per_note = {
                n.note_id: highlight_citations(
                    n.text,
                    as_of,
                    default_dept=fctx.file_no.split("-")[0],
                    departments=run.departments,
                    user_id=o.ctx.user_id,
                    instruments=run.stores.instruments,
                    relations=list(run.stores.relations),
                    tags_of=tags_of,
                    store=store,
                    policy=run.policy,
                    classification=run.classification,
                    awaiting_review=tuple(run.stores.awaiting.values()),
                    own_file_no=fctx.file_no,
                )
                for n in body.notes
            }
        except ScopeError:
            audit.record(o.request_id, o.ctx.user_id, "assist.highlights", "denied")
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None
        ids = sorted({h.canonical_id for hs in per_note.values() for h in hs if h.canonical_id})
        audit.record(
            o.request_id, o.ctx.user_id, "assist.highlights", "ok", ids=(body.computer_no, *ids)
        )
        return {
            "request_id": o.request_id,
            "computer_no": body.computer_no,
            "as_of": as_of.isoformat(),
            "notes": [
                {
                    "note_id": nid,
                    "highlights": [
                        {
                            "start": h.start,
                            "end": h.end,
                            "raw": h.raw,
                            "kind": h.kind,
                            "state": h.state.value,
                            "canonical_id": h.canonical_id,
                            "file_no": h.file_no,
                            "flags": _report_flags(h.flags),
                        }
                        for h in hs
                    ],
                }
                for nid, hs in per_note.items()
            ],
            **meta(run),
        }

    def document(o: Officer, run: AssistRuntime, canonical_id: str, action: str) -> Any:
        """ADR-0014 rule 1: the record only if this officer may see it right now (L0 within scope
        + can_access re-check), with its stored source. Unknown, hidden, held in review, malformed
        and unstored all give the same 404."""
        doc, stored = None, None
        try:
            keys = lookup_keys(canonical_id) if re.fullmatch(CANONICAL_ID, canonical_id) else []
        except InvalidCanonicalIdError:
            keys = []
        ctx = run.tool_context(o.ctx.user_id, run.store_for(o.ctx))
        for k in keys:
            if (doc := visible_document(ctx, k)) is not None:
                break
        if doc is not None:
            stored = run.stored_source(doc.canonical_id, o.ctx.user_id, run.store_for(o.ctx))
        if doc is None or stored is None:
            audit.record(o.request_id, o.ctx.user_id, action, "not_available")
            raise HTTPException(status_code=404, detail=DOC_NOT_AVAILABLE)
        return doc, stored

    @r.get("/documents/{canonical_id}")
    def document_info(canonical_id: str, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """What the preview panel shows before loading the file (ADR-0014)."""
        run = rt(o, "assist.document.info")
        doc, stored = document(o, run, canonical_id, "assist.document.info")
        audit.record(
            o.request_id,
            o.ctx.user_id,
            "assist.document.info",
            "ok",
            ids=(doc.canonical_id, stored.version),
        )
        ctx = run.tool_context(o.ctx.user_id, run.store_for(o.ctx))
        standing, use_instead = standing_of(
            ctx, doc.canonical_id, doc.doc_type, *visible_facts(ctx, {doc.canonical_id})
        )
        return {
            "request_id": o.request_id,
            "canonical_id": doc.canonical_id,
            "doc_type": doc.doc_type,
            "subject": doc.subject,
            "issue_date": doc.issue_date.isoformat() if doc.issue_date else None,
            # ADR-0045: where the record stands today and how it came to be (versions kept)
            "standing": standing,
            "use_instead": use_instead,
            "history": history_of(run, doc.canonical_id),
            "version": stored.version,
            "media_type": stored.media_type,
            "previewable": stored.previewable,
            "filename": f"{doc.canonical_id}{extension(stored.media_type)}",
        }

    def history_of(run: AssistRuntime, cid: str) -> list[dict[str, Any]]:
        """The record's versions as they entered institutional memory, oldest first (no text)."""
        return [
            {
                "version": v.version.split(":")[1],
                "received_at": v.received_at.isoformat(),
                "event": v.event,
            }
            for v in run.stores.history.get(cid, [])
        ]

    @r.get("/files/{computer_no}/records")
    def file_records(computer_no: str, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """ADR-0045 — what of this file is in institutional memory (each record re-checked, with
        its standing and versions), and its papers still waiting: OCR review, or a reference that
        could not be resolved. Drafts are never here: they enter only when confirmed or issued."""
        action = "assist.file.records"
        run = rt(o, action)
        fctx = open_file(o, run, computer_no, action)
        store = run.store_for(o.ctx)
        ctx = run.tool_context(o.ctx.user_id, store)
        records: list[dict[str, Any]] = []
        for cid in dict.fromkeys(c for c, _ in run.stores.files.get(fctx.file_no, [])):
            doc = visible_document(ctx, cid)
            if doc is None:
                continue  # re-check: a paper of this file the officer may not see is not named
            standing, use_instead = standing_of(ctx, cid, doc.doc_type, *visible_facts(ctx, {cid}))
            hist = history_of(run, cid)
            records.append(
                {
                    "canonical_id": cid,
                    "doc_type": doc.doc_type,
                    "subject": doc.subject,
                    "issue_date": doc.issue_date.isoformat() if doc.issue_date else None,
                    "standing": standing,
                    "use_instead": use_instead,
                    "versions": len(hist),
                    "last_event": hist[-1]["event"] if hist else None,
                }
            )
        waiting: list[dict[str, Any]] = []
        for (uri, _), res in run.stores.results.items():
            art = run.artefacts.get(uri)
            if res.status is not IngestStatus.HELD or art is None or art[0].file_no != fctx.file_no:
                continue
            if any(w["source"] == uri for w in waiting):
                continue
            later = [r for (u, _), r in run.stores.results.items() if u == uri]
            if later and later[-1].status is IngestStatus.INDEXED:
                continue  # reviewed and indexed since
            waiting.append(
                {
                    "source": uri,
                    "filename": art[0].filename,
                    "waiting_for": sorted(
                        {WAITING_FOR.get(i.kind, "review") for i in res.review_items}
                    )
                    or ["review"],
                }
            )
        audit.record(
            o.request_id,
            o.ctx.user_id,
            action,
            "ok",
            ids=(computer_no, *(x["canonical_id"] for x in records)),
        )
        return {
            "request_id": o.request_id,
            "computer_no": computer_no,
            "file_no": fctx.file_no,
            "records": records,
            "waiting": [{k: v for k, v in w.items() if k != "source"} for w in waiting],
        }

    @r.get("/documents/{canonical_id}/context")
    def document_context(
        canonical_id: str,
        o: Annotated[Officer, Depends(officer)],
        quote: Annotated[str, Query(min_length=3, max_length=500)],
    ) -> dict[str, Any]:
        """The paragraph a citation's quote comes from, for the hover preview (ADR-0034). The
        record must be one this officer may see now; anything else is the same 404 as the
        document routes. Only that one paragraph is returned, never the whole text."""
        action = "assist.document.context"
        run = rt(o, action)
        store = run.store_for(o.ctx)
        ctx = run.tool_context(o.ctx.user_id, store)
        doc = None
        base = canonical_id.split("#")[0]
        try:
            keys = lookup_keys(base) if re.fullmatch(CANONICAL_ID, base) else []
        except InvalidCanonicalIdError:
            keys = []
        for k in keys:
            if (doc := visible_document(ctx, k)) is not None:
                break
        if doc is None:
            audit.record(o.request_id, o.ctx.user_id, action, "not_available")
            raise HTTPException(status_code=404, detail=DOC_NOT_AVAILABLE)
        text = run.evidence_texts(o.ctx.user_id, store).get(doc.canonical_id) or ""
        found = context_of(text, quote)
        audit.record(o.request_id, o.ctx.user_id, action, "ok", ids=(doc.canonical_id,))
        return {
            "request_id": o.request_id,
            "canonical_id": doc.canonical_id,
            "reference": reference_text(
                canonical_id if "#" in canonical_id else doc.canonical_id, doc.issue_date
            ),
            "subject": doc.subject,
            "paragraph": found.paragraph if found else None,
            "highlight": list(found.highlight) if found and found.highlight else None,
        }

    def serve(canonical_id: str, o: Officer, action: str, disposition: str) -> Response:
        run = rt(o, action)
        doc, stored = document(o, run, canonical_id, action)
        if disposition == "inline" and not stored.previewable:
            audit.record(
                o.request_id,
                o.ctx.user_id,
                action,
                "not_previewable",
                ids=(doc.canonical_id, stored.version),
            )
            raise HTTPException(status_code=415, detail="This file type cannot be shown here.")
        audit.record(
            o.request_id, o.ctx.user_id, action, "ok", ids=(doc.canonical_id, stored.version)
        )
        name = f"{doc.canonical_id}{extension(stored.media_type)}"
        return Response(
            content=stored.data,
            media_type=stored.media_type,
            headers={
                "Content-Disposition": f'{disposition}; filename="{name}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "X-Document-Version": stored.version,
            },
        )

    @r.get("/documents/{canonical_id}/preview")
    def document_preview(canonical_id: str, o: Annotated[Officer, Depends(officer)]) -> Response:
        """ADR-0014: the exact stored file, inline (PDF and images only)."""
        return serve(canonical_id, o, "assist.document.preview", "inline")

    @r.get("/documents/{canonical_id}/download")
    def document_download(canonical_id: str, o: Annotated[Officer, Depends(officer)]) -> Response:
        """ADR-0014: the exact stored file, as a download."""
        return serve(canonical_id, o, "assist.document.download", "attachment")

    # ---- OCR review (plan §4.2, §9.1 checkpoint 5; CLAUDE.md §8) --------------------------------

    def ocr_item(o: Officer, run: AssistRuntime, item_id: str, action: str) -> ReviewItem:
        """A pending OCR review item the officer may see (same check as the file itself).
        Unknown, decided, hidden and malformed IDs all give the same 404."""
        item = next(
            (
                i
                for i in run.stores.queue.pending(ReviewKind.LOW_CONFIDENCE_EXTRACTION)
                if i.item_id == item_id
            ),
            None,
        )
        tags = run.stores.awaiting.get(item.subject) if item else None
        if (
            item is None
            or tags is None
            or item.subject not in run.artefacts
            or not check(
                o.ctx.user_id, tags, run.store_for(o.ctx), run.policy, run.classification
            ).allowed
        ):
            audit.record(o.request_id, o.ctx.user_id, action, "not_available")
            raise HTTPException(status_code=404, detail=REVIEW_ITEM_NOT_AVAILABLE)
        return item

    def ocr_summary(run: AssistRuntime, item: ReviewItem) -> dict[str, Any]:
        a, _ = run.artefacts[item.subject]
        draft = run.stores.ocr_drafts.get(item.version)
        return {
            "item_id": item.item_id,
            "created_at": item.created_at.isoformat(),
            "reason": item.reason,
            "filename": a.filename,
            "department": a.department,
            "section": a.section,
            "classification": a.classification,
            "file_no": a.file_no,
            "engine": draft.engine if draft else None,
            "pages": [
                {"page": pg.page, "confidence": pg.confidence, "languages": list(pg.languages)}
                for pg in (draft.pages if draft else ())
            ],
        }

    @r.get("/review/ocr")
    def ocr_queue(o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Scans waiting for a reviewer that this officer may see. Others are simply absent; the
        list never hints at them (CLAUDE.md §4.7)."""
        run = rt(o, "assist.review.list")
        store = run.store_for(o.ctx)
        items = [
            i
            for i in run.stores.queue.pending(ReviewKind.LOW_CONFIDENCE_EXTRACTION)
            if i.subject in run.artefacts
            and (t := run.stores.awaiting.get(i.subject)) is not None
            and check(o.ctx.user_id, t, store, run.policy, run.classification).allowed
        ]
        audit.record(
            o.request_id,
            o.ctx.user_id,
            "assist.review.list",
            "ok",
            ids=tuple(i.item_id for i in items),
        )
        return {"request_id": o.request_id, "items": [ocr_summary(run, i) for i in items]}

    @r.get("/review/ocr/{item_id}")
    def ocr_detail(item_id: str, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        run = rt(o, "assist.review.view")
        item = ocr_item(o, run, item_id, "assist.review.view")
        a, _ = run.artefacts[item.subject]
        draft = run.stores.ocr_drafts.get(item.version)
        audit.record(o.request_id, o.ctx.user_id, "assist.review.view", "ok", ids=(item.item_id,))
        mt = media_type(a.data, a.filename)
        return {
            "request_id": o.request_id,
            **ocr_summary(run, item),
            "media_type": mt,
            "previewable": mt in PREVIEWABLE,
            "draft_text": review_text(a.data, a.filename, draft) if draft else "",
            "has_draft": draft is not None,
        }

    @r.get("/review/ocr/{item_id}/scan")
    def ocr_scan(item_id: str, o: Annotated[Officer, Depends(officer)]) -> Response:
        """The scan itself, for checking the OCR text against it (ADR-0014 rule 4: served only to an
        officer who may open the file)."""
        run = rt(o, "assist.review.scan")
        item = ocr_item(o, run, item_id, "assist.review.scan")
        a, _ = run.artefacts[item.subject]
        mt = media_type(a.data, a.filename)
        if mt not in PREVIEWABLE:
            raise HTTPException(status_code=415, detail="This file type cannot be shown here.")
        audit.record(o.request_id, o.ctx.user_id, "assist.review.scan", "ok", ids=(item.item_id,))
        return Response(
            content=a.data,
            media_type=mt,
            headers={
                "Content-Disposition": f'inline; filename="{item.item_id}{extension(mt)}"',
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @r.post("/review/ocr/{item_id}/confirm")
    def ocr_confirm(
        item_id: str, body: OcrReviewIn, o: Annotated[Officer, Depends(officer)]
    ) -> dict[str, Any]:
        """Reviewer confirms the OCR text, or confirms a corrected text. The file then runs through
        the pipeline again; it is indexed only if every other check passes."""
        run = rt(o, "assist.review.confirm")
        item = ocr_item(o, run, item_id, "assist.review.confirm")
        a, _ = run.artefacts[item.subject]
        draft = run.stores.ocr_drafts.get(item.version)
        unchanged = draft is not None and body.corrected_text == review_text(
            a.data, a.filename, draft
        )
        try:
            res = run.review_ocr(
                item,
                reviewer=o.ctx.user_id,
                confirm=True,
                reason=body.reason,
                at=dt.datetime.now(dt.UTC),
                corrected_text=None if unchanged else body.corrected_text,
            )
        except ConfirmError as exc:
            audit.record(
                o.request_id, o.ctx.user_id, "assist.review.confirm", "refused", ids=(item_id,)
            )
            raise HTTPException(status_code=409, detail=str(exc)) from None
        assert res is not None
        audit.record(
            o.request_id,
            o.ctx.user_id,
            "assist.review.confirm",
            res.status.value,
            ids=(item_id, *((res.canonical_id,) if res.canonical_id else ())),
        )
        return {
            "request_id": o.request_id,
            "status": res.status.value,
            "canonical_id": res.canonical_id if res.status.value == "indexed" else None,
            "corrected": not unchanged and body.corrected_text is not None,
            "still_held_for": [
                {"kind": i.kind.value, "reason": i.reason}
                for i in res.review_items
                if res.status.value == "held"
            ],
        }

    @r.post("/review/ocr/{item_id}/reject")
    def ocr_reject(
        item_id: str, body: OcrReviewIn, o: Annotated[Officer, Depends(officer)]
    ) -> dict[str, Any]:
        """Reviewer rejects the OCR text (unreadable / needs a re-scan). The file stays held."""
        run = rt(o, "assist.review.reject")
        item = ocr_item(o, run, item_id, "assist.review.reject")
        run.review_ocr(
            item,
            reviewer=o.ctx.user_id,
            confirm=False,
            reason=body.reason,
            at=dt.datetime.now(dt.UTC),
        )
        audit.record(o.request_id, o.ctx.user_id, "assist.review.reject", "ok", ids=(item_id,))
        return {"request_id": o.request_id, "status": "rejected"}

    @r.get("/digest")
    def digest(
        o: Annotated[Officer, Depends(officer)],
        days: Annotated[int, Query(ge=1, le=90)] = 7,
    ) -> dict[str, Any]:
        """The officer's digest (ADR-0034): files waiting with them (oldest first, overdue
        marked) and orders cited in their open files that are no longer in force — those whose
        change took effect in the last `days` days marked new. Only files the officer can open
        now and orders they may see; nothing about anyone else's files."""
        action = "assist.digest"
        run = rt(o, action)
        store = run.store_for(o.ctx)
        ctx = run.tool_context(o.ctx.user_id, store)
        today = run.as_of
        waiting: list[dict[str, Any]] = []
        changed: list[dict[str, Any]] = []
        for f in connector.officer_files(o.ctx.user_id):
            try:
                fctx = open_file(o, run, f.computer_no, action)
            except HTTPException:
                continue  # out of reach or not cleared now: left out, without a word
            if f.with_officer:
                received = f.since.date() if f.since else None
                waiting.append(
                    {
                        "computer_no": f.computer_no,
                        "file_no": f.file_no,
                        "subject": f.subject,
                        "received_on": received.isoformat() if received else None,
                        "days_waiting": (today - received).days if received else None,
                        "due_on": f.due_on.isoformat() if f.due_on else None,
                        "overdue": bool(f.due_on and f.due_on < today),
                        "priority": f.priority,
                        "sent_back": f.sent_back,
                    }
                )
            papers = [
                cid
                for cid, _ in run.stores.files.get(fctx.file_no, [])
                if visible_document(ctx, cid) is not None
            ]
            cited = expand(
                o.ctx.user_id,
                papers,
                graph=ctx.graph,
                kinds=frozenset({EdgeKind.CITES, EdgeKind.REFERENCES}),
                direction=Direction.OUT,
                max_hops=1,
                store=store,
                policy=run.policy,
                classification=run.classification,
            )
            for cid in dict.fromkeys(h.canonical_id for h in cited.hits):
                st = check_document_status(ctx, cid)
                if not (st.available and st.status in ("superseded", "repealed", "expired")):
                    continue
                d = st.documents[0] if st.documents else None
                changed.append(
                    {
                        "computer_no": f.computer_no,
                        "file_no": f.file_no,
                        "cited": cid,
                        "reference": reference_text(cid, d.issue_date if d else None),
                        "status": st.status,
                        "by": st.by,
                        "by_reference": reference_text(st.by) if st.by else None,
                        "since": st.since.isoformat() if st.since else None,
                        "new": bool(st.since and (today - st.since).days < days),
                    }
                )
        waiting.sort(key=lambda w: (not w["overdue"], -(w["days_waiting"] or 0)))
        changed.sort(key=lambda c: (not c["new"], c["since"] or ""), reverse=False)
        audit.record(
            o.request_id,
            o.ctx.user_id,
            action,
            "ok",
            ids=tuple(
                dict.fromkeys(
                    [*(w["computer_no"] for w in waiting), *(c["cited"] for c in changed)]
                )
            ),
        )
        return {
            "request_id": o.request_id,
            "as_of": today.isoformat(),
            "window_days": days,
            "waiting": waiting,
            "changed_orders": changed,
            **meta(run),
        }

    def pad_refused(o: Officer, action: str) -> NoReturn:
        """The pad does not exist for this officer (same 404 as any unknown route). The attempt
        is recorded: the screens never offer the pad to them, so a call means someone went
        around the screens (ADR-0036, alert `pad_probe`)."""
        audit.record(o.request_id, o.ctx.user_id, action, "denied")
        raise HTTPException(status_code=404, detail="Not Found")

    @r.post("/monitor/alerts/{alert_id}/review")
    def review_alert(
        alert_id: str,
        body: AlertReviewIn,
        o: Annotated[Officer, Depends(officer)],
    ) -> dict[str, Any]:
        """A monitoring officer marks an alert reviewed (nothing further) or escalated (for the
        department's own procedure). Fixed codes only; the assistant does nothing else with it —
        no message, no change to the officer's access (ADR-0036)."""
        if monitor is None or o.ctx.user_id not in monitoring_users:
            pad_refused(o, "assist.monitor.review")
        if not re.fullmatch(r"AL-[0-9a-f]{16}", alert_id):
            raise HTTPException(status_code=422, detail="Not an alert ID.")
        rec = HumanAction(
            action_id=uuid.uuid4().hex[:16],
            ts=dt.datetime.now(dt.UTC),
            user_id=o.ctx.user_id,
            query_id=alert_id,
            target_kind=TargetKind.ALERT,
            action=body.action,
            reason=body.reason,
        )
        feedback_log.write(rec)
        audit.record(o.request_id, o.ctx.user_id, "assist.monitor.review", "ok", (alert_id,))
        return {"request_id": o.request_id, "alert_id": alert_id, "status": body.action.value}

    @r.get("/monitor")
    def monitor_view(
        o: Annotated[Officer, Depends(officer)],
        days: Annotated[int, Query(ge=1, le=90)] = 14,
    ) -> dict[str, Any]:
        """The monitoring officer's pad (ADR-0035): overview, activity log, most frequent
        questions, each officer's activity, unanswered questions, slowest answers, feedback,
        cache and start-up. Only for monitoring officers (sandbox.yaml `monitoring`,
        C2_MONITORING_USERS); for everyone else it does not exist (same 404). A question's words
        are shown only if this officer is cleared at least as high as the one who asked."""
        if monitor is None or o.ctx.user_id not in monitoring_users:
            pad_refused(o, "assist.monitor")
        run = rt(o, "assist.monitor")
        since = dt.datetime.now(dt.UTC).date() - dt.timedelta(days=days - 1)
        data = monitor(since, run.classification.rank_of(o.ctx.clearance))
        audit.record(o.request_id, o.ctx.user_id, "assist.monitor", "ok")
        return {"request_id": o.request_id, "days": days, **data.model_dump(mode="json")}

    @r.get("/me/roles")
    def my_roles(o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """What the screens should offer this officer (only their own roles)."""
        return {"monitoring": o.ctx.user_id in monitoring_users}

    @r.get("/usage")
    def usage_view(
        o: Annotated[Officer, Depends(officer)],
        days: Annotated[int, Query(ge=1, le=90)] = 14,
    ) -> dict[str, Any]:
        """Usage dashboard (ADR-0034): questions per day, time per answer, cache hits, no-answer
        rate, which search step answered, feedback counts and the last start's build time.
        Aggregates only — no question, user, document or file. Only the monitoring officers
        (C2_MONITORING_USERS) see it; for everyone else it does not exist (same 404)."""
        if usage is None or o.ctx.user_id not in monitoring_users:
            pad_refused(o, "assist.usage")
        since = dt.datetime.now(dt.UTC).date() - dt.timedelta(days=days - 1)
        u = usage(since)
        audit.record(o.request_id, o.ctx.user_id, "assist.usage", "ok")
        return {"request_id": o.request_id, **u.model_dump(mode="json")}

    @r.post("/feedback")
    def feedback(body: FeedbackIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Record what the officer thought of an output (plan §9.2; ADR-0031): evaluation data
        only — nothing reads it back to change answers. The target must be one this officer can
        reach right now: their own session's turn, a record they may see, a file they can open.
        Anything else — unknown, someone else's, hidden — gets the same 404 (ADR-0016)."""
        action = "assist.feedback"
        allowed = _FEEDBACK_ACTIONS.get(body.kind)
        if allowed is None or body.action not in allowed:
            raise HTTPException(status_code=422, detail="This action does not apply here.")
        targets: tuple[str, ...]
        if body.kind is TargetKind.ANSWER:
            try:
                turns = sessions.turns(o.ctx.user_id, body.session_id or "")
            except SessionError:
                turns = ()
            if not body.session_id or not any(t.request_id == body.request_id for t in turns):
                audit.record(o.request_id, o.ctx.user_id, action, "not_available")
                raise HTTPException(status_code=404, detail=NOT_AVAILABLE)
            targets = (body.session_id,)
        elif body.kind is TargetKind.STATEMENT:
            run = rt(o, action)
            ctx = run.tool_context(o.ctx.user_id, run.store_for(o.ctx))
            doc = None
            base = (body.canonical_id or "").split("#")[0]  # a clause → its document
            try:
                keys = lookup_keys(base) if re.fullmatch(CANONICAL_ID, base) else []
            except InvalidCanonicalIdError:
                keys = []
            for k in keys:
                if (doc := visible_document(ctx, k)) is not None:
                    break
            if doc is None:
                audit.record(o.request_id, o.ctx.user_id, action, "not_available")
                raise HTTPException(status_code=404, detail=DOC_NOT_AVAILABLE)
            targets = (doc.canonical_id,)
        else:  # a conflict flag on a file the officer can open
            if not body.computer_no or not body.flag_type:
                raise HTTPException(status_code=422, detail="A flag needs its file and type.")
            open_file(o, rt(o, action), body.computer_no, action)
            base = (body.canonical_id or "").split("#")[0]
            # the ID as the flag (and the officer's own note) cites it
            cited = (base,) if re.fullmatch(CANONICAL_ID, base) else ()
            targets = (body.computer_no, *cited)
        rec = HumanAction(
            action_id=uuid.uuid4().hex[:16],
            ts=dt.datetime.now(dt.UTC),
            user_id=o.ctx.user_id,
            query_id=body.request_id,
            target_kind=body.kind,
            target_ids=targets,
            action=body.action,
            reason=body.reason,
            flag_type=body.flag_type if body.kind is TargetKind.CONFLICT_FLAG else None,
        )
        feedback_log.write(rec)
        audit.record(
            o.request_id,
            o.ctx.user_id,
            action,
            "ok",
            ids=(body.request_id, *targets),
            detail=f"{body.kind.value}:{body.action.value}",
        )
        return {"request_id": o.request_id, "recorded": True}

    @r.get("/draft/formats")
    def draft_format_list(o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """The draft formats (ADR-0044): mock structures from the corpus, [To confirm]."""
        if draft_formats is None:
            raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
        return {"request_id": o.request_id, **draft_formats.model_dump(mode="json")}

    @r.post("/draft/prepare")
    def draft_prepare(
        body: DraftPrepareIn, o: Annotated[Officer, Depends(officer)]
    ) -> dict[str, Any]:
        """Prepare a draft in a chosen format from the officer's inputs and the records within
        their scope (ADR-0044): Read the following through the supersession chain, close matches
        by the ladder (hybrid search + graph) with their standing and relations, the pre-send
        check on the draft itself, and — on request — checked wording from the model. A preview:
        nothing reaches the file until the officer clicks Save."""
        action = "assist.draft.prepare"
        fmt = draft_formats.get(body.format_id) if draft_formats is not None else None
        if fmt is None:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE)
        run = rt(o, action)
        inputs = body.inputs
        new_matter = body.computer_no is None
        if new_matter and len(inputs.subject.strip()) < 10:
            raise HTTPException(
                status_code=422,
                detail="Give the subject of the new matter (at least 10 characters).",
            )
        fctx = None if new_matter else open_file(o, run, body.computer_no or "", action)
        store = run.store_for(o.ctx)
        ctx = run.tool_context(o.ctx.user_id, store)
        if fctx is not None and not inputs.subject.strip():
            inputs = inputs.model_copy(update={"subject": fctx.subject})
        file_no = fctx.file_no if fctx is not None else ""
        if fctx is not None:
            note_id, text, earlier = latest_note(o, run, fctx, store)
        else:
            note_id, text, earlier = None, "", ""
        # the officer's own words: references they typed ("G.O.Ms.No.88 …") and the action they
        # propose are read by the same reader as a note, so a new matter has orders too
        own_text = "\n".join(
            x for x in (inputs.subject, inputs.request, inputs.facts, inputs.proposal) if x.strip()
        )
        own_meta = DocumentMetadata(
            doc_type=DocType.NOTING_DRAFT,
            canonical_id=None,
            raw_reference=None,
            instrument=None,
            issue_date=ctx.as_of,
            department=fctx.department if fctx is not None else o.ctx.department,
            subject=inputs.subject.strip() or None,
            references=cited_references(own_text, run.departments, o.ctx.department),
        )
        meta_ = extract_metadata(text, run.departments) if note_id else None
        facts = (
            extract_proposal_facts(text, meta_, run.rules, note_id) if note_id and meta_ else None
        )
        own_facts = extract_proposal_facts(own_text, own_meta, run.rules, "draft:new")
        act = (facts.facts.action if facts and facts.facts else None) or (
            own_facts.facts.action if own_facts.facts else None
        )
        governing, left = governing_orders(ctx, meta_, act)
        typed, left_typed = governing_orders(ctx, own_meta, None)
        added, left_added = read_items_for(ctx, body.add_references)
        read_list = merge_read(governing, typed, added, drop=body.drop_references)
        left_out = tuple({x.cited: x for x in (*left, *left_typed, *left_added)}.values())
        points: tuple[Any, ...] = ()
        precedents: tuple[Any, ...] = ()
        fc = None
        if fmt.kind == "note":

            def file_of_(cid: str) -> str | None:
                t = run.tags(cid)
                return t.file_no if t else None

            links = suggest_links(ctx, inputs.subject, file_no, file_of_)
            fc = first_cut_note(
                ctx=ctx,
                file_no=file_no,
                subject=inputs.subject,
                draft_note=note_id,
                meta=meta_,
                action=act,
                flags=(),
                precedents=[(lk.file_no, d.canonical_id) for lk in links for d in lk.documents],
                text_of=lambda c: run.texts.get(c, ""),
                windows=[
                    w
                    for w in run.windows()
                    if (t := run.tags(w.source.split("#", 1)[0])) is not None
                    and check(o.ctx.user_id, t, store, run.policy, run.classification).allowed
                ],
            )
            points, precedents = fc.points, fc.precedents
        names = department_names()

        def label(cid: str, when: dt.date | None) -> str:
            """As an order cites it: a memo by the number printed on it (its own header line),
            so the citation can be resolved back; anything else by `reference_text`."""
            base = cid.split("#", 1)[0]
            if when is None and (doc := visible_document(ctx, base)) is not None:
                when = doc.issue_date
            head = "\n".join(run.texts.get(base, "").splitlines()[:6])
            own = _OWN_NUMBER.search(head) if visible_document(ctx, base) else None
            if own and "#" not in cid:
                text = reference_text(cid, when, names)
                rest = text.split(", ", 1)[1] if ", " in text else ""
                return f"{own.group(1)}, {rest}" if rest else own.group(1)
            return reference_text(cid, when, names)

        dept_code = fctx.department if fctx is not None else o.ctx.department
        dept = names.get(dept_code, dept_code)
        first = compose(
            fmt,
            inputs,
            department=dept,
            read_list=read_list,
            points=points,
            precedents=precedents,
            label=label,
        )
        # the pre-send check on the draft itself (what the officer wrote + what it reads)
        # read as the draft it is: its own Read list plus every order cited in its text (an
        # unnumbered draft is not recognised as an order or a note by the document reader)
        read_meta = extract_metadata(first.text, run.departments)
        draft_meta = own_meta.model_copy(
            update={
                "references": read_meta.references
                + cited_references(first.text, run.departments, dept_code)
            }
        )
        # what the draft itself proposes is checked; quoted record parts (earlier decisions,
        # provisions) are evidence, and an approver named in an old decision is not this proposal's
        checked = "\n".join(p.text for p in first.parts if p.origin != "record")
        rep = run_presend(
            o, run, store, f"draft:{body.computer_no or 'new'}", checked, earlier, draft_meta
        )
        flags = tuple(rep.flags)
        prepared = compose(
            fmt,
            inputs,
            department=dept,
            read_list=read_list,
            points=points,
            precedents=precedents,
            flags=flags,
            left_out=left_out,
            label=label,
        )

        def file_of(cid: str) -> str | None:
            t = run.tags(cid)
            return t.file_no if t else None

        def paper_label(cid: str) -> str:
            """An order as it is cited; any other paper as "Noting — File …" (never a raw ID).
            Only called for records the graph walk already re-checked for this officer."""
            text = label(cid, None)
            if text != cid.split("#", 1)[0]:
                return text
            doc = visible_document(ctx, cid)
            where = file_of(cid)
            kind = doc.doc_type if doc else "Paper"
            return f"{kind} — File {where}" if where else kind

        matches = close_matches(
            ctx,
            " ".join(x for x in (inputs.subject, inputs.proposal, inputs.facts) if x.strip()),
            read_ids=[i.canonical_id for i in read_list],
            flags=flags,
            file_of=file_of,
        )
        # a new matter: earlier files on the same subject the officer can open, to tick as Previous
        # References when the file is created (touchpoint 5's engine; the officer chooses)
        related_files: list[dict[str, Any]] = []
        if new_matter:
            for s_ in suggest_links(ctx, inputs.subject, "", file_of, limit=8):
                cno = connector.file_computer_no(s_.file_no, o.ctx.user_id)
                if cno is not None:
                    related_files.append({"file_no": s_.file_no, "computer_no": cno})
            related_files = related_files[:5]
        suggested: dict[str, Any] | None = None
        if body.suggest:
            if fmt.kind == "note" and fc is not None:
                note = draft_note(fc.model_copy(update={"flags": flags}), inputs.subject, run.llm)
                suggested = {
                    "lines": [
                        {"text": ln.text, "refs": list(ln.refs), "heading": sec.heading}
                        for sec in note.sections
                        for ln in sec.lines
                    ],
                    "removed": note.removed,
                    "engine": note.engine,
                    "fallback": False,
                    "reason": note.reason,
                }
            else:
                sw = suggest_wording(inputs, read_list, lambda c: run.texts.get(c, ""), run.llm)
                suggested = {
                    "lines": [
                        {"text": t, "refs": list(refs), "heading": None} for t, refs in sw.lines
                    ],
                    "removed": sw.removed,
                    "engine": sw.engine,
                    "fallback": sw.fallback,
                    "reason": sw.reason,
                }
        audit.record(  # IDs only: never the officer's text or the draft
            o.request_id,
            o.ctx.user_id,
            action,
            "ok",
            ids=(
                *([body.computer_no] if body.computer_no else []),
                *prepared.citations,
                *(m.canonical_id for m in matches.documents),
            ),
            detail=fmt.id,
        )
        return {
            "request_id": o.request_id,
            "computer_no": body.computer_no,
            "format": fmt.model_dump(mode="json"),
            "draft": prepared.model_dump(mode="json"),
            "read_list": [
                {**i.model_dump(mode="json"), "label": label(i.canonical_id, i.issue_date)}
                for i in read_list
            ],
            "left_out": [x.model_dump(mode="json") for x in left_out],
            "checks": {
                **{k: v for k, v in _report(rep).items() if k != "note_id"},
                # a draft has no note number or date yet by design: not a gap in it
                "fact_gaps": [g for g in rep.fact_gaps if g != "note identity/date/department"],
            },
            "matches": {
                "ladder": matches.ladder,
                # plan §14.4: a store that failed is said (L3: relations not checked)
                "unavailable": list(matches.unavailable),
                "documents": [
                    {
                        **m.model_dump(mode="json"),
                        "relations": [
                            {**x.model_dump(mode="json"), "other_label": paper_label(x.other)}
                            for x in m.relations
                        ],
                        "label": label(m.canonical_id, m.issue_date)
                        if m.standing != "not_an_order"
                        else f"{m.doc_type} — File {m.file_no}"
                        if m.file_no
                        else m.doc_type,
                    }
                    for m in matches.documents
                ],
            },
            "suggested": suggested,
            "related_files": related_files,
            **meta(run),
        }

    @r.post("/draft")
    def draft(body: DraftIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Insert as Yellow Note / Create DFA draft / Suggest reference — a DRAFT, on click."""
        open_file(o, rt(o, "draft.create"), body.computer_no, "draft.create")
        try:
            receipt = connector.create_draft(
                DraftRequest(
                    kind=body.kind,
                    computer_no=body.computer_no,
                    requested_by=o.ctx.user_id,
                    officer_clicked=True,  # this endpoint IS the officer's click
                    body=body.body,
                    citations=body.citations,
                    request_id=body.request_id,
                )
            )
        except ConnectorError:
            audit.record(o.request_id, o.ctx.user_id, "draft.create", "not_available")
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None
        audit.record(
            o.request_id,
            o.ctx.user_id,
            "draft.create",
            "ok",
            ids=(body.computer_no, receipt.draft_id, body.request_id),
            detail=body.kind.value,
        )
        saved_drafts.discard(o.ctx.user_id, body.computer_no)  # it is on the file now (ADR-0046)
        return {"request_id": o.request_id, **receipt.model_dump(mode="json")}

    # ---- draft recovery (ADR-0046): the workspace, kept by the server as the officer works ----

    def workspace_target(o: Officer, computer_no: str | None, action: str) -> str:
        """A file's workspace only while the officer can still open the file (same 404 as every
        file route); "new" for a matter with no file yet."""
        run = rt(o, action)  # the per-officer limit applies to every save
        if computer_no is None:
            return NEW_MATTER
        open_file(o, run, computer_no, action)
        return computer_no

    @r.get("/draft/workspace")
    def get_workspace(
        o: Annotated[Officer, Depends(officer)],
        computer_no: Annotated[str | None, Query(pattern=r"^[A-Za-z0-9._-]{1,64}$")] = None,
    ) -> dict[str, Any]:
        """Where the officer left this draft, if anywhere (re-checked access; their own only)."""
        action = "assist.draft.workspace.restore"
        target = workspace_target(o, computer_no, action)
        saved = saved_drafts.get(o.ctx.user_id, target)
        if saved is not None:
            audit.record(o.request_id, o.ctx.user_id, action, "ok", ids=(target,))
        return {
            "request_id": o.request_id,
            "workspace": saved.workspace.model_dump(mode="json") if saved else None,
            "saved_at": saved.saved_at.isoformat() if saved else None,
        }

    @r.post("/draft/workspace")
    def put_workspace(body: WorkspaceIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Autosave (a moment after each change). Not audited per save: it is the officer's own
        scratch, like typing; restoring and discarding are audited."""
        target = workspace_target(o, body.computer_no, "assist.draft.workspace.save")
        saved = saved_drafts.put(o.ctx.user_id, target, body.workspace, dt.datetime.now(dt.UTC))
        return {"request_id": o.request_id, "saved_at": saved.saved_at.isoformat()}

    @r.post("/draft/workspace/discard")
    def discard_workspace(
        body: WorkspaceTargetIn, o: Annotated[Officer, Depends(officer)]
    ) -> dict[str, Any]:
        """Start over: the saved workspace is removed (the officer's click)."""
        action = "assist.draft.workspace.discard"
        target = workspace_target(o, body.computer_no, action)
        gone = saved_drafts.discard(o.ctx.user_id, target)
        audit.record(o.request_id, o.ctx.user_id, action, "ok" if gone else "none", ids=(target,))
        return {"request_id": o.request_id, "discarded": gone}

    return r


def _report_flags(flags: tuple[ConflictFlag, ...]) -> list[dict[str, Any]]:
    return [
        {
            "type": f.type.value,
            "cited": f.cited,
            "evidence_ids": list(f.evidence_ids),
            "explanation": f.explanation,
            "certain": f.certain,
            "review_state": f.review_state,
        }
        for f in flags
    ]


def _report(rep: PreSendReport) -> dict[str, Any]:
    return {
        "note_id": rep.note_id,
        "outcome": rep.outcome.value,
        "flags": _report_flags(rep.flags),
        "status_unconfirmed": list(rep.status_unconfirmed),
        "awaiting_review": list(rep.awaiting_review),
        "fact_gaps": list(rep.fact_gaps),
        "authority_message": rep.authority.message if rep.authority else None,
    }
