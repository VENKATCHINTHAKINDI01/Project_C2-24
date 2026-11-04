"""'File so far' — the note chain of an e-File by post (plan §11.5 touchpoint 8, §10.1).

Deterministic: notes are read from the file's indexed note documents ("Note # N", numbered
paragraphs, signature "name / post / dd/mm/yyyy hh:mm AM"). Each entry keeps the note's own
words and the document it came from, so every line is citable. Missing note numbers are named
as gaps — never filled in. A model-written summary comes later (Gemini) on top of this.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NoteEntry(_Frozen):
    note_no: int
    paragraphs: tuple[int, int] | None  # first and last paragraph number, when numbered
    text: str  # the note's own words, page furniture removed
    signer: str | None
    post: str | None
    signed_at: dt.datetime | None
    source: str  # canonical ID of the note document


class FileSoFar(_Frozen):
    notes: tuple[NoteEntry, ...]
    chain: tuple[str, ...]  # posts in note order, consecutive repeats merged
    last_direction: NoteEntry | None
    gaps: tuple[tuple[int, int], ...]  # missing note-number ranges, inclusive
    sources: tuple[str, ...]


_NOTE = re.compile(r"^\s*Note\s*#\s*(\d+)\s*$", re.M)
_SIGNED = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(\d{1,2}:\d{2})\s*([AP]M)", re.I)
_FURNITURE = re.compile(
    r"^\s*(?:(?:[A-Z]\s){3,}[A-Z]\s*|\[(?:UNCLASSIFIED|RESTRICTED|CONFIDENTIAL|SECRET)\]"
    r"|SYNTHETIC TEST DATA\b.*|NOTE)\s*$"
)
_ONE_LINE = re.compile(r"^(?P<name>.+?)\s+/\s+(?P<post>.+?)\s+/\s+\d{2}/\d{2}/\d{4}\b")
_PARA = re.compile(r"^\s*(\d{1,3})\.\s")


def _when(date: str, time: str, ampm: str) -> dt.datetime | None:
    try:
        return dt.datetime.strptime(f"{date} {time} {ampm.upper()}", "%d/%m/%Y %I:%M %p")
    except ValueError:
        return None


def parse_notes(text: str, source: str) -> list[NoteEntry]:
    """Every 'Note # N' section of one note document."""
    marks = list(_NOTE.finditer(text))
    out: list[NoteEntry] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        lines = [
            ln.strip()
            for ln in text[m.end() : end].splitlines()
            if ln.strip() and not _FURNITURE.match(ln)
        ]
        signer = post = None
        signed_at = None
        idx = next((j for j in range(len(lines) - 1, -1, -1) if _SIGNED.search(lines[j])), None)
        if idx is not None:
            sm = _SIGNED.search(lines[idx])
            assert sm is not None
            signed_at = _when(sm.group(1), sm.group(2), sm.group(3))
            one = _ONE_LINE.match(lines[idx])
            if one:  # "name / post / date" on one line
                signer, post = one.group("name"), one.group("post")
                body = lines[:idx]
            else:  # name and post on the two lines above the date
                signer = lines[idx - 2] if idx >= 2 else None
                post = lines[idx - 1] if idx >= 1 else None
                body = lines[: max(idx - 2, 0)]
            body += lines[idx + 1 :]
        else:
            body = lines
        nums = [int(p.group(1)) for ln in body if (p := _PARA.match(ln))]
        out.append(
            NoteEntry(
                note_no=int(m.group(1)),
                paragraphs=(nums[0], nums[-1]) if nums else None,
                text=" ".join(body),
                signer=signer,
                post=post,
                signed_at=signed_at,
                source=source,
            )
        )
    return out


def file_so_far(documents: Iterable[tuple[str, str]]) -> FileSoFar:
    """`documents`: (canonical ID, text) of the note documents of ONE file that the officer may
    see. Duplicate note numbers keep the first occurrence; gaps are the missing numbers between
    1 and the highest note seen."""
    by_no: dict[int, NoteEntry] = {}
    for cid, text in documents:
        for n in parse_notes(text, cid):
            by_no.setdefault(n.note_no, n)
    notes = tuple(by_no[k] for k in sorted(by_no))
    gaps: list[tuple[int, int]] = []
    expected = 1
    for n in notes:
        if n.note_no > expected:
            gaps.append((expected, n.note_no - 1))
        expected = n.note_no + 1
    chain: list[str] = []
    for n in notes:
        if n.post and (not chain or chain[-1] != n.post):
            chain.append(n.post)
    return FileSoFar(
        notes=notes,
        chain=tuple(chain),
        last_direction=notes[-1] if notes else None,
        gaps=tuple(gaps),
        sources=tuple(dict.fromkeys(n.source for n in notes)),
    )
