"""Clause structure of an order's text (plan §4.4 clause-level IDs). Deterministic.

`clauses(text)` → (locator, text) blocks: "2" for para 2, "2.v" for (v) under para 2; a line that
starts no new clause continues the previous one (PDF line wraps). When the order has an "ORDER:"
heading, only what follows it is read: the numbered "Read the following" list above it is
references, not paragraphs of the order. `paragraph_label(text)` reads the
paragraph an officer names ("para 2(v)", "paragraph 3", "para 2.v") as a locator.
"""

from __future__ import annotations

import re

_PARA = re.compile(r"^\s*(\d{1,2})\.\s+")
_SUB = re.compile(r"^\s*\(([ivx]{1,5}|[a-z])\)\s+")
_ORDER_HEADING = re.compile(r"^\s*ORDERS?\s*:?\s*$")
_NAMED = re.compile(
    r"\bpara(?:graph)?\.?\s*(\d{1,2})(?:\s*\(\s*([ivx]{1,5}|[a-z])\s*\)|\.([ivx]{1,5}|[a-z])\b)?",
    re.I,
)


def clauses(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    para = ""
    lines = text.splitlines()
    start = next((i + 1 for i, ln in enumerate(lines) if _ORDER_HEADING.match(ln)), 0)
    for raw in lines[start:]:
        line = " ".join(raw.split())  # PDF text: runs of spaces after the number
        if m := _PARA.match(line):
            para = m.group(1)
            out.append((para, line.strip()))
        elif (m := _SUB.match(line)) and para:
            out.append((f"{para}.{m.group(1).lower()}", line.strip()))
        elif out and line.strip():
            loc, body = out[-1]
            out[-1] = (loc, f"{body} {line.strip()}")
    return out


def paragraph_label(text: str) -> str | None:
    """The first paragraph the text names, as a locator ("2.v"), or None."""
    m = _NAMED.search(text)
    if not m:
        return None
    sub = m.group(2) or m.group(3)
    return f"{m.group(1)}.{sub.lower()}" if sub else m.group(1)


def clause_text(text: str, locator: str) -> str | None:
    """The clause at `locator`, only when exactly one block has it (else None: absent/ambiguous)."""
    hits = [body for loc, body in clauses(text) if loc == locator]
    return hits[0] if len(hits) == 1 else None
