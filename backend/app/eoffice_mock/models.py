"""Mock e-Office sandbox objects — SYNTHETIC, not NIC e-Office (plan §11.2, §11.6).

Shapes follow the eFile 7.x user manual: receipts with diary metadata, files with File No. and
Computer No., notes (Yellow → Green, versioned), correspondence (PUC/FR) with pages, drafts (DFA),
movements, links and Previous/Later References.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.auth.models import SearchScope

BANNER = "Mock e-Office sandbox — not NIC e-Office · synthetic data"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SandboxProfile(_Model):
    """A mock officer (plan §11.6: eight sandbox profiles)."""

    user_id: str
    name: str
    post: str
    role_rank: int = Field(ge=0)
    department: str
    section: str | None
    clearance: str
    search_scopes: frozenset[SearchScope]
    login: bool = True  # False for posts that appear in notes but have no sandbox login (e.g. ASO)


class Nature(StrEnum):
    ELECTRONIC = "E"
    PHYSICAL = "P"


class Receipt(_Model):
    """eFile 7.0 manual: diarised DAK/letter with a Computer No. and a Receipt No. of the form
    ``sequence no./creation year/dealing section``."""

    computer_no: str
    receipt_no: str
    nature: Nature = Nature.ELECTRONIC
    diary_date: dt.date
    sender: str
    letter_ref: str | None = None
    letter_date: dt.date | None = None
    main_category: str
    subject: str
    dealing_section: str
    source_uri: str  # the uploaded scanned/native PDF
    put_in_file: str | None = None  # file Computer No. once put in a file
    assumed_fields: tuple[str, ...] = ()  # fields the generator had to assume (synthetic)


class NoteState(StrEnum):
    YELLOW = "yellow"  # draft, editable, versioned
    GREEN = "green"  # confirmed by the officer; immutable


class TextSource(StrEnum):
    NATIVE = "native"  # typed in the noting editor: text is available
    NEEDS_OCR = "needs_ocr"  # scanned / migrated noting: text comes only from ingestion OCR


class NoteVersion(_Model):
    version: int = Field(ge=1)
    text: str | None  # None when TextSource.NEEDS_OCR
    saved_at: dt.datetime
    saved_by: str


class Note(_Model):
    note_id: str
    computer_no: str
    note_no: int = Field(ge=1)
    paragraph_from: int = Field(ge=1)
    state: NoteState
    author: str  # user_id of the post holder (sandbox profile or staff post)
    author_post: str
    text_source: TextSource = TextSource.NATIVE
    source_uri: str | None = None  # document the note was taken from
    versions: list[NoteVersion]
    confirmed_at: dt.datetime | None = None
    created_by_assistant: bool = False  # inserted via "Insert as Yellow Note"


class CorrespondenceKind(StrEnum):
    PUC = "puc"  # paper under consideration
    FR = "fr"  # fresh receipt


class Correspondence(_Model):
    correspondence_id: str
    computer_no: str
    kind: CorrespondenceKind
    page_from: int = Field(ge=1)
    page_to: int = Field(ge=1)
    title: str
    canonical_id: str | None = None  # when the page is a G.O./circular in the corpus
    receipt_id: str | None = None


class DraftStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"  # a DFA put up to the approving officer; the author can no longer edit
    APPROVED = "approved"
    SIGNED = "signed"  # simulated click only — no DSC/eSign
    DISPATCHED = "dispatched"
    CONFIRMED = "confirmed"  # a Yellow Note the officer confirmed: it is now a Green Note
    DISCARDED = "discarded"  # thrown away by the officer; kept, never shown again


class Draft(_Model):
    draft_id: str
    computer_no: str
    kind: str  # yellow_note / dfa_draft / suggested_reference / manual
    status: DraftStatus
    versions: list[NoteVersion]
    created_by_assistant: bool = False
    request_id: str | None = None
    requested_by: str | None = None  # the officer who clicked Insert / Create (owns the draft)
    note_id: str | None = None  # the Green Note a confirmed Yellow Note became
    submitted_at: dt.datetime | None = None
    approved_by: str | None = None  # the approving officer (simulated signature, no DSC/eSign)
    issued_as: str | None = None  # the number and date allotted on issue (SYNTHETIC numbering)
    issued_uri: str | None = None  # where the issued order went to ingestion


class Attachment(_Model):
    """A paper an officer attached to an e-File (sandbox "Attach"). SYNTHETIC store; the bytes go
    to ingestion as a SourceArtefact with the file's access tags."""

    attachment_id: str
    computer_no: str
    filename: str
    size: int = Field(ge=1)
    uploaded_by: str
    uploaded_at: dt.datetime
    source_uri: str


class Movement(_Model):
    computer_no: str
    seq: int = Field(ge=1)
    from_user: str
    to_user: str
    sent_at: dt.datetime
    due_on: dt.date | None = None
    priority: str = "normal"
    remarks: str = ""
    sent_back: bool = False


class FileState(StrEnum):
    OPEN = "open"
    PARKED = "parked"
    CLOSED = "closed"


class EFile(_Model):
    computer_no: str
    file_no: str
    nature: Nature = Nature.ELECTRONIC
    file_head: str | None = None  # Non-SFS file head, e.g. "USD01-12"
    subject: str
    description: str = ""
    department: str
    dealing_section: str
    category: str
    classification: str
    state: FileState = FileState.OPEN
    created_by: str | None  # None when the source does not say who opened the file
    created_on: dt.date
    previous_references: list[str] = []
    later_references: list[str] = []
    linked_files: list[str] = []


class Seed(_Model):
    """Sandbox seed (plan §11.6). SYNTHETIC; holds no answer keys — relations, conflicts and
    expected answers belong to the evaluation harness only (CLAUDE.md §9.2)."""

    synthetic: bool
    banner: str
    corpus: str
    as_of: dt.date
    sources: tuple[str, ...]
    profiles: list[SandboxProfile]
    assignments: dict[str, list[str]]
    files: list[EFile]
    notes: list[Note]
    correspondence: list[Correspondence]
    movements: list[Movement]
    receipts: list[Receipt]
