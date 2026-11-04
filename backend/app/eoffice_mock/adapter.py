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
    FileContext,
    OfficerContext,
    SearchScope,
)
from app.eoffice_mock.models import (
    BANNER,
    Draft,
    DraftStatus,
    EFile,
    Movement,
    NoteVersion,
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
    ) -> None:
        self._profiles = {p.user_id: p for p in profiles}
        self._files = {f.computer_no: f for f in files}
        self._movements = sorted(movements, key=lambda m: (m.computer_no, m.seq))
        self._events = sorted(events, key=lambda e: e.occurred_at)
        self._assignments = assignments or {}
        self._now = now
        self._seq = itertools.count(1)
        self.drafts: dict[str, Draft] = {}

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

    def events_since(self, after: dt.datetime) -> list[EOfficeEvent]:
        return [e for e in self._events if e.occurred_at > after]

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


def adapter_from_seed(seed: Seed, now: dt.datetime | None = None) -> MockEOfficeAdapter:
    return MockEOfficeAdapter(
        seed.profiles,
        seed.files,
        seed.movements,
        assignments={u: frozenset(f) for u, f in seed.assignments.items()},
        now=now,
    )
