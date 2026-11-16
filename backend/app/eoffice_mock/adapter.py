"""In-memory mock adapter for `EOfficeConnector` — SYNTHETIC sandbox, not NIC e-Office (plan §11.3).

Holds sandbox objects in memory; the Cloud SQL `eoffice_mock` schema replaces the store later
without changing the connector contract.
"""

from __future__ import annotations

import datetime as dt
import itertools
import re
from collections.abc import Iterable
from pathlib import Path

from app.connectors.eoffice import (
    ConnectorError,
    DraftKind,
    DraftOutcome,
    DraftOutcomeKind,
    DraftReceipt,
    DraftRequest,
    EOfficeEvent,
    EventKind,
    FileContext,
    MovementRef,
    NoteRef,
    OfficerContext,
    OfficerFile,
    PageRef,
    ReceiptContext,
    SearchScope,
    SourceArtefact,
)
from app.eoffice_mock.models import (
    BANNER,
    Correspondence,
    Draft,
    DraftStatus,
    EFile,
    FileState,
    Movement,
    Note,
    NoteState,
    NoteVersion,
    Receipt,
    SandboxProfile,
    Seed,
)
from app.hitl.feedback import edit_share, strip_watermark


class MockEOfficeAdapter:
    """Plan §11.3 mock adapter. `now` is injectable so tests stay deterministic."""

    is_mock = True

    def __init__(
        self,
        profiles: Iterable[SandboxProfile],
        files: Iterable[EFile],
        movements: Iterable[Movement] = (),
        events: Iterable[EOfficeEvent] = (),
        assignments: dict[str, frozenset[str]] | None = None,
        now: dt.datetime | None = None,
        notes: Iterable[Note] = (),
        correspondence: Iterable[Correspondence] = (),
        artefacts: Iterable[SourceArtefact] = (),
        receipts: Iterable[Receipt] = (),
        holdback: Iterable[str] = (),
        arrivals: Iterable[SourceArtefact] = (),
    ) -> None:
        self._profiles = {p.user_id: p for p in profiles}
        self._files = {f.computer_no: f for f in files}
        self._movements = sorted(movements, key=lambda m: (m.computer_no, m.seq))
        self._events = sorted(events, key=lambda e: e.occurred_at)
        self._assignments = assignments or {}
        self._now = now
        self._seq = itertools.count(1)
        self.drafts: dict[str, Draft] = {}
        self._notes = sorted(notes, key=lambda n: (n.computer_no, n.note_no))
        self._correspondence = sorted(correspondence, key=lambda c: (c.computer_no, c.page_from))
        self._artefacts = list(artefacts)
        self._receipts = {r.computer_no: r for r in receipts}
        # Replay (sandbox demo): letters held back from the initial load until they "arrive".
        held = set(holdback)
        self._pending = {a.filename: a for a in self._artefacts if a.filename in held}
        self._artefacts = [a for a in self._artefacts if a.filename not in held]
        # Replay (sandbox demo): orders issued "later" — not loaded until `order_arrives`.
        self._arrivals = {a.source_uri: a for a in arrivals}

    def _clock(self) -> dt.datetime:
        return self._now or dt.datetime.now(dt.UTC)

    def _profile(self, user_id: str) -> SandboxProfile:
        try:
            return self._profiles[user_id]
        except KeyError as exc:
            raise ConnectorError("unknown officer") from exc

    def _trail(self, computer_no: str) -> tuple[str, ...]:
        trail: list[str] = []
        for m in self._movements:
            if m.computer_no != computer_no:
                continue
            for u in (m.from_user, m.to_user):
                if u not in trail:
                    trail.append(u)
        return tuple(trail)

    def officer_context(self, user_id: str) -> OfficerContext:
        p = self._profile(user_id)
        return OfficerContext(
            user_id=p.user_id,
            post=p.post,
            role_rank=p.role_rank,
            department=p.department,
            section=p.section,
            clearance=p.clearance,
            search_scopes=p.search_scopes,
            assigned_files=self._assignments.get(user_id, frozenset()),
            handled_files=frozenset(
                f.file_no for f in self._files.values() if user_id in self._trail(f.computer_no)
            ),
        )

    def _reachable(self, p: SandboxProfile, f: EFile) -> bool:
        """e-Office reach for opening a file: the scope from search privilege, or the file
        passed through the officer, or it is assigned to them. Classification is applied
        separately by C2-24's `can_access` (plan §11.4)."""
        s = p.search_scopes
        if SearchScope.GLOBAL in s:
            return True
        if SearchScope.DEPARTMENT in s and f.department == p.department:
            return True
        if (
            s & {SearchScope.SECTION, SearchScope.SECTION_HIERARCHY}
            and f.department == p.department
            and f.dealing_section == p.section
        ):
            return True
        return p.user_id in self._trail(f.computer_no) or f.file_no in self._assignments.get(
            p.user_id, frozenset()
        )

    def file_context(self, computer_no: str, user_id: str) -> FileContext:
        p = self._profile(user_id)
        f = self._files.get(computer_no)
        if f is None or not self._reachable(p, f):
            raise ConnectorError("file not available")  # same message: no existence leak
        return FileContext(
            computer_no=f.computer_no,
            file_no=f.file_no,
            subject=f.subject,
            department=f.department,
            dealing_section=f.dealing_section,
            classification=f.classification,
            movement_trail=self._trail(f.computer_no),
            movements=tuple(
                MovementRef(
                    seq=m.seq,
                    from_user=m.from_user,
                    from_post=self._post(m.from_user),
                    to_user=m.to_user,
                    to_post=self._post(m.to_user),
                    sent_at=m.sent_at,
                    due_on=m.due_on,
                    priority=m.priority,
                    remarks=m.remarks,
                    sent_back=m.sent_back,
                )
                for m in sorted(self.movements(f.computer_no), key=lambda m: m.seq)
            ),
            state=f.state.value,
            created_on=f.created_on,
            created_by=f.created_by,
            previous_references=tuple(f.previous_references),
            later_references=tuple(f.later_references),
            notes=tuple(
                NoteRef(
                    note_id=n.note_id,
                    note_no=n.note_no,
                    paragraph_from=n.paragraph_from,
                    confirmed=n.state is NoteState.GREEN,
                )
                for n in self.notes(f.computer_no)
            ),
            pages=tuple(
                PageRef(
                    correspondence_id=c.correspondence_id,
                    page_from=c.page_from,
                    page_to=c.page_to,
                    title=c.title,
                    canonical_id=c.canonical_id,
                )
                for c in self.correspondence(f.computer_no)
            ),
        )

    def _receipt_department(self, r: Receipt) -> str | None:
        """The department of the receipt's dealing section (from the files it deals with)."""
        return next(
            (f.department for f in self._files.values() if f.dealing_section == r.dealing_section),
            None,
        )

    def _receipt_reachable(self, p: SandboxProfile, r: Receipt) -> bool:
        dept = self._receipt_department(r)
        s = p.search_scopes
        if dept is None:
            return False
        if SearchScope.GLOBAL in s or (SearchScope.DEPARTMENT in s and dept == p.department):
            return True
        return (
            bool(s & {SearchScope.SECTION, SearchScope.SECTION_HIERARCHY})
            and dept == p.department
            and r.dealing_section == p.section
        )

    def receipt_context(self, computer_no: str, user_id: str) -> ReceiptContext:
        p = self._profile(user_id)
        r = self._receipts.get(computer_no)
        dept = self._receipt_department(r) if r else None
        if r is None or dept is None or not self._receipt_reachable(p, r):
            raise ConnectorError("receipt not available")
        return ReceiptContext(
            computer_no=r.computer_no,
            receipt_no=r.receipt_no,
            diary_date=r.diary_date,
            sender=r.sender,
            letter_ref=r.letter_ref,
            letter_date=r.letter_date,
            main_category=r.main_category,
            subject=r.subject,
            department=dept,
            dealing_section=r.dealing_section,
            put_in_file=r.put_in_file,
            attachment_uri=self._uri_of(r.source_uri),
        )

    def receipts_for(self, user_id: str) -> list[ReceiptContext]:
        """Receipt inbox (sandbox screen)."""
        out = []
        for cno in sorted(self._receipts):
            try:
                out.append(self.receipt_context(cno, user_id))
            except ConnectorError:
                continue
        return out

    def events_since(self, after: dt.datetime) -> list[EOfficeEvent]:
        return [e for e in self._events if e.occurred_at > after]

    def documents(self) -> list[SourceArtefact]:
        return list(self._artefacts)

    def open_files(self) -> frozenset[str]:
        return frozenset(f.file_no for f in self._files.values() if f.state is FileState.OPEN)

    def letter_pending(self, computer_no: str) -> bool:
        r = self._receipts.get(computer_no)
        return r is not None and Path(r.source_uri).name in self._pending

    def letter_arrives(self, computer_no: str, user_id: str) -> EOfficeEvent:
        """Sandbox replay: the held-back letter of a receipt arrives — it joins `documents()`
        and an ORDER_RECEIVED event is raised for ingestion (plan §11.3 'Events in')."""
        rc = self.receipt_context(computer_no, user_id)  # same reach as the receipt
        r = self._receipts[rc.computer_no]
        art = self._pending.pop(Path(r.source_uri).name, None)
        if art is None:
            raise ConnectorError("nothing pending for this receipt")
        self._artefacts.append(art)
        ev = EOfficeEvent(
            event_id=f"MOCK-EVENT-{next(self._seq):05d}",
            kind=EventKind.ORDER_RECEIVED,
            occurred_at=self._clock(),
            object_id=r.computer_no,
            source_uri=art.source_uri,
        )
        self._events.append(ev)
        return ev

    def pending_orders(self) -> list[str]:
        """Sandbox replay: source URIs of the orders that have not "arrived" yet."""
        return sorted(self._arrivals)

    def order_arrives(self, source_uri: str) -> EOfficeEvent:
        """Sandbox replay: a newly issued order reaches the department — it joins `documents()`
        and an ORDER_RECEIVED event is raised for ingestion (plan §11.3 'Events in'). The
        open files that rely on the order it changes are then listed by reconciliation."""
        art = self._arrivals.pop(source_uri, None)
        if art is None:
            raise ConnectorError("no such order is waiting")
        self._artefacts.append(art)
        ev = EOfficeEvent(
            event_id=f"MOCK-EVENT-{next(self._seq):05d}",
            kind=EventKind.ORDER_RECEIVED,
            occurred_at=self._clock(),
            object_id=Path(source_uri).parent.name,
            source_uri=art.source_uri,
        )
        self._events.append(ev)
        return ev

    # ---- sandbox screens (e-Office side; not part of the connector contract) ----------------

    def profiles(self) -> list[SandboxProfile]:
        """Officers who can sign in to the sandbox (posts without a login are excluded)."""
        return [p for p in self._profiles.values() if p.login]

    def profile(self, user_id: str) -> SandboxProfile:
        p = self._profile(user_id)
        if not p.login:
            raise ConnectorError("unknown officer")
        return p

    def officer_files(self, user_id: str) -> tuple[OfficerFile, ...]:
        try:
            p = self.profile(user_id)
        except ConnectorError:
            return ()
        assigned = self._assignments.get(user_id, frozenset())
        out = []
        for f in self._files.values():
            if f.state is not FileState.OPEN or not self._reachable(p, f):
                continue
            moves = self.movements(f.computer_no)
            created = f.created_by == user_id
            if (
                f.file_no not in assigned
                and not created
                and user_id not in self._trail(f.computer_no)
            ):
                continue
            last = moves[-1] if moves else None
            if last is not None:  # with whoever it was last sent to
                mine = last.to_user == user_id
                since = last.sent_at if mine else None
            else:  # never sent: it is still with the officer who opened it
                mine = created
                since = (
                    dt.datetime.combine(f.created_on, dt.time(10), tzinfo=dt.UTC) if mine else None
                )
            out.append(
                OfficerFile(
                    computer_no=f.computer_no,
                    file_no=f.file_no,
                    subject=f.subject,
                    with_officer=mine,
                    since=since,
                    due_on=last.due_on if mine and last else None,
                    priority=last.priority if mine and last else "normal",
                    sent_back=bool(mine and last and last.sent_back),
                )
            )
        return tuple(sorted(out, key=lambda x: x.computer_no))

    def _uri_of(self, path: str) -> str | None:
        """The ingested artefact for a seed path (same file name)."""
        name = path.rsplit("/", 1)[-1]
        return next(
            (
                a.source_uri
                for a in (*self._artefacts, *self._pending.values())
                if a.filename == name
            ),
            None,
        )

    def _post(self, user_id: str) -> str | None:
        p = self._profiles.get(user_id)
        return p.post if p is not None else None

    def section_files(self, user_id: str) -> tuple[OfficerFile, ...]:
        try:
            p = self.profile(user_id)
        except ConnectorError:
            return ()
        if not p.section:
            return ()
        out = []
        for f in self._files.values():
            if (
                f.department != p.department
                or f.dealing_section != p.section
                or not self._reachable(p, f)
            ):
                continue
            moves = sorted(self.movements(f.computer_no), key=lambda m: m.seq)
            last = moves[-1] if moves else None
            out.append(
                OfficerFile(
                    computer_no=f.computer_no,
                    file_no=f.file_no,
                    subject=f.subject,
                    with_officer=(last.to_user == user_id) if last else f.created_by == user_id,
                    since=last.sent_at if last else None,
                    due_on=last.due_on if last else None,
                    priority=last.priority if last else "normal",
                    sent_back=bool(last and last.sent_back),
                    state=f.state.value,
                )
            )
        return tuple(sorted(out, key=lambda x: x.computer_no))

    # --- touchpoints 5 and 16: creating and closing a file (officer actions, ADR-0038) ---------

    def file_computer_no(self, file_no: str, user_id: str) -> str | None:
        """The Computer No. of a file the officer can reach, by its file number; else None."""
        p = self.profile(user_id)
        return next(
            (
                f.computer_no
                for f in self._files.values()
                if f.file_no == file_no and self._reachable(p, f)
            ),
            None,
        )

    def create_file(self, user_id: str, subject: str, previous_references: list[str]) -> EFile:
        """The officer opens a new file in their own section (simulated e-Office "Create File";
        SYNTHETIC number). Previous references are the file numbers the officer chose; only files
        they can reach are kept."""
        p = self.profile(user_id)
        if not p.section:
            raise ValueError("no dealing section to open a file in")
        year = self._clock().year
        same = [
            f
            for f in self._files.values()
            if f.dealing_section == p.section and f.department == p.department
        ]
        head = same[0].file_no.split("/", 1)[0] if same else f"{p.department}-{p.section}"
        seqs = [
            int(m.group(1))
            for f in same
            if (m := re.match(r"^[^/]+/(\d+)/(\d{4})-", f.file_no)) and int(m.group(2)) == year
        ]
        file_no = f"{head}/{max(seqs, default=0) + 1}/{year}-{p.section}"
        cno = str(max(int(c) for c in self._files) + 1) if self._files else "1000001"
        reach = {f.file_no for f in self._files.values() if self._reachable(p, f)}
        f = EFile(
            computer_no=cno,
            file_no=file_no,
            file_head=head,
            subject=" ".join(subject.split()),
            department=p.department,
            dealing_section=p.section,
            category=same[0].category if same else "Non-SFS",
            classification=same[0].classification if same else "RESTRICTED",
            state=FileState.OPEN,
            created_by=user_id,
            created_on=self._clock().date(),
            previous_references=[r for r in dict.fromkeys(previous_references) if r in reach],
        )
        self._files[cno] = f
        return f

    def holder(self, computer_no: str) -> str | None:
        moves = [m for m in self._movements if m.computer_no == computer_no]
        if moves:
            return max(moves, key=lambda m: m.seq).to_user
        f = self._files.get(computer_no)
        return f.created_by if f else None

    def close_file(self, computer_no: str, user_id: str, remarks: str) -> EFile:
        """The officer holding the file closes it with their closing remarks (simulated click).
        The remarks become the last Green Note; the notes typed in this sandbox are handed to
        ingestion as the file's closing note sheet, so the decided file joins the precedent
        index (touchpoint 16). Only the holder — or, when no holder is recorded, an officer of
        the dealing section — may close; anyone else gets 'not available'."""
        p = self.profile(user_id)
        f = self._files.get(computer_no)
        if f is None or not self._reachable(p, f):
            raise ConnectorError("file not available")
        h = self.holder(computer_no)
        if f.state is FileState.CLOSED or not (
            h == user_id
            or (h is None and p.section == f.dealing_section and p.department == f.department)
        ):
            raise ConnectorError("file not available")
        now = self._clock()
        no, para = self._next_paragraph(computer_no)
        text = remarks.strip()
        if not re.match(r"^\s*\d+\.", text):
            text = f"{para}. {text}"
        closing = Note(
            note_id=f"{computer_no}-N{no}",
            computer_no=computer_no,
            note_no=no,
            paragraph_from=para,
            state=NoteState.GREEN,
            author=user_id,
            author_post=p.post,
            versions=[NoteVersion(version=1, text=text, saved_at=now, saved_by=user_id)],
            confirmed_at=now,
        )
        self._notes = sorted([*self._notes, closing], key=lambda n: (n.computer_no, n.note_no))
        closed = f.model_copy(update={"state": FileState.CLOSED})
        self._files[computer_no] = closed
        sheet = self._note_sheet(
            closed, [n for n in self.notes(computer_no) if n.source_uri is None]
        )
        art = SourceArtefact(
            source_uri=f"sandbox://files/{computer_no}/closing-note-sheet",
            filename=f"closing-note-sheet-{computer_no}.txt",
            department=closed.department,
            section=closed.dealing_section,
            classification=closed.classification,
            file_no=closed.file_no,
            data=sheet.encode("utf-8"),
        )
        self._artefacts.append(art)
        self._events.append(
            EOfficeEvent(
                event_id=f"MOCK-EV-{next(self._seq):05d}",
                kind=EventKind.FILE_CLOSED,
                occurred_at=now,
                computer_no=computer_no,
                object_id=computer_no,
                source_uri=art.source_uri,
            )
        )
        return closed

    def _note_sheet(self, f: EFile, notes: list[Note]) -> str:
        """The file's notes typed in e-Office, in the note-sheet layout ingestion reads."""
        out = [f"File No.{f.file_no} (Computer No.{f.computer_no})", f"Subject: {f.subject}", ""]
        for n in notes:
            who = self._profiles.get(n.author)
            when = (n.confirmed_at or self._clock()).astimezone(
                dt.timezone(dt.timedelta(hours=5, minutes=30))
            )
            out += [
                f"Note # {n.note_no}",
                (n.versions[-1].text or "").strip(),
                "",
                when.strftime("%d/%m/%Y %I:%M %p"),
                (who.name if who else n.author).upper(),
                n.author_post.upper(),
                "",
            ]
        return "\n".join(out)

    def reachable_files(self, user_id: str) -> list[EFile]:
        p = self.profile(user_id)
        return [f for f in self._files.values() if self._reachable(p, f)]

    def open_file(self, computer_no: str, user_id: str) -> EFile:
        """Same reach as `file_context`; unknown and unreachable are indistinguishable."""
        p = self.profile(user_id)
        f = self._files.get(computer_no)
        if f is None or not self._reachable(p, f):
            raise ConnectorError("file not available")
        return f

    def notes(self, computer_no: str) -> list[Note]:
        return [n for n in self._notes if n.computer_no == computer_no]

    def correspondence(self, computer_no: str) -> list[Correspondence]:
        return [c for c in self._correspondence if c.computer_no == computer_no]

    def movements(self, computer_no: str) -> list[Movement]:
        return [m for m in self._movements if m.computer_no == computer_no]

    def create_draft(self, request: DraftRequest) -> DraftReceipt:
        if not request.officer_clicked:
            raise ConnectorError("drafts are created only on the officer's click")
        if request.kind not in set(DraftKind):
            raise ConnectorError("unsupported write-back")
        self.file_context(request.computer_no, request.requested_by)  # same reach as e-Office
        now = self._clock()
        draft_id = f"MOCK-DRAFT-{next(self._seq):05d}"
        self.drafts[draft_id] = Draft(
            draft_id=draft_id,
            computer_no=request.computer_no,
            kind=request.kind.value,
            status=DraftStatus.DRAFT,
            versions=[
                NoteVersion(version=1, text=request.body, saved_at=now, saved_by="c2-24-assistant")
            ],
            created_by_assistant=True,
            request_id=request.request_id,
            requested_by=request.requested_by,
        )
        return DraftReceipt(
            draft_id=draft_id, kind=request.kind, computer_no=request.computer_no, created_at=now
        )

    # --- The officer's own actions on drafts, in e-Office (sandbox; simulated, no DSC/eSign) ---

    def my_drafts(self, computer_no: str, user_id: str) -> list[Draft]:
        """Drafts on this file that this officer created and has not confirmed or discarded. A
        Yellow Note in e-Office is the author's own until confirmed: other officers who open the
        file do not see it."""
        self.open_file(computer_no, user_id)
        return [
            d
            for d in self.drafts.values()
            if d.computer_no == computer_no
            and d.requested_by == user_id
            and d.status is DraftStatus.DRAFT
        ]

    def _own_draft(self, computer_no: str, draft_id: str, user_id: str) -> Draft:
        """Unknown, someone else's, already confirmed/discarded and unreachable file all give the
        same error (no existence leak)."""
        d = next((x for x in self.my_drafts(computer_no, user_id) if x.draft_id == draft_id), None)
        if d is None:
            raise ConnectorError("draft not available")
        return d

    def save_draft(self, computer_no: str, draft_id: str, user_id: str, text: str) -> Draft:
        """The officer edits their draft: a new version, the earlier ones kept."""
        d = self._own_draft(computer_no, draft_id, user_id)
        v = NoteVersion(
            version=len(d.versions) + 1, text=text, saved_at=self._clock(), saved_by=user_id
        )
        saved = d.model_copy(update={"versions": [*d.versions, v]})
        self.drafts[draft_id] = saved
        return saved

    def _next_paragraph(self, computer_no: str) -> tuple[int, int]:
        notes = self.notes(computer_no)
        if not notes:
            return 1, 1
        last = notes[-1]
        nums = [int(m) for m in re.findall(r"(?m)^\s*(\d+)\.", last.versions[-1].text or "")]
        nxt = max([last.paragraph_from, *nums]) + 1
        return last.note_no + 1, nxt

    def confirm_yellow_note(self, computer_no: str, draft_id: str, user_id: str) -> DraftOutcome:
        """The officer confirms their Yellow Note: it becomes the next Green Note, immutable, under
        their name and post (a simulated click — no DSC/eSign). The AI watermark goes, since the
        note is now theirs. Only Yellow Notes are confirmed here; DFA drafts follow e-Office's own
        approval chain, which this sandbox does not simulate."""
        d = self._own_draft(computer_no, draft_id, user_id)
        if d.kind != DraftKind.YELLOW_NOTE.value:
            raise ValueError("only a Yellow Note is confirmed here")
        p = self.profile(user_id)
        now = self._clock()
        ai_text = d.versions[0].text or ""
        final = strip_watermark(d.versions[-1].text or "")
        if not final:
            raise ValueError("an empty note cannot be confirmed")
        note_no, para = self._next_paragraph(computer_no)
        note_id = f"MOCK-NOTE-{next(self._seq):05d}"
        note = Note(
            note_id=note_id,
            computer_no=computer_no,
            note_no=note_no,
            paragraph_from=para,
            state=NoteState.GREEN,
            author=user_id,
            author_post=p.post,
            versions=[
                *d.versions,
                NoteVersion(
                    version=len(d.versions) + 1, text=final, saved_at=now, saved_by=user_id
                ),
            ],
            confirmed_at=now,
            created_by_assistant=d.created_by_assistant,
        )
        self._notes = sorted([*self._notes, note], key=lambda n: (n.computer_no, n.note_no))
        self.drafts[draft_id] = d.model_copy(
            update={"status": DraftStatus.CONFIRMED, "note_id": note_id}
        )
        self._events.append(
            EOfficeEvent(
                event_id=f"MOCK-EV-{next(self._seq):05d}",
                kind=EventKind.NOTE_CONFIRMED,
                occurred_at=now,
                computer_no=computer_no,
                object_id=note_id,
                source_uri=f"sandbox://notes/{note_id}",
            )
        )
        return DraftOutcome(
            draft_id=draft_id,
            kind=DraftKind.YELLOW_NOTE,
            computer_no=computer_no,
            request_id=d.request_id,
            user_id=user_id,
            outcome=DraftOutcomeKind.CONFIRMED,
            note_id=note_id,
            edit_share=edit_share(ai_text, final) if d.created_by_assistant else None,
            at=now,
        )

    def discard_draft(self, computer_no: str, draft_id: str, user_id: str) -> DraftOutcome:
        """The officer throws their draft away. Kept (status discarded), never shown again."""
        d = self._own_draft(computer_no, draft_id, user_id)
        now = self._clock()
        self.drafts[draft_id] = d.model_copy(update={"status": DraftStatus.DISCARDED})
        return DraftOutcome(
            draft_id=draft_id,
            kind=DraftKind(d.kind),
            computer_no=computer_no,
            request_id=d.request_id,
            user_id=user_id,
            outcome=DraftOutcomeKind.DISCARDED,
            at=now,
        )


def load_seed(path: Path) -> Seed:
    """Load a sandbox seed; refuses anything not marked synthetic (CLAUDE.md §11.10)."""
    seed = Seed.model_validate_json(path.read_text(encoding="utf-8"))
    if not seed.synthetic or seed.banner != BANNER:
        raise ConnectorError("seed is not marked as synthetic sandbox data")
    return seed


def merge_seeds(*seeds: Seed) -> Seed:
    """One sandbox from several synthetic seeds (v1 + v2, ADR-0020). Refuses any clash of officer,
    file, note, page or receipt identifiers: a merged seed must never let one set's officer reach
    the other's file by accident of a shared ID."""
    if not seeds:
        raise ConnectorError("no seed")
    if len(seeds) == 1:
        return seeds[0]

    def unique(kind: str, ids: list[str]) -> None:
        if len(ids) != len(set(ids)):
            raise ConnectorError(f"seeds clash on {kind} identifiers")

    unique("officer", [p.user_id for s in seeds for p in s.profiles])
    unique(
        "file",
        [f.computer_no for s in seeds for f in s.files]
        + [r.computer_no for s in seeds for r in s.receipts],
    )
    unique("file number", [f.file_no for s in seeds for f in s.files])
    unique("note", [n.note_id for s in seeds for n in s.notes])
    unique("page", [c.correspondence_id for s in seeds for c in s.correspondence])
    assignments: dict[str, list[str]] = {}
    for s in seeds:
        for u, fs in s.assignments.items():
            assignments.setdefault(u, []).extend(fs)
    return Seed(
        synthetic=all(s.synthetic for s in seeds),
        banner=seeds[0].banner if all(s.banner == seeds[0].banner for s in seeds) else "",
        corpus="+".join(s.corpus for s in seeds),
        as_of=max(s.as_of for s in seeds),
        sources=tuple(x for s in seeds for x in s.sources),
        profiles=[p for s in seeds for p in s.profiles],
        assignments=assignments,
        files=[f for s in seeds for f in s.files],
        notes=[n for s in seeds for n in s.notes],
        correspondence=[c for s in seeds for c in s.correspondence],
        movements=[m for s in seeds for m in s.movements],
        receipts=[r for s in seeds for r in s.receipts],
    )


def adapter_from_seed(
    seed: Seed,
    now: dt.datetime | None = None,
    artefacts: Iterable[SourceArtefact] = (),
    holdback: Iterable[str] = (),
    arrivals: Iterable[SourceArtefact] = (),
) -> MockEOfficeAdapter:
    return MockEOfficeAdapter(
        seed.profiles,
        seed.files,
        seed.movements,
        assignments={u: frozenset(f) for u, f in seed.assignments.items()},
        now=now,
        notes=seed.notes,
        correspondence=seed.correspondence,
        artefacts=artefacts,
        receipts=seed.receipts,
        holdback=holdback,
        arrivals=arrivals,
    )
