"""Streaming a cited answer (plan §8.1, §10.6; ADR-0033).

The officer sees the answer grow as the model writes it — but only statements that have already
passed the citation check (CLAUDE.md §4.12, §7.7). The model's raw text is never sent: each
statement is shown the moment its JSON object is complete AND the verifier confirms it against
the passage it cites. The final `done` event carries the full answer and is authoritative; the
screen replaces what it streamed with it.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

Event = dict[str, Any]
Emit = Callable[[Event], None]


class StatementStream:
    """Finds each complete object of the top-level `"statements": [...]` array in JSON text that
    arrives in pieces. Strings and escapes are tracked, so braces inside text do not count."""

    def __init__(self, key: str = "statements") -> None:
        self._key = f'"{key}"'  # the array to read (ADR-0072: also "sentences", "suggestions")
        self._buf = ""
        self._pos = 0  # next character to scan
        self._in_array = False
        self._depth = 0  # object depth inside the array
        self._start = -1  # where the current object began
        self._in_str = False
        self._esc = False
        self._key_seen = False
        self._done = False

    def feed(self, text: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        if self._done:
            return found
        self._buf += text
        b = self._buf
        i = self._pos
        while i < len(b):
            ch = b[i]
            if self._in_str:
                if self._esc:
                    self._esc = False
                elif ch == "\\":
                    self._esc = True
                elif ch == '"':
                    self._in_str = False
                i += 1
                continue
            if not self._in_array:
                if not self._key_seen:
                    k = b.find(self._key, i)
                    if k < 0:
                        i = max(i, len(b) - len(self._key))  # keep a partial key
                        break
                    self._key_seen, i = True, k + len(self._key)
                    continue
                if ch == "[":
                    self._in_array = True
                i += 1
                continue
            if ch == '"':
                self._in_str = True
            elif ch == "{":
                if self._depth == 0:
                    self._start = i
                self._depth += 1
            elif ch == "}":
                self._depth -= 1
                if self._depth == 0 and self._start >= 0:
                    try:
                        obj = json.loads(b[self._start : i + 1])
                    except ValueError:
                        obj = None
                    if isinstance(obj, dict):
                        found.append(obj)
                    self._start = -1
            elif ch == "]" and self._depth == 0:
                self._done = True  # the array is over: nothing more to find
                self._buf = ""
                return found
            i += 1
        self._pos = i
        return found


def sse(event: Event) -> str:
    """One Server-Sent Events message."""
    return f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
