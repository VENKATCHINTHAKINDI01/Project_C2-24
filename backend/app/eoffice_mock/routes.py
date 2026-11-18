"""Mock e-Office sandbox screens' API — SYNTHETIC, not NIC e-Office (plan §11.2, §11.4, §11.7).

What a signed-in sandbox officer sees in e-Office itself: their profile, the files they can open
and a file's inner page (notes, correspondence, movements). Reach follows the e-Office search
privilege / movement trail / assignment, and — stricter than e-Office, so the demo can never
show more than C2-24 would — the officer's clearance must cover the file's classification.
Unknown and unavailable files give the same answer. Every response carries the mock banner.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth.messages import FILE_NOT_AVAILABLE, RECEIPT_NOT_AVAILABLE
from app.config import Classification
from app.connectors.eoffice import ConnectorError, DraftOutcome, ReceiptContext
from app.eoffice_mock.adapter import MockEOfficeAdapter
from app.eoffice_mock.models import BANNER, Draft, EFile, FileState, SandboxProfile
from app.eoffice_mock.preferences import Preferences, PreferenceStore

NOT_SIGNED_IN = "Not signed in."
NOT_AVAILABLE = FILE_NOT_AVAILABLE  # ADR-0016: same for unknown and hidden


class OrderArrivesIn(BaseModel):
    id: str  # canonical ID of a held-back order, as listed by GET /orders/pending


class DraftSaveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=20000)


DRAFT_NOT_AVAILABLE = "This draft isn't available."


class CreateFileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject: str = Field(min_length=10, max_length=500)
    previous_references: list[str] = Field(default_factory=list, max_length=20)


class CloseFileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    remarks: str = Field(min_length=5, max_length=4000)


def build_sandbox_router(
    *,
    adapter: MockEOfficeAdapter,
    classification: Classification,
    identify: Callable[[Request], str | None],
    on_event: Callable[[], None] = lambda: None,
    on_outcome: Callable[[DraftOutcome], None] = lambda _o: None,
    preferences: PreferenceStore | None = None,
) -> APIRouter:
    r = APIRouter(prefix="/sandbox", tags=["sandbox"])
    prefs = preferences if preferences is not None else PreferenceStore()
    rank = {lv.name: lv.rank for lv in classification.levels}

    def me(request: Request) -> SandboxProfile:
        uid = identify(request)
        try:
            if not uid:
                raise ConnectorError("no identity")
            return adapter.profile(uid)
        except ConnectorError:
            raise HTTPException(status_code=401, detail=NOT_SIGNED_IN) from None

    def cleared(p: SandboxProfile, f: EFile) -> bool:
        return rank.get(p.clearance, -1) >= rank.get(f.classification, len(rank))

    def file_row(f: EFile) -> dict[str, Any]:
        return {
            "computer_no": f.computer_no,
            "file_no": f.file_no,
            "subject": f.subject,
            "department": f.department,
            "dealing_section": f.dealing_section,
            "category": f.category,
            "classification": f.classification,
            "state": f.state.value,
        }

    @r.get("/profiles")
    def profiles() -> dict[str, Any]:
        """Sign-in picker (simulated login — no Parichay, CLAUDE.md §2.4)."""
        return {
            "banner": BANNER,
            "profiles": [
                {
                    "user_id": p.user_id,
                    "name": p.name,
                    "post": p.post,
                    "department": p.department,
                    "section": p.section,
                    "clearance": p.clearance,
                }
                for p in adapter.profiles()
            ],
        }

    @r.get("/me")
    def whoami(p: Annotated[SandboxProfile, Depends(me)]) -> dict[str, Any]:
        return {
            "banner": BANNER,
            "user_id": p.user_id,
            "name": p.name,
            "post": p.post,
            "department": p.department,
            "section": p.section,
            "clearance": p.clearance,
            "search_scopes": sorted(s.value for s in p.search_scopes),
        }

    # The officer's own display and assistant settings (ADR-0041). Nothing here changes access.
    @r.get("/me/preferences")
    def get_preferences(p: Annotated[SandboxProfile, Depends(me)]) -> Preferences:
        return prefs.get(p.user_id)

    @r.post("/me/preferences")
    def save_preferences(
        body: Preferences, p: Annotated[SandboxProfile, Depends(me)]
    ) -> Preferences:
        return prefs.put(p.user_id, body)

    @r.post("/me/preferences/reset")
    def reset_preferences(p: Annotated[SandboxProfile, Depends(me)]) -> Preferences:
        return prefs.reset(p.user_id)

    @r.get("/files")
    def files(p: Annotated[SandboxProfile, Depends(me)]) -> dict[str, Any]:
        rows = []
        for f in adapter.reachable_files(p.user_id):
            if not cleared(p, f):
                continue
            moves = adapter.movements(f.computer_no)
            last = max(moves, key=lambda m: m.seq) if moves else None
            holder = adapter.holder(f.computer_no)
            rows.append(
                {
                    **file_row(f),
                    # the e-Office folders (Inbox / Created / Closed) are views of these fields
                    "with_me": f.state is not FileState.CLOSED and holder == p.user_id,
                    "created_by_me": f.created_by == p.user_id,
                    "holder_post": adapter.post_of(holder) if holder else None,
                    "sent_by_post": adapter.post_of(last.from_user) if last else None,
                    "received_on": last.sent_at.isoformat() if last else None,
                    "due_on": last.due_on.isoformat() if last and last.due_on else None,
                    "priority": last.priority if last else "normal",
                    "created_on": f.created_on.isoformat() if f.created_on else None,
                }
            )
        return {"banner": BANNER, "files": sorted(rows, key=lambda x: x["computer_no"])}

    @r.get("/files/{computer_no}")
    def file_page(computer_no: str, p: Annotated[SandboxProfile, Depends(me)]) -> dict[str, Any]:
        try:
            f = adapter.open_file(computer_no, p.user_id)
        except ConnectorError:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None
        if not cleared(p, f):
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE)
        notes = [
            {
                "note_id": n.note_id,
                "note_no": n.note_no,
                "paragraph_from": n.paragraph_from,
                "state": n.state.value,
                "author_post": n.author_post,
                "text_source": n.text_source.value,
                "text": n.versions[-1].text if n.versions else None,
                "versions": len(n.versions),
                "created_by_assistant": n.created_by_assistant,
            }
            for n in adapter.notes(computer_no)
        ]
        drafts = [
            {
                "draft_id": d.draft_id,
                "kind": d.kind,
                "status": d.status.value,
                "text": d.versions[-1].text if d.versions else None,
                "request_id": d.request_id,
                "versions": len(d.versions),
            }
            for d in adapter.my_drafts(computer_no, p.user_id)  # the author's own, until confirmed
        ]

        def dfa_row(d: Draft) -> dict[str, Any]:
            return {
                "draft_id": d.draft_id,
                "kind": d.kind,
                "status": d.status.value,
                "text": d.versions[-1].text if d.versions else None,
                "submitted_at": d.submitted_at.isoformat() if d.submitted_at else None,
                "author_post": adapter.post_of(d.requested_by) if d.requested_by else None,
                "approved_by_post": adapter.post_of(d.approved_by) if d.approved_by else None,
                "issued_as": d.issued_as,
            }

        return {
            "banner": BANNER,
            "file": {
                **file_row(f),
                "previous_references": f.previous_references,
                "later_references": f.later_references,
                "linked_files": f.linked_files,
            },
            "notes": notes,
            "drafts": drafts,
            # DFAs this officer put up (waiting, or issued), and those put up TO them
            "submitted": [dfa_row(d) for d in adapter.submitted_by_me(computer_no, p.user_id)],
            "awaiting_approval": [
                dfa_row(d) for d in adapter.awaiting_approval(computer_no, p.user_id)
            ],
            "attachments": [
                {
                    "attachment_id": a.attachment_id,
                    "filename": a.filename,
                    "size": a.size,
                    "uploaded_by_post": adapter.post_of(a.uploaded_by),
                    "uploaded_at": a.uploaded_at.isoformat(),
                }
                for a in adapter.attachments(computer_no)
            ],
            "correspondence": [
                c.model_dump(mode="json") for c in adapter.correspondence(computer_no)
            ],
            "movements": [
                {
                    **m.model_dump(mode="json"),
                    "from_post": adapter.post_of(m.from_user),
                    "to_post": adapter.post_of(m.to_user),
                }
                for m in adapter.movements(computer_no)
            ],
        }

    def own_draft_file(computer_no: str, p: SandboxProfile) -> None:
        try:
            f = adapter.open_file(computer_no, p.user_id)
        except ConnectorError:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None
        if not cleared(p, f):
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE)

    @r.post("/files/{computer_no}/drafts/{draft_id}/save")
    def save_draft(
        computer_no: str,
        draft_id: str,
        body: DraftSaveIn,
        p: Annotated[SandboxProfile, Depends(me)],
    ) -> dict[str, Any]:
        """The officer edits their own draft (Yellow Note / DFA): a new version, earlier kept."""
        own_draft_file(computer_no, p)
        try:
            d = adapter.save_draft(computer_no, draft_id, p.user_id, body.text)
        except ConnectorError:
            raise HTTPException(status_code=404, detail=DRAFT_NOT_AVAILABLE) from None
        return {"banner": BANNER, "draft_id": d.draft_id, "versions": len(d.versions)}

    @r.post("/files/{computer_no}/drafts/{draft_id}/confirm")
    def confirm_draft(
        computer_no: str, draft_id: str, p: Annotated[SandboxProfile, Depends(me)]
    ) -> dict[str, Any]:
        """The officer confirms their Yellow Note → the next Green Note (simulated signature, no
        DSC/eSign). This is the officer's e-Office action; the assistant has no such endpoint."""
        own_draft_file(computer_no, p)
        try:
            out = adapter.confirm_yellow_note(computer_no, draft_id, p.user_id)
        except ConnectorError:
            raise HTTPException(status_code=404, detail=DRAFT_NOT_AVAILABLE) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        on_outcome(out)  # composition root: recorded as feedback (ADR-0031)
        on_event()  # the Green Note is an official act: the note sheet goes to ingestion
        return {"banner": BANNER, "draft_id": draft_id, "note_id": out.note_id, "state": "green"}

    @r.post("/files/{computer_no}/drafts/{draft_id}/submit")
    def submit_draft(
        computer_no: str, draft_id: str, p: Annotated[SandboxProfile, Depends(me)]
    ) -> dict[str, Any]:
        """The author puts their DFA up for approval (ADR-0045). Nothing is ingested: a draft put
        up is still a draft."""
        own_draft_file(computer_no, p)
        try:
            d = adapter.submit_draft(computer_no, draft_id, p.user_id)
        except ConnectorError:
            raise HTTPException(status_code=404, detail=DRAFT_NOT_AVAILABLE) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return {"banner": BANNER, "draft_id": d.draft_id, "status": d.status.value}

    @r.post("/files/{computer_no}/approvals/{draft_id}/issue")
    def approve_and_issue(
        computer_no: str, draft_id: str, p: Annotated[SandboxProfile, Depends(me)]
    ) -> dict[str, Any]:
        """The approving officer approves, signs (simulated click) and issues the DFA put up to
        them. Only now does the order enter institutional memory (ADR-0045)."""
        own_draft_file(computer_no, p)
        try:
            d = adapter.approve_and_issue(computer_no, draft_id, p.user_id)
        except ConnectorError:
            raise HTTPException(status_code=404, detail=DRAFT_NOT_AVAILABLE) from None
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        on_event()
        return {
            "banner": BANNER,
            "draft_id": d.draft_id,
            "status": d.status.value,
            "issued_as": d.issued_as,
        }

    @r.post("/files/{computer_no}/approvals/{draft_id}/return")
    def return_draft(
        computer_no: str, draft_id: str, p: Annotated[SandboxProfile, Depends(me)]
    ) -> dict[str, Any]:
        """The approving officer sends the DFA back to its author for changes."""
        own_draft_file(computer_no, p)
        try:
            d = adapter.return_draft(computer_no, draft_id, p.user_id)
        except ConnectorError:
            raise HTTPException(status_code=404, detail=DRAFT_NOT_AVAILABLE) from None
        return {"banner": BANNER, "draft_id": d.draft_id, "status": d.status.value}

    @r.post("/files/{computer_no}/attachments")
    async def attach(
        computer_no: str,
        request: Request,
        p: Annotated[SandboxProfile, Depends(me)],
        name: Annotated[str, Query(min_length=1, max_length=200)],
    ) -> dict[str, Any]:
        """Simulated e-Office "Attach": the paper goes to ingestion with the file's access tags
        (native text read; a scan OCR'd, held for review unless confidently read). The body is the
        file itself (no form encoding), up to `upload_max_bytes`."""
        data = await request.body()
        try:
            f = adapter.open_file(computer_no, p.user_id)
            if not cleared(p, f):
                raise ConnectorError("file not available")
            a = adapter.add_attachment(computer_no, p.user_id, name, data)
        except ConnectorError:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        on_event()
        return {
            "banner": BANNER,
            "attachment_id": a.attachment_id,
            "filename": a.filename,
            "size": a.size,
        }

    @r.post("/files/{computer_no}/drafts/{draft_id}/discard")
    def discard_draft(
        computer_no: str, draft_id: str, p: Annotated[SandboxProfile, Depends(me)]
    ) -> dict[str, Any]:
        """The officer throws their draft away (kept as discarded, never shown again)."""
        own_draft_file(computer_no, p)
        try:
            out = adapter.discard_draft(computer_no, draft_id, p.user_id)
        except ConnectorError:
            raise HTTPException(status_code=404, detail=DRAFT_NOT_AVAILABLE) from None
        on_outcome(out)
        return {"banner": BANNER, "draft_id": draft_id, "status": "discarded"}

    def receipt_row(rc: ReceiptContext) -> dict[str, Any]:
        return {
            "computer_no": rc.computer_no,
            "receipt_no": rc.receipt_no,
            "diary_date": rc.diary_date.isoformat(),
            "sender": rc.sender,
            "letter_ref": rc.letter_ref,
            "letter_date": rc.letter_date.isoformat() if rc.letter_date else None,
            "main_category": rc.main_category,
            "subject": rc.subject,
            "dealing_section": rc.dealing_section,
            "put_in_file": rc.put_in_file,
            "letter_pending": adapter.letter_pending(rc.computer_no),  # sandbox replay only
        }

    @r.get("/receipts")
    def receipts(p: Annotated[SandboxProfile, Depends(me)]) -> dict[str, Any]:
        """Receipt inbox: receipts of the officer's section (or department / global scope)."""
        return {
            "banner": BANNER,
            "receipts": [receipt_row(x) for x in adapter.receipts_for(p.user_id)],
        }

    @r.get("/receipts/{computer_no}")
    def receipt_page(computer_no: str, p: Annotated[SandboxProfile, Depends(me)]) -> dict[str, Any]:
        try:
            rc = adapter.receipt_context(computer_no, p.user_id)
        except ConnectorError:
            raise HTTPException(status_code=404, detail=RECEIPT_NOT_AVAILABLE) from None
        return {"banner": BANNER, "receipt": receipt_row(rc)}

    @r.post("/receipts/{computer_no}/arrive")
    def letter_arrives(
        computer_no: str, p: Annotated[SandboxProfile, Depends(me)]
    ) -> dict[str, Any]:
        """Sandbox replay: the held-back letter arrives and is handed to ingestion."""
        try:
            ev = adapter.letter_arrives(computer_no, p.user_id)
        except ConnectorError:
            raise HTTPException(status_code=404, detail=RECEIPT_NOT_AVAILABLE) from None
        on_event()  # composition root: the core picks up the event (ingestion → reconciliation)
        return {"banner": BANNER, "event_id": ev.event_id, "kind": ev.kind.value}

    @r.get("/orders/pending")
    def orders_pending(p: Annotated[SandboxProfile, Depends(me)]) -> dict[str, Any]:
        """Sandbox replay: orders held back for the demo that have not arrived yet (public orders;
        only their IDs are shown)."""
        return {
            "banner": BANNER,
            "orders": [
                {"id": Path(u).parent.name, "source_uri": u} for u in adapter.pending_orders()
            ],
        }

    @r.post("/files")
    def create_file(
        body: CreateFileIn, p: Annotated[SandboxProfile, Depends(me)]
    ) -> dict[str, Any]:
        """Simulated e-Office "Create File" (touchpoint 5): the officer opens a file in their own
        section with the previous references THEY chose (the assistant only suggests)."""
        try:
            f = adapter.create_file(p.user_id, body.subject, body.previous_references)
        except ValueError:
            raise HTTPException(
                status_code=422, detail="You hold no section to open a file in."
            ) from None
        on_event()  # the file's particulars go to ingestion (its record)
        return {
            "banner": BANNER,
            "file": {**file_row(f), "previous_references": f.previous_references},
        }

    @r.post("/files/{computer_no}/close")
    def close_file(
        computer_no: str, body: CloseFileIn, p: Annotated[SandboxProfile, Depends(me)]
    ) -> dict[str, Any]:
        """Simulated e-Office "Close File" (touchpoint 16): the officer holding the file closes it
        with closing remarks they wrote or accepted; the decided file then goes to ingestion."""
        try:
            f = adapter.open_file(computer_no, p.user_id)
            if not cleared(p, f):
                raise ConnectorError("file not available")
            closed = adapter.close_file(computer_no, p.user_id, body.remarks)
        except ConnectorError:
            raise HTTPException(status_code=404, detail=NOT_AVAILABLE) from None
        on_event()
        return {"banner": BANNER, "file": file_row(closed)}

    @r.post("/orders/arrive")
    def order_arrives(
        body: OrderArrivesIn, p: Annotated[SandboxProfile, Depends(me)]
    ) -> dict[str, Any]:
        """Sandbox replay: a newly issued order arrives and is handed to ingestion; reconciliation
        then lists the open files that rely on the order it changes (touchpoint 4)."""
        uri = next((u for u in adapter.pending_orders() if Path(u).parent.name == body.id), None)
        try:
            ev = adapter.order_arrives(uri or "")
        except ConnectorError:
            raise HTTPException(status_code=404, detail="No such order is waiting.") from None
        on_event()
        return {"banner": BANNER, "event_id": ev.event_id, "kind": ev.kind.value, "id": body.id}

    return r
