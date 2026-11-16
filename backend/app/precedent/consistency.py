"""Conflict type D — precedent inconsistency, review only (plan §6.2, §6.4; CLAUDE.md §6.4).

Deterministic and narrow on purpose: a flag is raised only when
- EARLIER e-Files on the same matter (same subject) that this officer may see record a proposed
  disposal (allow / refuse) in their own words,
- this note proposes the opposite of what MOST of them proposed, and
- this note does not refer to those files.
It never says which disposal is right: comparable cases can differ for good reasons. Where either
note states no clear disposal nothing is raised (and nothing is inferred). The caller passes only
notes the officer is authorised to read; the flag names only those.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.conflict.deterministic import ConflictFlag, ConflictType


class Disposal(StrEnum):
    ALLOW = "allow"
    REFUSE = "refuse"


class EarlierNote(BaseModel):
    """A note of another e-File, already authorised for this officer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    file_no: str
    doc_id: str
    subject: str
    date: dt.date | None
    text: str


_PROPOSED = re.compile(r"It\s+is\s+proposed\s+that\s+(.+?)(?=\s\d{1,2}[.)]\s|$)", re.I)
_VERB_ALLOW = r"allowed|sanctioned|accorded|approved|permitted|agreed\s+to|admitted|granted"
_VERB_REFUSE = r"rejected|declined|refused|regretted|negatived"
_ALLOW = re.compile(rf"may\s+(?:kindly\s+)?be\s+(?:{_VERB_ALLOW})", re.I)
_REFUSE = re.compile(
    rf"may\s+(?:kindly\s+)?be\s+(?:{_VERB_REFUSE})|may\s+not\s+be\s+(?:{_VERB_ALLOW})", re.I
)


def disposal_of(text: str) -> tuple[Disposal | None, str]:
    """The disposal the LAST "It is proposed that …" sentence states, and that sentence.
    Both or neither of allow / refuse in it → None (never guessed)."""
    found = _PROPOSED.findall(re.sub(r"\s+", " ", text))
    if not found:
        return None, ""
    sentence = found[-1].strip()
    allow, refuse = bool(_ALLOW.search(sentence)), bool(_REFUSE.search(sentence))
    if allow == refuse:
        return None, sentence
    return (Disposal.ALLOW if allow else Disposal.REFUSE), sentence


def same_matter(a: str, b: str) -> bool:
    """Same subject line, ignoring case, punctuation, spacing and a trailing "Reg."."""

    def norm(s: str) -> str:
        s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
        return re.sub(r"\s+reg$", "", s)

    return bool(norm(a)) and norm(a) == norm(b)


def _mentions(text: str, file_no: str) -> bool:
    squeeze = re.compile(r"[\s.]+")
    return squeeze.sub("", file_no).lower() in squeeze.sub("", text).lower()


def precedent_flags(
    *,
    file_no: str,
    subject: str,
    note_date: dt.date | None,
    text: str,
    earlier: Iterable[EarlierNote],
) -> list[ConflictFlag]:
    """`text` is this file's note sheet (earlier notes, then the draft)."""
    mine, _ = disposal_of(text)
    if mine is None:
        return []
    by_file: dict[str, tuple[EarlierNote, Disposal]] = {}  # one disposal per file: its latest note
    for e in sorted(earlier, key=lambda n: (n.date or dt.date.min, n.doc_id)):
        if e.file_no == file_no or not same_matter(subject, e.subject):
            continue
        if note_date and e.date and e.date >= note_date:
            continue
        theirs, _ = disposal_of(e.text)
        if theirs is not None:
            by_file[e.file_no] = (e, theirs)
    against = [e for e, d in by_file.values() if d is not mine]
    # The earlier PRACTICE is what most earlier files did. Evenly divided earlier files show no
    # practice to depart from (e.g. a file that follows the usual line after one stray case).
    if len(against) * 2 <= len(by_file) or any(_mentions(text, e.file_no) for e in against):
        return []
    last = against[-1]
    theirs_word = (Disposal.REFUSE if mine is Disposal.ALLOW else Disposal.ALLOW).value
    when = f" ({last.date:%d-%m-%Y})" if last.date else ""
    count = (
        f"{len(against)} of {len(by_file)} earlier files on the same matter (latest: File "
        f"{last.file_no}{when})"
        if len(by_file) > 1
        else f"File {last.file_no}{when} on the same matter"
    )
    dates = {k: v for k, v in (("earlier_file", last.date), ("proposal", note_date)) if v}
    return [
        ConflictFlag(
            type=ConflictType.D,
            cited=last.file_no,
            evidence_ids=tuple(e.doc_id for e in against),
            explanation=(
                f"Potential precedent inconsistency — {count} proposed to {theirs_word} the "
                f"request; this note proposes to {mine.value} it and does not refer to "
                f"{'them' if len(against) > 1 else 'that file'}. Review recommended: compare "
                "the cases."
            ),
            dates=dates,
            certain=False,
        )
    ]
