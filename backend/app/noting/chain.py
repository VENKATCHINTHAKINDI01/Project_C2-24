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
    by_paragraph: tuple[tuple[int, str], ...] = ()  # (number, its own words), when numbered
    # the note's header, when it has one (e-Office layout "Sub: … / Ref: 1. … 2. … / * * *"):
    # its subject line and the items of its reference list (the PUC is usually one of them).
    # Reference-list items are never paragraphs of the note (ADR-0060 addendum).
    subject_line: str | None = None
    references: tuple[str, ...] = ()


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
_MARKING = re.compile(r"^\s*\[?(?:UNCLASSIFIED|RESTRICTED|CONFIDENTIAL|SECRET)\]?\s*$")
_PARA = re.compile(r"^\s*(\d{1,3})\.\s")
# a paragraph of the note's body: "5. …" or "5) …"
_BODY_PARA = re.compile(r"^\s*(\d{1,3})[.)]\s")
_SUB = re.compile(r"^\s*Sub(?:ject)?\s*[:.\-–]\s*(.*)$", re.I)
_REF = re.compile(r"^\s*Ref(?:erence)?s?\s*[:.\-–]?\s*(.*)$", re.I)
_SEPARATOR = re.compile(r"^\s*(?:\*\s*){3,}$|^\s*-{3,}\s*$")


def note_structure(
    body: list[str],
) -> tuple[str | None, tuple[str, ...], tuple[tuple[int, str], ...]]:
    """Split a note's lines into its header (subject line, reference list) and its numbered body
    paragraphs. A note without a "Sub:" header is all body (the older layout: "1. …"). In a note
    with one, the "Ref:" list is numbered "1. 2. …" too, so the body starts after the "* * *"
    separator or at the first "N)" paragraph; a wrapped line or a sub-item "(a) …" / "a) …"
    continues the paragraph above it."""
    subject: str | None = None
    refs: list[str] = []
    paras: list[tuple[int, str]] = []
    i = 0
    if body and (sm := _SUB.match(body[0])):
        subject = sm.group(1).strip()
        i = 1
        in_refs = False
        while i < len(body):
            ln = body[i]
            if _SEPARATOR.match(ln):
                i += 1
                break
            if re.match(r"^\s*\d{1,3}\)\s", ln) and (in_refs or subject):
                break  # the body's first paragraph, with no separator before it
            if (rm := _REF.match(ln)) and not in_refs:
                in_refs = True
                if rm.group(1).strip():
                    refs.append(rm.group(1).strip())
            elif in_refs and _PARA.match(ln):
                refs.append(_PARA.sub("", ln, count=1).strip())
            elif in_refs and refs:
                refs[-1] = f"{refs[-1]} {ln.strip()}"
            elif not in_refs:
                subject = f"{subject} {ln.strip()}".strip()
            i += 1
    for ln in body[i:]:
        if _MARKING.match(ln):
            continue  # a page's classification marking, not the note's words
        if pm := _BODY_PARA.match(ln):
            paras.append((int(pm.group(1)), ln))
        elif paras:  # a wrapped line or a sub-item continues the paragraph above it
            paras[-1] = (paras[-1][0], f"{paras[-1][1]} {ln}")
    return subject, tuple(refs), tuple(paras)


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
            after = lines[idx + 1 :]
            if one:  # "name / post / date" on one line
                signer, post = one.group("name"), one.group("post")
                body = lines[:idx]
            elif len(after) == 2 and not any(_PARA.match(a) for a in after):
                # date first, then name and post below it (set v2 / e-Office print layout)
                signer, post = after
                body, after = lines[:idx], []
            else:  # name and post on the two lines above the date
                signer = lines[idx - 2] if idx >= 2 else None
                post = lines[idx - 1] if idx >= 1 else None
                body = lines[: max(idx - 2, 0)]
            body += after
        else:
            body = lines
        subject_line, refs, paras = note_structure(body)
        nums = [n for n, _ in paras]
        out.append(
            NoteEntry(
                note_no=int(m.group(1)),
                paragraphs=(nums[0], nums[-1]) if nums else None,
                text=" ".join(body),
                signer=signer,
                post=post,
                signed_at=signed_at,
                source=source,
                by_paragraph=paras,
                subject_line=subject_line,
                references=refs,
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
