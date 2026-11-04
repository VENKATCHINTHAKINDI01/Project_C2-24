"""Proposal facts from a draft note, for conflict type C (plan §6.2; ADR-0010).

Deterministic patterns over the note's own words; every fact keeps the sentence it came from.
A fact that cannot be read is left empty and listed in `missing` — never guessed. Missing facts
make the type-C result "review needed" (owner rule, 4 Nov 2026), not a pass.

- action: from the subject (transfer · administrative sanction for works · outsourcing); several
  or none → unknown.
- post level (transfers): the post named in the subject, via the rules file's post levels.
- amount (works): "Rs.… crore/lakhs" in the subject, else in the proposal sentence.
- proposed authority: the LAST proposal sentence ("may (kindly) approve", "may be permitted to
  accord", "may be accorded by", "Orders may be issued by"); "by X" wins, else the authority named
  nearest before the verb. A body not in the rules file (e.g. "the Department") → unknown.
- concurrences obtained: only when the note says one was obtained / received / accorded.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from app.conflict.procedural import Action, AuthorityRules, ProposalFacts, parse_amount
from app.ingestion.metadata import DocumentMetadata


class FactsResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    facts: ProposalFacts | None  # None when the action itself is unknown
    evidence: dict[str, str]  # field → the note's words
    missing: tuple[str, ...]  # facts the rules need but the note does not state clearly


_ACTIONS = {
    Action.TRANSFER: re.compile(r"\btransfer", re.I),
    Action.WORKS_SANCTION: re.compile(r"administrative\s+sanction|\bworks?\b.*\bsanction", re.I),
    Action.OUTSOURCING: re.compile(r"outsourc|contract\s+(?:and|&)\s+outsourcing", re.I),
}
_PROPOSAL = re.compile(
    r"may\s+(?:kindly\s+)?approve|may\s+be\s+permitted\s+to\s+accord|may\s+be\s+accorded\s+by"
    r"|may\s+(?:kindly\s+)?(?:accord|sanction|order)\b|orders?\s+may\s+be\s+(?:issued|passed)\s+by",
    re.I,
)
_OBTAINED = re.compile(r"\b(?:obtained|received|accorded|has\s+concurred|concurred)\b", re.I)
_NEGATED = re.compile(r"\b(?:not|without|no)\b", re.I)


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    return [s.strip() for s in re.split(r"(?<=[.])\s+(?=\(?\d+\.|\(?[A-Z])", flat) if s.strip()]


def _mentions(sentence: str, rules: AuthorityRules) -> list[tuple[int, int, str]]:
    """Authority mentions as (start, end, code), longest alias first, non-overlapping."""
    found: list[tuple[int, int, str]] = []
    names = sorted(
        ((a, auth.code) for auth in rules.authorities for a in (auth.aliases or (auth.label,))),
        key=lambda x: -len(x[0]),
    )
    for alias, code in names:
        for m in re.finditer(rf"\b{re.escape(alias)}\b", sentence):
            if all(m.end() <= s or m.start() >= e for s, e, _ in found):
                found.append((m.start(), m.end(), code))
    return sorted(found)


def _proposed_authority(sentence: str, rules: AuthorityRules) -> str | None:
    trigger = list(_PROPOSAL.finditer(sentence))[-1]
    after_by = re.search(r"\bby\s+(?:the\s+)?", sentence[trigger.start() :], re.I)
    mentions = _mentions(sentence, rules)
    if after_by:
        start = trigger.start() + after_by.end()
        nxt = next((m for m in mentions if m[0] == start), None)
        return nxt[2] if nxt else None  # "by the Department" → not a known authority
    before = [m for m in mentions if m[1] <= trigger.start()]
    return before[-1][2] if before else None


def extract_proposal_facts(
    text: str, meta: DocumentMetadata, rules: AuthorityRules, proposal_id: str
) -> FactsResult:
    """`proposal_id`: the note's canonical ID as assigned at ingestion (notes carry no number)."""
    subject = meta.subject or ""
    evidence: dict[str, str] = {}
    missing: list[str] = []

    actions = [a for a, rx in _ACTIONS.items() if rx.search(subject)]
    if len(actions) != 1 or meta.issue_date is None or meta.department is None:
        missing.append("action" if len(actions) != 1 else "note identity/date/department")
        return FactsResult(facts=None, evidence={"subject": subject}, missing=tuple(missing))
    action = actions[0]
    evidence["action"] = subject

    post_level = None
    if action is Action.TRANSFER:
        post_level = rules.level_of(subject)
        if post_level is None:
            missing.append("post_level")
        else:
            evidence["post_level"] = subject

    sentences = _sentences(text)
    proposals = [s for s in sentences if _PROPOSAL.search(s)]
    proposal = proposals[-1] if proposals else None

    amount = None
    if action is Action.WORKS_SANCTION:
        amount = parse_amount(subject)
        evidence_src = subject
        if amount is None and proposal:
            amount, evidence_src = parse_amount(proposal), proposal
        if amount is None:
            missing.append("amount")
        else:
            evidence["amount"] = evidence_src

    authority = _proposed_authority(proposal, rules) if proposal else None
    if authority is None:
        missing.append("proposed_authority")
    if proposal:
        evidence["proposed_authority"] = proposal

    obtained: set[str] = set()
    for s in sentences:
        if "concurrence" not in s.lower() or not _OBTAINED.search(s) or _NEGATED.search(s):
            continue
        for c in rules.concurrences:
            if any(re.search(rf"\b{re.escape(a)}\b", s) for a in (c.aliases or (c.label,))):
                obtained.add(c.code)
                evidence[f"concurrence:{c.code}"] = s

    facts = ProposalFacts(
        proposal_id=proposal_id,
        department=meta.department,
        action=action,
        proposal_date=meta.issue_date,
        post_level=post_level,
        amount_rupees=amount,
        proposed_authority=authority,
        concurrences_obtained=frozenset(obtained),
        evidence=proposal or subject,
    )
    return FactsResult(facts=facts, evidence=evidence, missing=tuple(missing))
