"""Referencing in a note — touchpoint 7 (plan §11.5): point the officer's new note at a previous
note paragraph or a correspondence page of the SAME file, ready for the e-Office reference link.

Deterministic and scoped:
- Previous notes come from the file's indexed note documents that the officer may see (`allowed`
  re-checks each one), only CONFIRMED notes (Green Notes, per the e-Office `NoteRef`), and only
  notes signed on or before `as_of`. The e-Office supplies the note's own ID; C2-24 never invents
  one.
- Correspondence pages come from the e-Office page list; a page that is an indexed order is offered
  only if the officer may see that order.
- "Note #1, para 3" (or "para 3 of Note #1") in the request is matched exactly.
- Otherwise paragraphs are ranked by how many of the request's words (lightly stemmed) they share:
  a KEYWORD STAND-IN for meaning-based matching (Vertex AI Search / Gemini later). `min_terms` is a
  sandbox test value, not calibrated.
Nothing is inserted here: the officer picks a suggestion and clicks, which creates a
`suggested_reference` draft through the connector.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Iterable
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.auth.models import DocumentAccessTags
from app.connectors.eoffice import FileContext
from app.noting.chain import parse_notes


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReferenceConfig(_Frozen):
    min_terms: int = Field(ge=1)  # shared words a paragraph needs (capped at the request's own)
    max_suggestions: int = Field(ge=1)


class TargetKind(StrEnum):
    PREVIOUS_NOTE = "previous_note"
    CORRESPONDENCE_PAGE = "correspondence_page"


class MatchedBy(StrEnum):
    EXPLICIT = "explicit"  # the officer named the note / paragraph
    KEYWORDS = "keywords"  # keyword stand-in
    NONE = "none"


class ReferenceSuggestion(_Frozen):
    kind: TargetKind
    target_id: str  # e-Office note ID or correspondence ID
    note_no: int | None = None
    paragraph: int | None = None
    page_from: int | None = None
    page_to: int | None = None
    text: str  # the paragraph's own words, or the page title
    source: str | None  # canonical ID of the document the words come from
    matched_terms: tuple[str, ...] = ()
    insert_text: str  # what goes into the note, e.g. "Note #1, para 3"


class ReferenceResult(_Frozen):
    matched_by: MatchedBy
    suggestions: tuple[ReferenceSuggestion, ...]


_GENERIC = frozenset(
    "a an and are as at be by for from has have in is it of on or the to was were with what who "
    "which been any this that these those there their its about regarding reg made give me find "
    "please kindly ask asks asked reference references refer referring earlier previous last "
    "note notes noting para paragraph paragraphs page pages file same".split()
)
_WORD = re.compile(r"[a-z]+")
_SUFFIXES = ("ations", "ation", "ings", "ing", "als", "al", "ies", "ied", "ed", "es", "s", "y")
_EXPLICIT = (
    re.compile(
        r"\bnote\s*(?:#|no\.?)?\s*(\d{1,3})\b(?:\W{0,3}(?:para(?:graph)?\.?\s*(\d{1,3})))?", re.I
    ),
    re.compile(r"\bpara(?:graph)?\.?\s*(\d{1,3})\s+of\s+note\s*(?:#|no\.?)?\s*(\d{1,3})\b", re.I),
)


def _stem(w: str) -> str:
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def stems(text: str) -> frozenset[str]:
    return frozenset(_stem(w) for w in _WORD.findall(text.lower()) if w not in _GENERIC)


def _explicit(text: str) -> tuple[int, int | None] | None:
    if m := _EXPLICIT[1].search(text):
        return int(m.group(2)), int(m.group(1))
    if m := _EXPLICIT[0].search(text):
        return int(m.group(1)), int(m.group(2)) if m.group(2) else None
    return None


def suggest_references(
    request: str,
    file_ctx: FileContext,
    note_documents: Iterable[tuple[str, str, DocumentAccessTags]],
    *,
    as_of: dt.date,
    allowed: Callable[[DocumentAccessTags], bool],
    order_visible: Callable[[str], bool],
    cfg: ReferenceConfig,
) -> ReferenceResult:
    """`note_documents`: (canonical ID, text, tags) of the file's indexed note documents."""
    refs = {n.note_no: n for n in file_ctx.notes if n.confirmed}
    paragraphs: list[ReferenceSuggestion] = []
    seen: set[tuple[int, int]] = set()
    for cid, text, tags in note_documents:
        if not allowed(tags):
            continue
        for entry in parse_notes(text, cid):
            ref = refs.get(entry.note_no)
            if ref is None or entry.signed_at is None or entry.signed_at.date() > as_of:
                continue  # not a confirmed note of this file as of the date, or undated
            for no, words in entry.by_paragraph:
                if (entry.note_no, no) in seen:
                    continue
                seen.add((entry.note_no, no))
                paragraphs.append(
                    ReferenceSuggestion(
                        kind=TargetKind.PREVIOUS_NOTE,
                        target_id=ref.note_id,
                        note_no=entry.note_no,
                        paragraph=no,
                        text=words,
                        source=cid,
                        insert_text=f"Note #{entry.note_no}, para {no}",
                    )
                )

    named = _explicit(request)
    if named is not None:
        note_no, para = named
        hits = [
            p for p in paragraphs if p.note_no == note_no and (para is None or p.paragraph == para)
        ]
        return ReferenceResult(
            matched_by=MatchedBy.EXPLICIT if hits else MatchedBy.NONE,
            suggestions=tuple(hits[: cfg.max_suggestions]),
        )

    pages = [
        ReferenceSuggestion(
            kind=TargetKind.CORRESPONDENCE_PAGE,
            target_id=pg.correspondence_id,
            page_from=pg.page_from,
            page_to=pg.page_to,
            text=pg.title,
            source=pg.canonical_id,
            insert_text=(
                f"page {pg.page_from}/C"
                if pg.page_from == pg.page_to
                else f"pages {pg.page_from}–{pg.page_to}/C"
            ),
        )
        for pg in file_ctx.pages
        if pg.canonical_id is None or order_visible(pg.canonical_id)
    ]
    want = stems(request)
    need = min(cfg.min_terms, len(want))
    scored: list[tuple[int, int, ReferenceSuggestion]] = []
    for i, s in enumerate([*paragraphs, *pages]):
        hit = want & stems(s.text)
        if want and len(hit) >= need:
            scored.append((len(hit), i, s.model_copy(update={"matched_terms": tuple(sorted(hit))})))
    scored.sort(key=lambda t: (-t[0], t[1]))  # most shared words; then earliest in the file
    out = tuple(s for _, _, s in scored[: cfg.max_suggestions])
    return ReferenceResult(
        matched_by=MatchedBy.KEYWORDS if out else MatchedBy.NONE, suggestions=out
    )
