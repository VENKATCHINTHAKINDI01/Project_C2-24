"""Assist API — the C2-24 calls the e-Office screens make (plan §11.3 'Context in / Results out',
§11.5 touchpoints 10, 11, 15; drafts out).

- Identity comes from an injected `identify(request)` (sandbox: simulated sign-in; GCP: IAP).
  No identity, or one the connector does not know → 401 with a neutral message.
- Every call re-reads the officer's grants from the connector into a fresh access store.
- "Not available" is the same for unknown and unreachable files (plan §5.4).
- Write-back is limited to drafts, created only on the officer's click (CLAUDE.md §2.4).
- Every call is audited with IDs only — never question text or document text (plan §10.4).
"""

import datetime as dt
import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.agents.intents import IntentSlots
from app.agents.runtime import AssistRuntime
from app.agents.tools import ToolName, ToolResult, call_tool
from app.audit.log import AuditLog
from app.auth.policy import check
from app.conflict.presend import PreSendReport, presend_check
from app.connectors.eoffice import (
    ConnectorError,
    DraftKind,
    DraftRequest,
    EOfficeConnector,
    OfficerContext,
)
from app.ingestion.metadata import extract_metadata
from app.retrieval.references import LookupStatus, lookup_reference

NOT_SIGNED_IN = "Not signed in."
NOT_AVAILABLE = "File not available."
NO_MATCH = "No matching order was found in the records available to you."
NOT_CONFIGURED = "The assistant is not configured yet."


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SearchIn(_In):
    query: str = Field(min_length=1, max_length=500)


class ReferenceIn(_In):
    text: str = Field(min_length=1, max_length=300)


class PresendIn(_In):
    computer_no: str = Field(pattern=r"^\d{4,12}$")
    text: str | None = Field(default=None, max_length=20000)  # the officer's draft, if edited


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


def build_assist_router(
    *,
    connector: EOfficeConnector,
    runtime: Callable[[], AssistRuntime | None],
    audit: AuditLog,
    identify: Callable[[Request], str | None],
) -> APIRouter:
    r = APIRouter(prefix="/assist", tags=["assist"])

    def officer(request: Request) -> Officer:
        rid = uuid.uuid4().hex[:16]
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
        got = runtime()
        if got is None:
            audit.record(o.request_id, o.ctx.user_id, action, "error", detail="not configured")
            raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
        return got

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

    @r.post("/reference")
    def reference(body: ReferenceIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Touchpoint 10 — the current version of an order the officer cites."""
        run = rt(o, "assist.reference")
        store = run.store_for(o.ctx)
        look = lookup_reference(
            o.ctx.user_id,
            body.text,
            departments=run.departments,
            retriever=run.stores.index,
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
            run.tool_context(o.ctx.user_id, store),
            ToolName.CHECK_DOCUMENT_STATUS,
            {"canonical_ids": (look.canonical_id,)},
        )
        audit.record(
            o.request_id, o.ctx.user_id, "assist.reference", "ok", ids=(look.canonical_id,)
        )
        return {
            **base,
            "found": res.available,
            "documents": [d.model_dump() for d in docs_out(run, res)],
            "status": res.status,
            "by": res.by,
            "current_version": res.current_version,
            "message": res.message,
        }

    @r.post("/presend")
    def presend(body: PresendIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Touchpoint 11 — the pre-send check on the note about to be sent."""
        run = rt(o, "assist.presend")
        try:
            fctx = connector.file_context(body.computer_no, o.ctx.user_id)
        except ConnectorError:
            audit.record(o.request_id, o.ctx.user_id, "assist.presend", "not_available")
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None
        store = run.store_for(o.ctx)

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
        note_id = max(notes)[1] if notes else f"draft:{body.computer_no}"
        text = body.text if body.text is not None else run.texts.get(note_id, "")
        if not text.strip():
            audit.record(o.request_id, o.ctx.user_id, "assist.presend", "no_answer")
            return {
                "request_id": o.request_id,
                "outcome": "review_needed",
                "message": "There is no note in this file to check yet.",
                **meta(run),
            }
        tags_of = {c: t for c in run.stores.graph.node_ids() if (t := run.tags(c))}
        rep = presend_check(
            note_id,
            text,
            extract_metadata(text, run.departments),
            user_id=o.ctx.user_id,
            instruments=run.stores.instruments,
            relations=list(run.stores.relations),
            tags_of=tags_of,
            rules=run.rules,
            store=store,
            policy=run.policy,
            classification=run.classification,
            windows=run.windows(),
        )
        audit.record(
            o.request_id,
            o.ctx.user_id,
            "assist.presend",
            "ok",
            ids=(body.computer_no, note_id, *(e for f in rep.flags for e in f.evidence_ids)),
            detail=rep.outcome.value,
        )
        return {"request_id": o.request_id, **_report(rep), **meta(run)}

    @r.post("/draft")
    def draft(body: DraftIn, o: Annotated[Officer, Depends(officer)]) -> dict[str, Any]:
        """Insert as Yellow Note / Create DFA draft / Suggest reference — a DRAFT, on click."""
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
        return {"request_id": o.request_id, **receipt.model_dump(mode="json")}

    return r


def _report(rep: PreSendReport) -> dict[str, Any]:
    return {
        "note_id": rep.note_id,
        "outcome": rep.outcome.value,
        "flags": [
            {
                "type": f.type.value,
                "cited": f.cited,
                "evidence_ids": list(f.evidence_ids),
                "explanation": f.explanation,
                "certain": f.certain,
                "review_state": f.review_state,
            }
            for f in rep.flags
        ],
        "status_unconfirmed": list(rep.status_unconfirmed),
        "fact_gaps": list(rep.fact_gaps),
        "authority_message": rep.authority.message if rep.authority else None,
    }
