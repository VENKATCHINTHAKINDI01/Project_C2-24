"""Mock e-Office seed (plan §11.6): synthetic, reproducible, no answer keys, access-correct."""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.auth.models import DocumentAccessTags
from app.auth.policy import check
from app.auth.store import InMemoryAuthzStore
from app.config import REPO_ROOT
from app.connectors.eoffice import ConnectorError, grants_from_context
from app.eoffice_mock.adapter import adapter_from_seed, load_seed
from app.eoffice_mock.models import TextSource
from tests.unit.mock_access import CLASSES, POLICY

SEED_PATH = REPO_ROOT / "data" / "synthetic" / "mock_v1" / "eoffice" / "seed.json"
GENERATOR = REPO_ROOT / "data" / "synthetic" / "tools" / "build_eoffice_seed.py"
SEED = load_seed(SEED_PATH)
NOW = dt.datetime(2026, 10, 2, 10, 0, tzinfo=dt.UTC)
PROFILE_IDS = {p.user_id for p in SEED.profiles}
FILES = {f.computer_no: f for f in SEED.files}


def test_seed_is_up_to_date_with_its_generator() -> None:
    res = subprocess.run(  # noqa: S603 — fixed local script, no user input
        [sys.executable, str(GENERATOR), "--check"], capture_output=True, text=True, check=False
    )
    assert res.returncode == 0, res.stderr


def test_seed_counts_and_labels() -> None:
    assert SEED.synthetic and "not NIC e-Office" in SEED.banner
    assert len([p for p in SEED.profiles if p.login]) == 8
    assert len(SEED.files) == 13 and len(SEED.receipts) == 10
    assert any("eFile 7.0 User Manual" in s for s in SEED.sources)


def test_seed_holds_no_answer_keys() -> None:
    """Relations, conflicts, decisions and golden answers stay in ground_truth/ (CLAUDE.md §9.2)."""
    raw = SEED_PATH.read_text(encoding="utf-8")
    for key in ("planted", "conflict", "SUPERSEDES", "CITES", "relations", "golden", "decision"):
        assert key not in raw, key


def test_every_actor_is_a_profile_and_staff_posts_cannot_log_in() -> None:
    actors = {n.author for n in SEED.notes} | {
        u for m in SEED.movements for u in (m.from_user, m.to_user)
    }
    actors |= {f.created_by for f in SEED.files if f.created_by}
    assert actors <= PROFILE_IDS
    for p in SEED.profiles:
        if not p.login:
            assert p.user_id.startswith("POST-") and {s.value for s in p.search_scopes} == {
                "individual"
            }


def test_scanned_notes_have_no_text_native_notes_do() -> None:
    for n in SEED.notes:
        text = n.versions[0].text
        if n.text_source is TextSource.NEEDS_OCR:
            assert text is None, n.note_id
        else:
            assert text and text.strip(), n.note_id
    assert {n.note_id for n in SEED.notes if n.text_source is TextSource.NEEDS_OCR} == {
        "2601155-N6",
        "2601155-N7",
        "2601155-N8",
    }


def test_receipt_numbers_follow_the_efile_format_and_numbers_are_unique() -> None:
    """eFile 7.0 manual: Receipt No. = sequence no./creation year/dealing section."""
    for r in SEED.receipts:
        seq, year, section = r.receipt_no.split("/")
        assert seq.isdigit() and year == str(r.diary_date.year) and section == r.dealing_section
        assert "diary_date" in r.assumed_fields
    numbers = [f.computer_no for f in SEED.files] + [r.computer_no for r in SEED.receipts]
    assert len(numbers) == len(set(numbers))


def test_movements_follow_consecutive_notes_only() -> None:
    notes = {(n.computer_no, n.note_no): n for n in SEED.notes}
    for m in SEED.movements:
        sent = [n for (c, _), n in notes.items() if c == m.computer_no and n.author == m.from_user]
        assert any(
            (m.computer_no, n.note_no + 1) in notes
            and notes[(m.computer_no, n.note_no + 1)].author == m.to_user
            for n in sent
        )
    vig = [(m.from_user, m.to_user) for m in SEED.movements if m.computer_no == "2601155"]
    assert ("U06", "U04") not in vig  # no movement invented across the missing notes #4–#5


def test_files_match_the_corpus_numbering() -> None:
    for f in SEED.files:
        assert re.fullmatch(r"USD01-[A-Z0-9]+/\d+/\d{4}-[A-Z.]+", f.file_no), f.file_no
        assert f.file_head == f.file_no.split("/")[0]
    assert {f.computer_no for f in SEED.files if f.created_by is None} == {
        "1311050",
        "2620051",
        "2671408",
    }


# ---- the seeded sandbox respects e-Office reach and C2-24 access control -------------------


@pytest.fixture(scope="module")
def adapter():  # type: ignore[no-untyped-def]
    return adapter_from_seed(SEED, now=NOW)


def test_section_officer_reaches_own_section_file_not_vigilance(adapter) -> None:  # type: ignore[no-untyped-def]
    assert adapter.file_context("2894562", "U01").file_no == "USD01-12/19/2026-ESTT.I"
    with pytest.raises(ConnectorError) as hidden:
        adapter.file_context("2601155", "U01")
    with pytest.raises(ConnectorError) as absent:
        adapter.file_context("0000000", "U01")
    assert str(hidden.value) == str(absent.value)


def test_movement_trail_and_assignments_come_through(adapter) -> None:  # type: ignore[no-untyped-def]
    ctx = adapter.officer_context("U04")
    assert "USD01-31/4/2025-VIG" in ctx.handled_files  # U04 signed notes in the Vigilance file
    assert "USD01-12/58/2025-ESTT.I" in ctx.assigned_files
    trail = adapter.file_context("2601155", "U05").movement_trail
    assert trail == ("U04", "U05", "U06")


def test_seeded_profiles_feed_the_access_store(adapter) -> None:  # type: ignore[no-untyped-def]
    store = InMemoryAuthzStore()
    for uid in sorted(p.user_id for p in SEED.profiles if p.login):
        store.write(grants_from_context(adapter.officer_context(uid)))
    vig = DocumentAccessTags(
        doc_id="D21",
        department="USD01",
        section="VIG",
        classification="CONFIDENTIAL",
        file_no="USD01-31/4/2025-VIG",
    )
    allowed = {u for u in sorted(PROFILE_IDS) if u.startswith("U")}
    allowed = {u for u in allowed if check(u, vig, store, POLICY, CLASSES).allowed}
    assert allowed == {"U04", "U05", "U06"}


def test_load_seed_refuses_unlabelled_data(tmp_path: Path) -> None:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    data["synthetic"] = False
    bad = tmp_path / "seed.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ConnectorError):
        load_seed(bad)
