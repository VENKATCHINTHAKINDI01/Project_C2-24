"""Citation verification against the evidence package (plan §8.2, §8.3; CLAUDE.md §7.6-§7.7).

Three outcomes per claim (owner decision, 3 Nov 2026). An uncertain claim is never presented as
a confirmed fact:

- CONFIRMED — every cited evidence ID is in the package, still authorised NOW (grants re-read),
  about the right record, and the cited text supports the claim. Shown normally.
- REVIEW_NEEDED — cited and authorised, but support cannot be determined: the claim has no number,
  date or quote to check deterministically, or a mismatch is against OCR'd / incomplete text where
  it may be a misreading. Shown only in a separate, labelled "Review needed" section.
- REJECTED — no citation, invented evidence ID, no longer authorised, wrong record, or the claim
  contradicts native (exact) cited text. Removed.

If nothing is confirmed but some claims need review, the review-needed evidence is returned with a
caveat instead of the generic no-answer. If nothing survives at all, the defined no-answer.
"""

from __future__ import annotations

import datetime as dt
import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.auth.models import AccessPolicy
from app.auth.policy import check
from app.auth.store import AuthzStore
from app.config import Classification
from app.retrieval.evidence import EvidenceItem, EvidencePackage, TextQuality

NO_ANSWER = "No sufficiently supported answer was found in the authorised records."
REVIEW_NOTE = "Review needed: the cited record could not be confirmed to support this statement."
REVIEW_CAVEAT = (
    "No statement could be confirmed against the authorised records. The items below cite "
    "records that may be relevant; each needs to be checked against its source before use."
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Claim(_Frozen):
    text: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    quote: str | None = None  # exact words relied on, if the drafter gives them
    about: str | None = None  # canonical ID the claim is about, if the drafter names one


class ClaimStatus(StrEnum):
    CONFIRMED = "confirmed"
    REVIEW_NEEDED = "review_needed"
    REJECTED = "rejected"


class ClaimResult(_Frozen):
    claim: Claim
    status: ClaimStatus
    reason: str
    missing_tokens: tuple[str, ...] = ()


class AnswerStatus(StrEnum):
    ANSWERED = "answered"  # ≥1 confirmed claim; review-needed ones in their own section
    REVIEW_NEEDED = "review_needed"  # nothing confirmed; review-needed evidence + caveat
    NO_ANSWER = "no_answer"


class Verification(_Frozen):
    request_id: str
    answer_status: AnswerStatus
    results: tuple[ClaimResult, ...]
    confirmed: tuple[Claim, ...]  # shown normally
    review_needed: tuple[Claim, ...]  # shown ONLY in the labelled "Review needed" section
    review_note: str = REVIEW_NOTE
    message: str | None = None  # caveat or no-answer text


_NUM = re.compile(
    r"\d{1,2}[-./]\d{1,2}[-./]\d{2,4}"  # dates
    r"|\d+(?:\.\d+)?\s*%"  # percentages
    r"|\d+(?:\.\d+)?"  # plain numbers, incl. "1.50"
)


def _norm(text: str) -> str:
    """Case, dashes and whitespace only. Spaces around a hyphen are dropped, so a date or number
    broken across a line in the source ("18-09-\n2026") matches its quote ("18-09-2026")."""
    t = re.sub(r"\s+", " ", text.replace("–", "-").replace("—", "-")).strip().lower()
    return re.sub(r" ?- ?", "-", t)


def _tokens(text: str) -> list[str]:
    return [re.sub(r"\s+", "", m.group(0)) for m in _NUM.finditer(text)]


def _date_forms(d: dt.date) -> set[str]:
    return (
        {f"{d:%d}{sep}{d:%m}{sep}{d:%Y}" for sep in "-./"}
        | {f"{d.day}{sep}{d.month}{sep}{d.year}" for sep in "-./"}
        | {f"{d:%Y}"}
    )


def _own_tokens(spans: list[EvidenceItem]) -> set[str]:
    """Numbers that identify a cited record itself, from the evidence package's own fields: the
    number and year in its canonical ID and its issue / effective dates (plan §7.2). A statement
    may name the record it cites ("G.O.Ms.No.27 dated 06-08-2024") although the passage quoted is
    from its body. A number of ANOTHER record is still checked against the cited text."""
    out: set[str] = set()
    for s in spans:
        out |= set(re.findall(r"\d+", s.canonical_id.split("#", 1)[0]))
        for d in (s.issue_date, s.effective_from, s.effective_to):
            if d is not None:
                out |= _date_forms(d)
    return out


def _support(claim: Claim, spans: list[EvidenceItem]) -> tuple[ClaimStatus, str, tuple[str, ...]]:
    exact = all(s.text_quality is TextQuality.NATIVE and not s.incomplete for s in spans)
    joined = " ".join(_norm(s.span_text) for s in spans)
    compact = re.sub(r"\s+", "", joined)
    mismatch = ClaimStatus.REJECTED if exact else ClaimStatus.REVIEW_NEEDED
    if claim.quote is not None and _norm(claim.quote) not in joined:
        why = (
            "quote contradicts the cited text" if exact else "quote not found in OCR'd/partial text"
        )
        return mismatch, why, ()
    tokens = _tokens(claim.text)
    own = _own_tokens(spans)
    missing = tuple(t for t in tokens if t.lower() not in compact and t.lower() not in own)
    if missing:
        why = (
            "numbers/dates contradict the cited text"
            if exact
            else ("numbers/dates not found in OCR'd/partial text")
        )
        return mismatch, why, missing
    if claim.quote is not None or tokens:
        return ClaimStatus.CONFIRMED, "supported by cited evidence", ()
    return ClaimStatus.REVIEW_NEEDED, "support cannot be determined deterministically", ()


def _judge(
    claim: Claim,
    package: EvidencePackage,
    store: AuthzStore,
    policy: AccessPolicy,
    classification: Classification,
) -> ClaimResult:
    def rejected(reason: str) -> ClaimResult:
        return ClaimResult(claim=claim, status=ClaimStatus.REJECTED, reason=reason)

    if not claim.evidence_ids:
        return rejected("no citation")
    items = [package.get(e) for e in claim.evidence_ids]
    spans = [i for i in items if i is not None]
    if len(spans) != len(items):
        return rejected("cites evidence outside the package")
    if not all(
        check(package.user_id, i.tags, store, policy, classification).allowed for i in spans
    ):
        return rejected("evidence no longer authorised")
    if any(i.addressed_to_ai for i in spans):  # plan §5.5: never state anything on its word
        return rejected("cites a passage with instructions addressed to an AI system")
    if claim.about is not None and claim.about not in {i.canonical_id for i in spans}:
        return rejected("cites a different record than the one the claim is about")
    status, reason, missing = _support(claim, spans)
    return ClaimResult(claim=claim, status=status, reason=reason, missing_tokens=missing)


def verify(
    package: EvidencePackage,
    claims: list[Claim],
    *,
    store: AuthzStore,
    policy: AccessPolicy,
    classification: Classification,
) -> Verification:
    """Plan §8.2 citation check. Authorization is re-read now, not trusted from package time."""
    results = tuple(_judge(c, package, store, policy, classification) for c in claims)
    confirmed = tuple(r.claim for r in results if r.status is ClaimStatus.CONFIRMED)
    review = tuple(r.claim for r in results if r.status is ClaimStatus.REVIEW_NEEDED)
    if confirmed:
        status, message = AnswerStatus.ANSWERED, None
    elif review:
        status, message = AnswerStatus.REVIEW_NEEDED, REVIEW_CAVEAT
    else:
        status, message = AnswerStatus.NO_ANSWER, NO_ANSWER
    return Verification(
        request_id=package.request_id,
        answer_status=status,
        results=results,
        confirmed=confirmed,
        review_needed=review,
        message=message,
    )
