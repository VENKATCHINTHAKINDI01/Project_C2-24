"""Conflict type C against approval-authority rules (plan §6.2; owner decision 4 Nov 2026: rules
transcribed from mock orders). Facts are transcribed by hand from the notes, quoted below —
filling them automatically is a later step."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from pydantic import ValidationError

from app.config import REPO_ROOT
from app.conflict.deterministic import ConflictType
from app.conflict.procedural import (
    NO_COVERAGE_MESSAGE,
    UNVERIFIED_CAVEAT,
    Action,
    AuthorityOutcome,
    AuthorityRules,
    PostLevel,
    ProposalFacts,
    RuleSetStatus,
    check_authority,
    load_authority_rules,
    parse_amount,
)
from tests.unit.mock_access import CORPUS, MATRIX, rows

RULES = load_authority_rules(REPO_ROOT / "data" / "ontology" / "authority_rules.yaml")
CID = {r["id"]: r["canonical_id"] for r in rows("documents_index.csv")}
DOC = {v: k for k, v in CID.items()}
CONFLICTS = json.loads((CORPUS / "ground_truth" / "conflicts.json").read_text(encoding="utf-8"))
ALL = set(CID.values())

FACTS = {
    # "As the Secretary is on leave, the Deputy Secretary may kindly approve the transfer"
    "D27": ProposalFacts(
        department="USD01",
        proposal_id=CID["D27"],
        action=Action.TRANSFER,
        proposal_date=dt.date(2026, 9, 22),
        post_level=RULES.level_of("Senior Assistant, Regional Office, Eluru"),
        proposed_authority="DEPUTY_SECRETARY",
    ),
    # "proposed that the Commissioner may be permitted to accord the sanction" — Rs.1.30 crore
    "D28": ProposalFacts(
        department="USD01",
        proposal_id=CID["D28"],
        action=Action.WORKS_SANCTION,
        proposal_date=dt.date(2026, 9, 24),
        amount_rupees=parse_amount("Rs.1.30 crore"),
        proposed_authority="COMMISSIONER",
    ),
    # "reference to the Finance Department may not be necessary. Orders may be issued by the
    # Department." — no approving authority named, no concurrence
    "D29": ProposalFacts(
        department="USD01",
        proposal_id=CID["D29"],
        action=Action.OUTSOURCING,
        proposal_date=dt.date(2026, 8, 12),
    ),
    # clean cases
    "D19": ProposalFacts(
        department="USD01",
        proposal_id=CID["D19"],
        action=Action.TRANSFER,
        proposal_date=dt.date(2025, 5, 27),
        post_level=PostLevel.STAFF,
        proposed_authority="SECRETARY",
    ),
    "D24": ProposalFacts(
        department="USD01",
        proposal_id=CID["D24"],
        action=Action.WORKS_SANCTION,
        proposal_date=dt.date(2023, 8, 4),
        amount_rupees=parse_amount("Rs.1.20 crore"),
        proposed_authority="COMMISSIONER",
    ),
    "D25": ProposalFacts(
        department="USD01",
        proposal_id=CID["D25"],
        action=Action.WORKS_SANCTION,
        proposal_date=dt.date(2024, 10, 21),
        amount_rupees=parse_amount("Rs.1.40 crore"),
        proposed_authority="GOVERNMENT",
    ),
}


def _expected_c(did: str) -> list[set[str]]:
    return [set(c["evidence"]) for c in CONFLICTS if c["in"] == did and c["type"] == "C"]


def _verified(rules: AuthorityRules = RULES) -> AuthorityRules:
    """A VERIFIED copy, for testing the verified branch only — the real file stays mock."""
    cov = tuple(
        c.model_copy(
            update={
                "verified": True,
                "complete": True,
                "verified_by": "test",
                "verified_on": dt.date(2026, 11, 4),
            }
        )
        for c in rules.coverage
    )
    return rules.model_copy(update={"status": RuleSetStatus.VERIFIED, "coverage": cov})


VERIFIED = _verified()


@pytest.mark.parametrize("did", sorted(FACTS))
def test_mock_rules_find_the_answer_key_conflicts_but_only_as_uncertain_prompts(did: str) -> None:
    res = check_authority(FACTS[did], RULES, ALL)
    assert not res.rules_verified
    expected = _expected_c(did)
    if expected:
        assert res.outcome is AuthorityOutcome.CONFLICT
        assert len(res.flags) == len(expected)
        for f, ev in zip(res.flags, expected, strict=True):
            assert f.type is ConflictType.C and {DOC[e] for e in f.evidence_ids} == ev
            assert not f.certain and f.explanation.endswith(UNVERIFIED_CAVEAT)
    else:  # mock rules: "nothing matched" is never a clean pass
        assert res.outcome is AuthorityOutcome.REVIEW_NEEDED and res.flags == ()
        assert res.message == NO_COVERAGE_MESSAGE


@pytest.mark.parametrize("did", sorted(FACTS))
def test_verified_complete_rules_give_certain_flags_or_a_verified_clean_result(did: str) -> None:
    res = check_authority(FACTS[did], VERIFIED, ALL)
    assert res.rules_verified
    if _expected_c(did):
        assert res.outcome is AuthorityOutcome.CONFLICT and all(f.certain for f in res.flags)
        assert not any(UNVERIFIED_CAVEAT in f.explanation for f in res.flags)
    else:
        assert res.outcome is AuthorityOutcome.NO_CONFLICT_VERIFIED and res.message is None


def test_uncovered_department_or_action_needs_review_even_in_a_verified_set() -> None:
    other = FACTS["D19"].model_copy(update={"department": "FIN01"})
    res = check_authority(other, VERIFIED, ALL)
    assert res.outcome is AuthorityOutcome.REVIEW_NEEDED and not res.rules_verified


def test_a_mock_rule_set_cannot_claim_verified_coverage() -> None:
    raw = RULES.model_dump()
    raw["coverage"][0].update(
        verified=True, complete=True, verified_by="x", verified_on=dt.date(2026, 1, 1)
    )
    with pytest.raises(ValidationError):
        AuthorityRules.model_validate(raw)


def test_verified_coverage_must_say_who_and_when() -> None:
    raw = _verified().model_dump()
    raw["coverage"][0].update(verified_by=None)
    with pytest.raises(ValidationError):
        AuthorityRules.model_validate(raw)


def test_wording_is_advisory_and_names_the_competent_authority() -> None:
    (flag,) = check_authority(FACTS["D27"], VERIFIED, ALL).flags
    assert flag.explanation.startswith("Potential conflict")
    assert "Deputy Secretary, who can only recommend" in flag.explanation
    assert "Review recommended: submit to Secretary to Government." in flag.explanation
    (works,) = check_authority(FACTS["D28"], VERIFIED, ALL).flags
    assert "competent authority is Government" in works.explanation
    (outs,) = check_authority(FACTS["D29"], VERIFIED, ALL).flags
    assert "without the prior concurrence of the Finance Department" in outs.explanation


def test_rule_applies_only_from_its_source_date() -> None:
    later = FACTS["D24"].model_copy(update={"proposal_date": dt.date(2024, 9, 1)})
    assert check_authority(FACTS["D24"], VERIFIED, ALL).flags == ()  # 2023: G.O. not yet issued
    assert len(check_authority(later, VERIFIED, ALL).flags) == 1


def test_above_5_crore_needs_finance_concurrence_too() -> None:
    big = FACTS["D25"].model_copy(update={"amount_rupees": parse_amount("Rs.6.00 crore")})
    (flag,) = check_authority(big, VERIFIED, ALL).flags
    assert "concurrence of the Finance Department" in flag.explanation
    ok = big.model_copy(update={"concurrences_obtained": frozenset({"FINANCE"})})
    assert check_authority(ok, VERIFIED, ALL).outcome is AuthorityOutcome.NO_CONFLICT_VERIFIED


def test_officer_level_transfer_goes_to_gad() -> None:
    f = FACTS["D19"].model_copy(
        update={"post_level": RULES.level_of("Assistant Secretary (Estt.)")}
    )
    (flag,) = check_authority(f, VERIFIED, ALL).flags
    assert "General Administration (Ser.A) Department" in flag.explanation


def test_citations_only_from_sources_the_officer_can_see() -> None:
    """U03 (Works) cannot see the RESTRICTED Standing Order 2/2020: it is not cited for them."""
    visible = {cid for did, cid in CID.items() if MATRIX[(did, "U03")]}
    (flag,) = check_authority(FACTS["D27"], VERIFIED, visible).flags
    assert {DOC[e] for e in flag.evidence_ids} == {"D04", "D09"} and flag.certain
    assert "Standing Order" not in flag.explanation and "SO-2-2020" not in flag.explanation
    (blind,) = check_authority(FACTS["D27"], VERIFIED, set()).flags
    assert blind.evidence_ids == () and not blind.certain and '("' not in blind.explanation


def test_unknown_facts_need_review_not_a_pass() -> None:
    unknown_level = FACTS["D27"].model_copy(update={"post_level": None})
    res = check_authority(unknown_level, RULES, ALL)
    assert res.outcome is AuthorityOutcome.REVIEW_NEEDED


@pytest.mark.parametrize(
    ("text", "rupees"),
    [
        ("Rs.1.30 crore", 13_000_000),
        ("Rs.84.50 lakhs", 8_450_000),
        ("Rs.15.00 lakhs", 1_500_000),
        ("Rs.25,000", 25_000),
        ("no amount", None),
    ],
)
def test_parse_amount(text: str, rupees: int | None) -> None:
    assert parse_amount(text) == rupees


def test_post_levels() -> None:
    assert RULES.level_of("Senior Assistant, Regional Office") is PostLevel.STAFF
    assert RULES.level_of("Assistant Section Officer (Estt.I)") is PostLevel.STAFF  # longest match
    assert RULES.level_of("Deputy Secretary") is PostLevel.OFFICER
    assert RULES.level_of("Driver") is None


def test_rules_file_is_mock_testing_only_and_validated() -> None:
    assert RULES.status is RuleSetStatus.MOCK
    assert RULES.coverage and not any(c.verified or c.complete for c in RULES.coverage)
    raw = RULES.model_dump()
    raw["rules"][0]["competent"] = ["CHIEF_JUSTICE"]
    with pytest.raises(ValidationError):
        AuthorityRules.model_validate(raw)
