"""Conflict type C — procedural / wrong authority / missing concurrence (plan §6.2, §6.4).

Deterministic: a proposal's structured facts (action, post level, amount, proposed approving
authority, concurrences obtained) are checked against approval-authority rules held in config
(`data/ontology/authority_rules.yaml`, mock, [To confirm]). The LLM never decides who is
competent; at most it later helps fill the facts, which are then shown with their evidence.

- A rule applies only from its source's date (`effective_from`) and to the matching action,
  post level and amount band.
- Flags cite only rule sources the officer may see; if none are visible, the flag is still raised
  but marked uncertain with no citation (never revealing a restricted rule's text).
- Coverage (owner decision, 4 Nov 2026): every check returns one of three outcomes —
  CONFLICT, NO_CONFLICT_VERIFIED (only when the rule set for that department and action is
  verified AND complete) or REVIEW_NEEDED (not enough rule coverage to tell). "No matching rule"
  never reads as approval. With unverified rules (all mock rules) flags are uncertain and carry a
  caveat: mock rules test the mechanism, they are not approval guidance.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Collection
from decimal import Decimal
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.conflict.deterministic import ConflictFlag, ConflictType
from app.identifiers.canonical import parse_canonical_id


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Action(StrEnum):
    TRANSFER = "transfer"
    WORKS_SANCTION = "works_sanction"
    OUTSOURCING = "outsourcing"
    RECRUITMENT = "recruitment"  # who recruits / issues the notification
    REAPPROPRIATION = "reappropriation"  # re-appropriation / additional funds
    BUSINESS_ALLOCATION = "business_allocation"  # which department administers a subject


class PostLevel(StrEnum):
    STAFF = "staff"  # Section Officer and below
    OFFICER = "officer"  # Assistant Secretary and above


class Labelled(_Frozen):
    code: str = Field(pattern=r"^[A-Z_]+$")
    label: str
    aliases: tuple[str, ...] = ()


class RuleSource(_Frozen):
    id: str  # clause-level canonical ID
    text: str

    @model_validator(mode="after")
    def _clause(self) -> RuleSource:
        if not parse_canonical_id(self.id).clause:
            raise ValueError(f"rule source must be clause-level: {self.id}")
        return self

    @property
    def document_id(self) -> str:
        return parse_canonical_id(self.id).document_id


class BarredPeriod(_Frozen):
    """A part of every year in which the action may not be granted ("no request … will be
    entertained in the first two quarters"): month-day bounds, inclusive."""

    from_month_day: str = Field(pattern=r"^\d{2}-\d{2}$")
    to_month_day: str = Field(pattern=r"^\d{2}-\d{2}$")

    def covers(self, day: dt.date) -> bool:
        return self.from_month_day <= day.strftime("%m-%d") <= self.to_month_day


class AuthorityRule(_Frozen):
    id: str
    action: Action
    departments: tuple[str, ...] = ()  # departments whose proposals it governs; empty = any
    subject_terms: tuple[str, ...] = ()  # applies only when the proposal names one of these
    post_level: PostLevel | None = None
    amount_max: int | None = None  # rupees, inclusive
    amount_min_exclusive: int | None = None
    competent: tuple[str, ...] = ()
    recommend_only: tuple[str, ...] = ()
    requires_concurrence: tuple[str, ...] = ()
    barred: BarredPeriod | None = None
    effective_from: dt.date
    effective_until: dt.date | None = None  # e.g. an order for one financial year
    sources: tuple[RuleSource, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _says_something(self) -> AuthorityRule:
        if not (self.competent or self.requires_concurrence or self.barred):
            raise ValueError(f"rule {self.id} states no authority, concurrence or barred period")
        return self

    def names(self, text: str) -> bool:
        """True when the rule has no subject terms, or `text` contains one (case-insensitive)."""
        low = text.lower()
        return not self.subject_terms or any(t.lower() in low for t in self.subject_terms)


class RuleSetStatus(StrEnum):
    MOCK = "mock"  # testing only
    VERIFIED = "verified"  # authoritative, current rules collected and checked


class Coverage(_Frozen):
    department: str
    action: Action
    verified: bool
    complete: bool
    verified_by: str | None = None
    verified_on: dt.date | None = None
    note: str = ""

    @model_validator(mode="after")
    def _evidence(self) -> Coverage:
        if (self.verified or self.complete) and not (self.verified_by and self.verified_on):
            raise ValueError(f"coverage {self.department}/{self.action} verified without who/when")
        return self


class AuthorityRules(_Frozen):
    version: str
    status: RuleSetStatus
    coverage: tuple[Coverage, ...] = ()
    authorities: tuple[Labelled, ...]
    concurrences: tuple[Labelled, ...]
    post_levels: dict[PostLevel, tuple[str, ...]]
    rules: tuple[AuthorityRule, ...]

    @model_validator(mode="after")
    def _known_codes(self) -> AuthorityRules:
        auth = {a.code for a in self.authorities}
        conc = {c.code for c in self.concurrences}
        for r in self.rules:
            unknown = (set(r.competent) | set(r.recommend_only)) - auth
            if unknown or set(r.requires_concurrence) - conc:
                raise ValueError(f"rule {r.id} uses unknown codes {sorted(unknown)}")
        if len({r.id for r in self.rules}) != len(self.rules):
            raise ValueError("duplicate rule id")
        if self.status is RuleSetStatus.MOCK and any(
            c.verified or c.complete for c in self.coverage
        ):
            raise ValueError("a mock rule set cannot declare verified or complete coverage")
        return self

    def covered(self, department: str, action: Action) -> bool:
        """True only for a verified rule set whose coverage of (department, action) is verified
        and complete."""
        return self.status is RuleSetStatus.VERIFIED and any(
            c.department == department and c.action is action and c.verified and c.complete
            for c in self.coverage
        )

    def label(self, code: str) -> str:
        return next(
            (a.label for a in (*self.authorities, *self.concurrences) if a.code == code), code
        )

    def level_of(self, post: str) -> PostLevel | None:
        """'Senior Assistant, Regional Office' → STAFF. Longest match wins; unknown → None."""
        p = post.lower()
        hits = [
            (len(name), lvl)
            for lvl, names in self.post_levels.items()
            for name in names
            if re.search(rf"\b{re.escape(name)}\b", p)
        ]
        return max(hits)[1] if hits else None


def load_authority_rules(path: Path) -> AuthorityRules:
    with path.open(encoding="utf-8") as fh:
        return AuthorityRules.model_validate(yaml.safe_load(fh))


class ProposalFacts(_Frozen):
    """Structured facts of one proposal (a draft note). Each fact keeps the words it came from."""

    proposal_id: str  # canonical ID of the note
    department: str  # department whose rules govern the proposal
    action: Action
    proposal_date: dt.date
    post_level: PostLevel | None = None
    amount_rupees: int | None = Field(default=None, ge=0)
    proposed_authority: str | None = None  # authority code the note asks to approve
    concurrences_obtained: frozenset[str] = frozenset()
    grants: bool = False  # the proposal supports granting the request (read from its own words)
    subject: str = ""  # the note's subject, for rules limited to named subjects
    evidence: str = ""  # the note's own words for these facts


_AMOUNT = re.compile(r"Rs\.?\s*([\d,]+(?:\.\d+)?)\s*(crores?|lakhs?|lakh)?", re.I)


def parse_amount(text: str) -> int | None:
    """'Rs.1.30 crore' → 13000000; 'Rs.84.50 lakhs' → 8450000; plain 'Rs.25,000' → 25000."""
    m = _AMOUNT.search(text)
    if not m:
        return None
    value = Decimal(m.group(1).replace(",", ""))
    unit = (m.group(2) or "").lower()
    mult = 10_000_000 if unit.startswith("crore") else 100_000 if unit.startswith("lakh") else 1
    return int(value * mult)


def _applies(rule: AuthorityRule, f: ProposalFacts) -> bool:
    if rule.action is not f.action or f.proposal_date < rule.effective_from:
        return False
    if rule.effective_until is not None and f.proposal_date > rule.effective_until:
        return False
    if rule.departments and f.department not in rule.departments:
        return False
    if not rule.names(f"{f.subject} {f.evidence}"):
        return False
    if rule.post_level is not None and rule.post_level is not f.post_level:
        return False
    if rule.amount_max is not None and (
        f.amount_rupees is None or f.amount_rupees > rule.amount_max
    ):
        return False
    return not (
        rule.amount_min_exclusive is not None
        and (f.amount_rupees is None or f.amount_rupees <= rule.amount_min_exclusive)
    )


class AuthorityOutcome(StrEnum):
    CONFLICT = "conflict"
    NO_CONFLICT_VERIFIED = "no_conflict_verified"  # verified, complete rule set: nothing violated
    REVIEW_NEEDED = "review_needed"  # not enough rule coverage to tell


UNVERIFIED_CAVEAT = (
    " Caution: the approval rules for this action are not verified as complete; treat this as a "
    "prompt to check, not as approval guidance."
)
NO_COVERAGE_MESSAGE = (
    "Approval authority could not be checked: the rules for this action are not verified as "
    "complete. Review needed — confirm the competent authority before approval."
)


class AuthorityResult(_Frozen):
    outcome: AuthorityOutcome
    flags: tuple[ConflictFlag, ...] = ()
    rules_verified: bool
    message: str | None = None


def _flag(
    rule: AuthorityRule,
    facts: ProposalFacts,
    shown: tuple[RuleSource, ...],
    explanation: str,
    verified: bool,
) -> ConflictFlag:
    return ConflictFlag(
        type=ConflictType.C,
        cited=rule.id,
        evidence_ids=tuple(dict.fromkeys(src.document_id for src in shown)),
        explanation=explanation if verified else explanation + UNVERIFIED_CAVEAT,
        dates={"proposal_date": facts.proposal_date, "rule_effective_from": rule.effective_from},
        certain=bool(shown) and verified,  # unverified rules or no visible source → uncertain
    )


def check_authority(
    facts: ProposalFacts, rules: AuthorityRules, visible_documents: Collection[str]
) -> AuthorityResult:
    """Type C for one proposal (plan §6.2). `visible_documents`: canonical IDs the officer may see
    (the authorised set), used only to decide which rule sources may be cited."""
    verified = rules.covered(facts.department, facts.action)
    flags: list[ConflictFlag] = []
    for rule in (r for r in rules.rules if _applies(r, facts)):
        shown = tuple(s for s in rule.sources if s.document_id in visible_documents)
        quote = f' ("{shown[0].text}")' if shown else ""
        where = f" under {', '.join(s.id for s in shown)}" if shown else ""
        competent = " or ".join(rules.label(c) for c in rule.competent)
        p = facts.proposed_authority
        if rule.competent and p is not None and p not in rule.competent:
            if rule.action is Action.BUSINESS_ALLOCATION:
                text = (
                    f"Potential conflict — the proposal treats {rules.label(p)} as the "
                    f"department concerned; the subject is allotted to {competent}{where}{quote}. "
                    f"Review recommended: route the matter to {competent}."
                )
            else:
                role = (
                    "can only recommend"
                    if p in rule.recommend_only
                    else "is not the competent authority"
                )
                text = (
                    f"Potential conflict — the proposal seeks approval by {rules.label(p)}, "
                    f"who {role}; the competent authority is {competent}{where}{quote}. "
                    f"Review recommended: submit to {competent}."
                )
            flags.append(_flag(rule, facts, shown, text, verified))
        if rule.barred is not None and facts.grants and rule.barred.covers(facts.proposal_date):
            text = (
                "Potential conflict — the proposal supports the request on "
                f"{facts.proposal_date:%d-%m-%Y}, inside the period in which such requests are "
                f"not to be entertained{where}{quote}. Review recommended."
            )
            flags.append(_flag(rule, facts, shown, text, verified))
        missing = [c for c in rule.requires_concurrence if c not in facts.concurrences_obtained]
        if missing:
            need = " and ".join(rules.label(c) for c in missing)
            text = (
                f"Potential conflict — the proposal proceeds without the {need}, which is "
                f"required{where}{quote}. Review recommended: obtain it before approval."
            )
            flags.append(_flag(rule, facts, shown, text, verified))
    if flags:
        return AuthorityResult(
            outcome=AuthorityOutcome.CONFLICT, flags=tuple(flags), rules_verified=verified
        )
    if verified:
        return AuthorityResult(outcome=AuthorityOutcome.NO_CONFLICT_VERIFIED, rules_verified=True)
    return AuthorityResult(
        outcome=AuthorityOutcome.REVIEW_NEEDED, rules_verified=False, message=NO_COVERAGE_MESSAGE
    )
