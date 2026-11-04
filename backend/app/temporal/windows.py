"""Action windows: periods an order opens for an action, stated inside its paragraphs (plan §6.1,
§6.4 type F). E.g. G.O.Ms.31/2025 para 2(i): "The ban on transfers is relaxed for the period
from 15-05-2025 to 31-05-2025."

Facts only, read deterministically from the order's own clause text, each with its clause-level
canonical ID and the words it came from. A sentence that does not match the fixed pattern yields
nothing — windows are never inferred.
"""

from __future__ import annotations

import datetime as dt
import re

from pydantic import BaseModel, ConfigDict, model_validator


class ActionWindow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str  # clause-level canonical ID, e.g. AP-FIN01-GOMS-31-2025#para-2.i
    action: str  # "transfer" — matches the proposal action's value
    start: dt.date
    end: dt.date  # inclusive
    evidence: str

    @model_validator(mode="after")
    def _ordered(self) -> ActionWindow:
        if self.end < self.start:
            raise ValueError(f"window ends before it starts: {self.source}")
        return self

    @property
    def document_id(self) -> str:
        return self.source.split("#", 1)[0]

    def contains(self, day: dt.date) -> bool:
        return self.start <= day <= self.end


_D = r"(\d{1,2}[-./]\d{1,2}[-./]\d{4})"
_PATTERNS = {
    "transfer": re.compile(
        r"\bban\s+on\s+transfers?\s+is\s+(?:hereby\s+)?relaxed\s+(?:for\s+the\s+period\s+)?"
        rf"from\s+{_D}\s+to\s+{_D}",
        re.I,
    ),
}
_PARA = re.compile(r"^\s*(\d{1,2})\.\s+")
_SUB = re.compile(r"^\s*\(([ivx]{1,5}|[a-z])\)\s+")


def _date(raw: str) -> dt.date | None:
    for fmt in ("%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _clauses(text: str) -> list[tuple[str, str]]:
    """(locator, clause text) blocks: "2" for para 2, "2.i" for (i) under para 2. Lines that
    start no new clause continue the previous one (PDF line wraps)."""
    out: list[tuple[str, str]] = []
    para = ""
    for line in text.splitlines():
        if m := _PARA.match(line):
            para = m.group(1)
            out.append((para, line))
        elif (m := _SUB.match(line)) and para:
            out.append((f"{para}.{m.group(1).lower()}", line))
        elif out and line.strip():
            loc, body = out[-1]
            out[-1] = (loc, f"{body} {line.strip()}")
    return out


def windows_from_text(canonical_id: str, text: str) -> tuple[ActionWindow, ...]:
    """Every action window an order states, one per matching clause."""
    found: list[ActionWindow] = []
    for loc, body in _clauses(text):
        flat = re.sub(r"\s+", " ", body)
        for action, rx in _PATTERNS.items():
            for m in rx.finditer(flat):
                start, end = _date(m.group(1)), _date(m.group(2))
                if start and end and start <= end:
                    found.append(
                        ActionWindow(
                            source=f"{canonical_id}#para-{loc}",
                            action=action,
                            start=start,
                            end=end,
                            evidence=m.group(0),
                        )
                    )
    return tuple(found)
