"""How many matters of a kind were decided, and how (plan §13.3 "counts"; ADR-0051).

"How many spouse-ground transfer requests were rejected in 2025?" is answered by counting, not
by the model: the decided note files of that kind that THIS officer may see, by their final order
and the date it was signed. The count is computed only over the officer's authorised records, so
it never hints at a record they may not see (CLAUDE.md §4.6–4.7): a hidden rejection is simply not
in their count, and nothing says that anything was left out.

Deterministic throughout:
- the question: fixed patterns ("how many" / "number of"; outcome words; one year; the remaining
  words are the topic);
- which records: the L1 template (doc type Noting, every topic word in the subject) within the
  officer's scope, then `can_access` re-checked per record;
- the outcome: the LAST paragraph of the LAST note — the order of the officer who disposed of the
  file — read by fixed phrases ("Approved." / "Not agreed …" / "Not considered …"). A file whose
  last word is not an order ("Submitted.") is undecided and not counted. Never guessed.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.auth.models import Scope
from app.noting.chain import parse_notes
from app.retrieval.scoped import IndexedDocument, L1Criteria, ScopedRetriever


class Outcome(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


_COUNT_Q = re.compile(
    r"^\s*(?:how\s+many|what\s+(?:is|was)\s+the\s+number\s+of|number\s+of)\b", re.I
)
_ASKED_REJECTED = re.compile(
    r"\b(rejected|refused|declined|turned\s+down|not\s+(?:agreed|approved|considered|accepted))\b",
    re.I,
)
_ASKED_APPROVED = re.compile(r"\b(approved|allowed|sanctioned|granted|accepted|agreed)\b", re.I)
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")
# final orders: refusals first ("Not approved" contains "approved")
_ORDER_REFUSE = re.compile(
    r"\b(?:not\s+(?:agreed|approved|considered|accepted|permitted|allowed|sanctioned|acceded)"
    r"|rejected|declined|refused|regretted|negatived)\b",
    re.I,
)
_ORDER_ALLOW = re.compile(
    r"^\W*(?:approved|sanctioned|agreed|accepted|allowed|permitted|granted|orders?\s+issued)\b",
    re.I,
)
# words that say how / when / what is counted, not what the matter is
_NOT_TOPIC = frozenset(
    "how many what is was the number of were has have been did do does in on for a an and or to "
    "by from during year years between total all any so far till until request requests case "
    "cases matter matters file files application applications proposal proposals representation "
    "representations decided disposed".split()
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CountAsk(_Frozen):
    outcome: Outcome | None  # None: decided either way
    year: int | None
    topic: tuple[str, ...]  # every one must be in the record's subject


class Decided(_Frozen):
    canonical_id: str
    issue_date: dt.date | None
    outcome: Outcome
    decided_on: dt.date


class CountResult(_Frozen):
    ask: CountAsk
    decided: tuple[Decided, ...]  # every decided record of the topic the officer may see
    counted: tuple[Decided, ...]  # those with the asked outcome and year


def _word(w: str) -> str:
    w = w.lower()
    return w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w


def count_ask(question: str) -> CountAsk | None:
    """The count a question asks for, or None if it does not ask to count."""
    if not _COUNT_Q.search(question):
        return None
    rejected, approved = _ASKED_REJECTED.search(question), _ASKED_APPROVED.search(question)
    outcome = (
        Outcome.REJECTED if rejected else Outcome.APPROVED if approved and not rejected else None
    )
    years = set(_YEAR.findall(question))
    year = int(years.pop()) if len(years) == 1 else None
    rest = _ASKED_REJECTED.sub(" ", _ASKED_APPROVED.sub(" ", _YEAR.sub(" ", question)))
    topic = tuple(
        dict.fromkeys(
            _word(w)
            for w in re.findall(r"[A-Za-z]+", rest)
            if len(w) > 2 and w.lower() not in _NOT_TOPIC
        )
    )
    return CountAsk(outcome=outcome, year=year, topic=topic)


def final_order(text: str, source: str) -> tuple[Outcome, dt.date] | None:
    """The disposing officer's order: last paragraph of the last note, and when it was signed."""
    notes = parse_notes(text, source)
    if not notes or (signed := notes[-1].signed_at) is None:
        return None
    last = notes[-1]
    words = last.by_paragraph[-1][1] if last.by_paragraph else last.text
    words = re.sub(r"^\s*\d+\s*[.)]\s*", "", words).strip()  # "8. Approved." → "Approved."
    if _ORDER_REFUSE.search(words):
        return Outcome.REJECTED, signed.date()
    if _ORDER_ALLOW.search(words):
        return Outcome.APPROVED, signed.date()
    return None


def count_decisions(
    ask: CountAsk,
    scope: Scope,
    index: ScopedRetriever,
    texts: Mapping[str, str],
    may_see: Callable[[str], bool],
) -> CountResult:
    """Counts over the officer's authorised records only (scope in the L1 template, then the
    per-record re-check). A record whose text is not available to this officer is not counted."""
    found: Sequence[IndexedDocument] = index.filter(
        L1Criteria(doc_types=frozenset({"Noting"}), subject_terms=ask.topic), scope
    )
    decided: list[Decided] = []
    for d in found:
        if not may_see(d.canonical_id) or d.canonical_id not in texts:
            continue
        order = final_order(texts[d.canonical_id], d.canonical_id)
        if order is None:
            continue
        decided.append(
            Decided(
                canonical_id=d.canonical_id,
                issue_date=d.issue_date,
                outcome=order[0],
                decided_on=order[1],
            )
        )
    decided.sort(key=lambda x: (x.decided_on, x.canonical_id))
    in_year = [x for x in decided if ask.year is None or x.decided_on.year == ask.year]
    counted = [x for x in in_year if ask.outcome is None or x.outcome is ask.outcome]
    return CountResult(ask=ask, decided=tuple(in_year), counted=tuple(counted))


def sentence(r: CountResult) -> str:
    """One plain sentence; says what was counted, over what, and nothing about anything else."""
    a = r.ask
    topic = " ".join(a.topic) or "file"
    when = f" in {a.year}" if a.year else ""
    how = a.outcome.value if a.outcome else "decided"
    n, m = len(r.counted), len(r.decided)
    noun, verb = ("matter", "was") if n == 1 else ("matters", "were")
    out = f"Among the records you may see, {n} {topic} {noun} {verb} {how}{when}"
    if a.outcome is not None:
        out += f" (of {m} decided{when})"
    return out + "."
