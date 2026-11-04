"""In-memory mock adapter for `EOfficeConnector` — SYNTHETIC sandbox, not NIC e-Office (plan §11.3).

Holds sandbox objects in memory; the Cloud SQL `eoffice_mock` schema replaces the store later
without changing the connector contract.
"""

from __future__ import annotations

import datetime as dt
import itertools
from collections.abc import Iterable
from pathlib import Path

from app.connectors.eoffice import (
    ConnectorError,
    DraftKind,
    DraftReceipt,
    DraftRequest,
    EOfficeEvent,
    EventKind,
    FileContext,
    OfficerContext,
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
    NoteVersion,
    Receipt,
    SandboxProfile,
    Seed,
)


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
            previous_references=tuple(f.previous_references),
            later_references=tuple(f.later_references),
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

    # ---- sandbox screens (e-Office side; not part of the connector contract) ----------------

    def profiles(self) -> list[SandboxProfile]:
        """Officers who can sign in to the sandbox (posts without a login are excluded)."""
        return [p for p in self._profiles.values() if p.login]

    def profile(self, user_id: str) -> SandboxProfile:
        p = self._profile(user_id)
        if not p.login:
            raise ConnectorError("unknown officer")
        return p

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
        )
        return DraftReceipt(
            draft_id=draft_id, kind=request.kind, computer_no=request.computer_no, created_at=now
        )


def load_seed(path: Path) -> Seed:
    """Load a sandbox seed; refuses anything not marked synthetic (CLAUDE.md §11.10)."""
    seed = Seed.model_validate_json(path.read_text(encoding="utf-8"))
    if not seed.synthetic or seed.banner != BANNER:
        raise ConnectorError("seed is not marked as synthetic sandbox data")
    return seed


def adapter_from_seed(
    seed: Seed,
    now: dt.datetime | None = None,
    artefacts: Iterable[SourceArtefact] = (),
    holdback: Iterable[str] = (),
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
    )
