"""Mock e-Office sandbox screens' API — SYNTHETIC, not NIC e-Office (plan §11.2, §11.4, §11.7).

What a signed-in sandbox officer sees in e-Office itself: their profile, the files they can open
and a file's inner page (notes, correspondence, movements). Reach follows the e-Office search
privilege / movement trail / assignment, and — stricter than e-Office, so the demo can never
show more than C2-24 would — the officer's clearance must cover the file's classification.
Unknown and unavailable files give the same answer. Every response carries the mock banner.
"""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import Classification
from app.connectors.eoffice import ConnectorError, ReceiptContext
from app.eoffice_mock.adapter import MockEOfficeAdapter
from app.eoffice_mock.models import BANNER, EFile, SandboxProfile

NOT_SIGNED_IN = "Not signed in."
NOT_AVAILABLE = "File not available."


def build_sandbox_router(
    *,
    adapter: MockEOfficeAdapter,
    classification: Classification,
    identify: Callable[[Request], str | None],
    on_event: Callable[[], None] = lambda: None,
) -> APIRouter:
    r = APIRouter(prefix="/sandbox", tags=["sandbox"])
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
                {"user_id": p.user_id, "name": p.name, "post": p.post} for p in adapter.profiles()
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

    @r.get("/files")
    def files(p: Annotated[SandboxProfile, Depends(me)]) -> dict[str, Any]:
        rows = [file_row(f) for f in adapter.reachable_files(p.user_id) if cleared(p, f)]
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
            }
            for d in adapter.drafts.values()
            if d.computer_no == computer_no
        ]
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
            "correspondence": [
                c.model_dump(mode="json") for c in adapter.correspondence(computer_no)
            ],
            "movements": [m.model_dump(mode="json") for m in adapter.movements(computer_no)],
        }

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
            raise HTTPException(status_code=404, detail="Receipt not available.") from None
        return {"banner": BANNER, "receipt": receipt_row(rc)}

    @r.post("/receipts/{computer_no}/arrive")
    def letter_arrives(
        computer_no: str, p: Annotated[SandboxProfile, Depends(me)]
    ) -> dict[str, Any]:
        """Sandbox replay: the held-back letter arrives and is handed to ingestion."""
        try:
            ev = adapter.letter_arrives(computer_no, p.user_id)
        except ConnectorError:
            raise HTTPException(status_code=404, detail="Receipt not available.") from None
        on_event()  # composition root: the core picks up the event (ingestion → reconciliation)
        return {"banner": BANNER, "event_id": ev.event_id, "kind": ev.kind.value}

    return r
