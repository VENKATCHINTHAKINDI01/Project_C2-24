"""The paragraph a citation points at, with the quoted words marked (ADR-0034).

Used by the hover preview: the officer sees the cited paragraph without leaving the file. The
text comes from the record the officer may see (checked by the route); this module only finds
the paragraph that holds the quote, matching it as the citation check does (case, dashes and
whitespace ignored).
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

MAX_CHARS = 1200
_PARA_START = re.compile(r"\n\s*\n|\n(?=\s*(?:\d+[.)]|\([ivxlc]+\)|\([a-z]\))\s)")


class PassageContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    paragraph: str
    highlight: tuple[int, int] | None  # character range of the quote inside `paragraph`


def _normalised(text: str) -> tuple[str, list[int]]:
    """Lower-cased, dashes unified, whitespace runs as one space and none around a dash (as the
    citation check matches); with the original index of every kept character, so a match maps
    back to the source text."""
    out: list[str] = []
    where: list[int] = []
    space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            space = bool(out)
            continue
        c = "-" if ch in "–—" else ch.lower()
        if space and c != "-" and not (out and out[-1] == "-"):
            out.append(" ")
            where.append(i)
        space = False
        out.append(c)
        where.append(i)
    return "".join(out), where


def _find(text: str, quote: str) -> tuple[int, int] | None:
    hay, where = _normalised(text)
    needle, _ = _normalised(quote)
    at = hay.find(needle) if needle else -1
    if at < 0:
        return None
    return where[at], where[at + len(needle) - 1] + 1


def context_of(text: str, quote: str | None) -> PassageContext | None:
    """The paragraph holding `quote` (or None when the quote is not in the text)."""
    if not text or not quote:
        return None
    hit = _find(text, quote)
    if hit is None:
        return None
    s, e = hit
    starts = [m.end() for m in _PARA_START.finditer(text, 0, s)]
    begin = starts[-1] if starts else 0
    nxt = _PARA_START.search(text, e)
    end = nxt.start() if nxt else len(text)
    if end - begin > MAX_CHARS:  # a long paragraph: a window around the quote
        begin = max(begin, s - (MAX_CHARS - (e - s)) // 2)
        end = min(end, begin + MAX_CHARS)
    raw = text[begin:end]
    lead = len(raw) - len(raw.lstrip())
    para = raw.strip()
    return PassageContext(paragraph=para, highlight=(s - begin - lead, e - begin - lead))
