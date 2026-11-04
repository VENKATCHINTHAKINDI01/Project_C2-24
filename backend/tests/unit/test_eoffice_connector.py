"""EOfficeConnector contract + mock adapter (plan §11.1-§11.4). Fixtures are SYNTHETIC."""

from __future__ import annotations

import datetime as dt
import re

import pytest

from app.auth.models import DocumentAccessTags
from app.auth.policy import check, load_access_policy
from app.auth.store import InMemoryAuthzStore
from app.config import REPO_ROOT, load_classification
from app.connectors.eoffice import (
    ConnectorError,
    DraftKind,
    DraftRequest,
    EOfficeConnector,
    EOfficeEvent,
    EventKind,
    SearchScope,
    grants_from_context,
)
from app.eoffice_mock.adapter import MockEOfficeAdapter
from app.eoffice_mock.models import BANNER, EFile, Movement, SandboxProfile

NOW = dt.datetime(2026, 10, 2, 10, 0, tzinfo=dt.UTC)
S = SearchScope


def _profile(
    uid: str, rank: int, section: str | None, clearance: str, scopes: set[S]
) -> SandboxProfile:
    return SandboxProfile(
        user_id=uid,
        name=f"Officer {uid}",
        post="mock post",
        role_rank=rank,
        department="USD01",
        section=section,
        clearance=clearance,
        search_scopes=frozenset(scopes),
    )


PROFILES = [
    _profile("U01", 1, "ESTT.I", "RESTRICTED", {S.SECTION}),
    _profile("U03", 1, "WORKS", "RESTRICTED", {S.SECTION}),
    _profile("U04", 1, "VIG", "CONFIDENTIAL", {S.SECTION}),
    _profile("U05", 3, None, "CONFIDENTIAL", {S.DEPARTMENT}),
]
VIG_FILE = EFile(
    computer_no="1800001",
    file_no="USD01-31/4/2025-VIG",
    subject="Vigilance enquiry (synthetic)",
    department="USD01",
    dealing_section="VIG",
    category="Vigilance",
    classification="CONFIDENTIAL",
    created_by="U04",
    created_on=dt.date(2025, 4, 18),
)
ESTT_FILE = VIG_FILE.model_copy(
    update={
        "computer_no": "2894562",
        "file_no": "USD01-12/19/2026-ESTT.I",
        "subject": "Transfer request (synthetic)",
        "dealing_section": "ESTT.I",
        "category": "Establishment",
        "classification": "RESTRICTED",
        "created_by": "U01",
    }
)
MOVES = [
    Movement(computer_no="2894562", seq=1, from_user="U01", to_user="U05", sent_at=NOW),
]
EVENT = EOfficeEvent(
    event_id="E1",
    kind=EventKind.ORDER_RECEIVED,
    occurred_at=NOW,
    object_id="R1",
    source_uri="mock://receipts/R1.pdf",
)


@pytest.fixture
def adapter() -> MockEOfficeAdapter:
    return MockEOfficeAdapter(PROFILES, [VIG_FILE, ESTT_FILE], MOVES, [EVENT], now=NOW)


def _req(**kw: object) -> DraftRequest:
    base: dict[str, object] = {
        "kind": DraftKind.YELLOW_NOTE,
        "computer_no": "2894562",
        "requested_by": "U01",
        "officer_clicked": True,
        "body": "Draft note (synthetic).",
        "request_id": "REQ-1",
    }
    base.update(kw)
    return DraftRequest.model_validate(base)


def test_adapter_satisfies_protocol_and_is_labelled_mock(adapter: MockEOfficeAdapter) -> None:
    assert isinstance(adapter, EOfficeConnector)
    assert adapter.is_mock
    assert "not NIC e-Office" in BANNER and "synthetic" in BANNER


def test_section_officer_cannot_open_vigilance_file_and_gets_neutral_error(
    adapter: MockEOfficeAdapter,
) -> None:
    with pytest.raises(ConnectorError) as missing:
        adapter.file_context("9999999", "U01")
    with pytest.raises(ConnectorError) as hidden:
        adapter.file_context(VIG_FILE.computer_no, "U01")
    assert str(missing.value) == str(hidden.value)  # cannot tell "absent" from "not allowed"


def test_reach_by_section_department_and_movement(adapter: MockEOfficeAdapter) -> None:
    assert adapter.file_context(VIG_FILE.computer_no, "U04").dealing_section == "VIG"
    ctx = adapter.file_context(ESTT_FILE.computer_no, "U05")
    assert ctx.movement_trail == ("U01", "U05")
    with pytest.raises(ConnectorError):
        adapter.file_context(ESTT_FILE.computer_no, "U03")


def test_assignment_extends_reach() -> None:
    a = MockEOfficeAdapter(
        PROFILES, [ESTT_FILE], assignments={"U04": frozenset({ESTT_FILE.file_no})}, now=NOW
    )
    assert a.file_context(ESTT_FILE.computer_no, "U04").file_no == ESTT_FILE.file_no
    assert ESTT_FILE.file_no in a.officer_context("U04").assigned_files


def test_drafts_only_on_click_and_only_as_drafts(adapter: MockEOfficeAdapter) -> None:
    with pytest.raises(ConnectorError):
        adapter.create_draft(_req(officer_clicked=False))
    receipt = adapter.create_draft(_req())
    assert receipt.status == "draft"
    stored = adapter.drafts[receipt.draft_id]
    assert stored.status.value == "draft" and stored.created_by_assistant
    with pytest.raises(ConnectorError):  # cannot write into a file outside the officer's reach
        adapter.create_draft(_req(computer_no=VIG_FILE.computer_no))


def test_write_back_kinds_are_drafts_only() -> None:
    assert {k.value for k in DraftKind} == {"yellow_note", "dfa_draft", "suggested_reference"}
    with pytest.raises(ValueError):
        _req(kind="green_note")


def test_events_since(adapter: MockEOfficeAdapter) -> None:
    assert adapter.events_since(NOW - dt.timedelta(seconds=1)) == [EVENT]
    assert adapter.events_since(NOW) == []


def test_officer_context_feeds_authorization(adapter: MockEOfficeAdapter) -> None:
    onto = REPO_ROOT / "data" / "ontology"
    policy = load_access_policy(onto / "access_policy.yaml")
    classes = load_classification(onto / "classification.yaml")
    vig = DocumentAccessTags(
        doc_id="D21", department="USD01", section="VIG", classification="CONFIDENTIAL"
    )
    store = InMemoryAuthzStore()
    for uid in ("U01", "U04", "U05"):
        store.write(grants_from_context(adapter.officer_context(uid)))
    assert not check("U01", vig, store, policy, classes).allowed  # Section Officer, Estt.I
    assert check("U05", vig, store, policy, classes).allowed  # Deputy Secretary, Department scope
    assert check("U04", vig, store, policy, classes).allowed  # Vigilance section


def test_movement_trail_becomes_handled_files(adapter: MockEOfficeAdapter) -> None:
    ctx = adapter.officer_context("U05")
    assert ESTT_FILE.file_no in ctx.handled_files
    assert any(t.object == f"file:{ESTT_FILE.file_no}" for t in grants_from_context(ctx))


def test_core_modules_never_import_the_mock_sandbox() -> None:
    """CLAUDE.md §2.4: the sandbox reaches the core only through the connector."""
    app_dir = REPO_ROOT / "backend" / "app"
    pattern = re.compile(r"^\s*(from|import)\s+app\.eoffice_mock\b", re.M)
    offenders = [
        str(p.relative_to(app_dir))
        for p in app_dir.rglob("*.py")
        if "eoffice_mock" not in p.parts
        and p.name != "main.py"  # the composition root wires the adapter in; nothing else may
        and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []
