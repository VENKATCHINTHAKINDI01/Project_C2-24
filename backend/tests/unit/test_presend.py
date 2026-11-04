"""Pre-send check (touchpoint 11): facts from note text + A/C/E/F together (plan §6.2, §11.5).

Expected types come from ground_truth/conflicts.json, restricted to the deterministic ones.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.conflict.deterministic import ConflictType
from app.conflict.facts import extract_proposal_facts
from app.conflict.presend import PreSendOutcome, presend_check
from app.conflict.procedural import Action, AuthorityOutcome, PostLevel
from app.ingestion.detect import detect_file
from app.ingestion.extract import extract_native
from app.ingestion.metadata import DocumentMetadata, extract_metadata
from app.temporal.windows import windows_from_text
from tests.unit.mock_access import CLASSES, CORPUS, POLICY, doc_tags, new_store
from tests.unit.test_agent_tools_and_memory import INSTRUMENTS, RELS
from tests.unit.test_conflict_procedural import FACTS, RULES, _verified
from tests.unit.test_ingestion_pipeline import DEPTS, IDX

TAGS = {IDX[d]["canonical_id"]: t for d, t in doc_tags().items()}
CONFLICTS = json.loads((CORPUS / "ground_truth" / "conflicts.json").read_text(encoding="utf-8"))
DETERMINISTIC = {"A", "C", "E", "F"}
# Action windows stated inside the orders (read the same way ingestion reads them).
WINDOWS = [
    w
    for d in ("D01", "D03", "D04")
    for w in windows_from_text(
        IDX[d]["canonical_id"], (CORPUS / "ground_truth" / "text" / f"{d}.txt").read_text("utf-8")
    )
]


def _note(did: str) -> tuple[str, DocumentMetadata]:
    path = Path(CORPUS / IDX[did]["file"])
    text = extract_native(path.read_bytes(), detect_file(path)).native_text
    return text, extract_metadata(text, DEPTS)


def _run(did: str, uid: str, rules=RULES):  # type: ignore[no-untyped-def]
    text, meta = _note(did)
    return presend_check(
        IDX[did]["canonical_id"],
        text,
        meta,
        user_id=uid,
        instruments=INSTRUMENTS,
        relations=list(RELS),
        tags_of=TAGS,
        rules=rules,
        store=new_store(),
        policy=POLICY,
        classification=CLASSES,
        windows=WINDOWS,
    )


@pytest.mark.parametrize("did", ["D27", "D28", "D29"])
def test_facts_read_from_the_note_match_the_hand_transcription(did: str) -> None:
    text, meta = _note(did)
    got = extract_proposal_facts(text, meta, RULES, IDX[did]["canonical_id"]).facts
    want = FACTS[did]
    assert got is not None
    for field in (
        "action",
        "post_level",
        "amount_rupees",
        "proposed_authority",
        "concurrences_obtained",
        "proposal_date",
        "department",
    ):
        assert getattr(got, field) == getattr(want, field), (did, field)


def test_facts_keep_their_evidence_and_report_gaps() -> None:
    text, meta = _note("D29")
    res = extract_proposal_facts(text, meta, RULES, "X")
    assert res.missing == ("proposed_authority",)  # "Orders may be issued by the Department"
    assert "Orders may be issued by the Department" in res.evidence["proposed_authority"]
    text27, meta27 = _note("D27")
    r27 = extract_proposal_facts(text27, meta27, RULES, "X")
    assert r27.facts is not None and r27.facts.action is Action.TRANSFER
    assert (
        r27.facts.post_level is PostLevel.STAFF
        and "Deputy Secretary may kindly approve" in r27.evidence["proposed_authority"]
    )


@pytest.mark.parametrize(("did", "uid"), [("D27", "U01"), ("D28", "U03"), ("D29", "U01")])
def test_presend_finds_every_deterministic_planted_conflict(did: str, uid: str) -> None:
    rep = _run(did, uid)
    expected = {c["type"] for c in CONFLICTS if c["in"] == did} & DETERMINISTIC
    got = {f.type.value for f in rep.flags}
    assert got == expected, (did, [f.explanation for f in rep.flags])
    assert rep.outcome is PreSendOutcome.CONFLICTS_FOUND


def test_mock_rules_make_type_c_an_uncertain_prompt() -> None:
    rep = _run("D27", "U01")
    c = [f for f in rep.flags if f.type is ConflictType.C]
    assert c and not any(f.certain for f in c) and rep.authority is not None
    assert not rep.authority.rules_verified


def test_status_never_assumed_in_force_without_coverage() -> None:
    """D28 cites the 2023 circular; the Works SO cannot see all of USD01 → status unconfirmed."""
    rep = _run("D28", "U03")
    assert "AP-USD01-CIRMEMO-USD01WRKS0-9-2023" in rep.status_unconfirmed


def test_a_clean_draft_is_review_needed_with_mock_rules_and_clear_only_when_verified() -> None:
    """D25's proposal (Rs.1.40 crore by Government, 2024) breaks no rule."""
    mock = _run("D25", "U06")
    assert not mock.flags and mock.outcome is PreSendOutcome.REVIEW_NEEDED
    verified = _run("D25", "U06", rules=_verified())
    assert (
        verified.authority is not None
        and verified.authority.outcome is AuthorityOutcome.NO_CONFLICT_VERIFIED
    )
    assert (
        verified.outcome is PreSendOutcome.CLEAR
    )  # Secretary covers USD01; rules verified (in-test copy)


def test_forbidden_citations_are_neither_checked_nor_named() -> None:
    """D20 cites the Vigilance file; the Assistant Secretary (sees D20, not Vigilance) learns
    nothing about it from the pre-send check."""
    rep = _run("D20", "U02")
    assert not any("USD0131" in f.cited or "VIG" in f.explanation for f in rep.flags)


def test_unknown_user_fails_closed_to_review() -> None:
    rep = _run("D27", "U99")
    assert rep.outcome is PreSendOutcome.REVIEW_NEEDED and rep.flags == ()
