"""EOfficeConnector: the ONLY boundary between an e-Office and the C2-24 core (plan §11.3).

Events in · context in · drafts out. A real adapter (authorised export or official API) can replace
the mock adapter without touching ingestion, retrieval, agents or security (CLAUDE.md §2.4).
Core modules import this file, never `app.eoffice_mock`.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.auth.models import SearchScope
from app.auth.store import AccessTuple, Relation

__all__ = ["SearchScope"]  # re-exported: SearchScope is defined by auth


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OfficerContext(_Frozen):
    """Who is asking, as e-Office knows them (plan §11.4). Feeds `compute_scope`."""

    user_id: str
    post: str
    role_rank: int = Field(ge=0)
    department: str
    section: str | None
    clearance: str
    search_scopes: frozenset[SearchScope]
    assigned_files: frozenset[str] = frozenset()
    handled_files: frozenset[str] = frozenset()  # from the movement trail


class FileContext(_Frozen):
    """The open file, metadata only. Note/correspondence text is fetched via ingestion, scoped."""

    computer_no: str
    file_no: str
    subject: str
    department: str
    dealing_section: str
    classification: str
    movement_trail: tuple[str, ...]  # user_ids the file has passed through, oldest first
    previous_references: tuple[str, ...] = ()
    later_references: tuple[str, ...] = ()


class ReceiptContext(_Frozen):
    """A diarised receipt (DAK), metadata only (plan §11.2 'Receipt'). The letter itself reaches
    C2-24 through ingestion; `letter_ref` is the reference the clerk diarised."""

    computer_no: str
    receipt_no: str
    diary_date: dt.date
    sender: str
    letter_ref: str | None
    letter_date: dt.date | None
    main_category: str
    subject: str
    department: str
    dealing_section: str
    put_in_file: str | None = None  # file Computer No. once put in a file


class EventKind(StrEnum):
    RECEIPT_DIARISED = "receipt_diarised"
    NOTE_CONFIRMED = "note_confirmed"
    DRAFT_APPROVED = "draft_approved"
    DRAFT_DISPATCHED = "draft_dispatched"
    FILE_CLOSED = "file_closed"
    ORDER_RECEIVED = "order_received"


class EOfficeEvent(_Frozen):
    """Something happened in e-Office; ingestion picks it up (plan §11.3 'Events in')."""

    event_id: str
    kind: EventKind
    occurred_at: dt.datetime
    computer_no: str | None = None
    object_id: str  # receipt / note / draft / document id inside the e-Office
    source_uri: str  # where ingestion fetches the artefact from


class DraftKind(StrEnum):
    """The only things the assistant may write back (plan §11.1 'Drafts only')."""

    YELLOW_NOTE = "yellow_note"
    DFA_DRAFT = "dfa_draft"
    SUGGESTED_REFERENCE = "suggested_reference"


class DraftRequest(_Frozen):
    """Created only when the officer clicks Insert / Create (plan §11.3 'Results out')."""

    kind: DraftKind
    computer_no: str
    requested_by: str  # user_id of the officer who clicked
    officer_clicked: bool
    body: str = Field(min_length=1)
    citations: tuple[str, ...] = ()  # canonical / clause IDs from the verified answer
    request_id: str  # C2-24 request that produced the content (audit link)


class DraftReceipt(_Frozen):
    draft_id: str
    kind: DraftKind
    computer_no: str
    created_at: dt.datetime
    status: str = "draft"  # the connector never returns anything but a draft


class SourceArtefact(_Frozen):
    """A document the e-Office holds, with the access tags the e-Office records for it (plan §11.3
    'Events in'). Handed to the normal ingestion pipeline; the tags are source-system metadata."""

    source_uri: str
    filename: str
    department: str
    section: str
    classification: str
    file_no: str | None = None
    data: bytes = Field(repr=False)


class ConnectorError(Exception):
    """Neutral failure. Callers deny / show a neutral message; never fall back to unscoped data."""


@runtime_checkable
class EOfficeConnector(Protocol):
    """Plan §11.3. Implemented by `app.eoffice_mock.adapter.MockEOfficeAdapter` (synthetic)."""

    @property
    def is_mock(self) -> bool:
        """True for the sandbox; the UI must show the mock banner (CLAUDE.md §2.4)."""
        ...

    def officer_context(self, user_id: str) -> OfficerContext: ...

    def file_context(self, computer_no: str, user_id: str) -> FileContext:
        """Raises ConnectorError if the file is unknown OR outside the officer's e-Office reach —
        the two cases are indistinguishable to the caller (no existence leak, plan §5.4)."""
        ...

    def receipt_context(self, computer_no: str, user_id: str) -> ReceiptContext:
        """Raises ConnectorError if the receipt is unknown OR outside the officer's reach — the
        two cases are indistinguishable (plan §5.4)."""
        ...

    def events_since(self, after: dt.datetime) -> list[EOfficeEvent]: ...

    def open_files(self) -> frozenset[str]:
        """e-File numbers of files that are open (not closed) — reconciliation notifies only
        these (plan §7.2, touchpoint 4)."""
        ...

    def documents(self) -> list[SourceArtefact]:
        """Initial load: every document the e-Office holds, for ingestion (real adapter:
        authorised export). Later changes arrive as events."""
        ...

    def create_draft(self, request: DraftRequest) -> DraftReceipt:
        """Write back a DRAFT only. Never confirms a Green Note, signs, sends or closes."""
        ...


def grants_from_context(ctx: OfficerContext) -> list[AccessTuple]:
    """e-Office profile → access-store tuples (plan §11.4). The sync job writes these into the
    store; authorization always reads the store, never this context directly."""
    u = f"user:{ctx.user_id}"
    out = [
        AccessTuple(subject=u, relation=Relation.MEMBER_OF, object=f"department:{ctx.department}"),
        AccessTuple(
            subject=u, relation=Relation.HAS_CLEARANCE, object=f"clearance:{ctx.clearance}"
        ),
        AccessTuple(subject=u, relation=Relation.HAS_RANK, object=f"rank:{ctx.role_rank}"),
    ]
    if ctx.section:
        out.append(
            AccessTuple(subject=u, relation=Relation.IN_SECTION, object=f"section:{ctx.section}")
        )
    out += [
        AccessTuple(subject=u, relation=Relation.HAS_SEARCH_SCOPE, object=f"scope:{s.value}")
        for s in sorted(ctx.search_scopes)
    ]
    out += [
        AccessTuple(subject=u, relation=Relation.ASSIGNED, object=f"file:{f}")
        for f in sorted(ctx.assigned_files)
    ]
    out += [
        AccessTuple(subject=u, relation=Relation.HANDLED, object=f"file:{f}")
        for f in sorted(ctx.handled_files)
    ]
    return out
