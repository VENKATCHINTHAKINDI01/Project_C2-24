"""RAG answer quality that needs no judge model (plan §13.2 "RAG"; ADR-0050).

Computed on every run, offline and free, from what the assistant actually did: the evidence
package it sent to Gemini and the statements that survived the citation check. The RAGAS scores
that need a judge model (faithfulness, groundedness, answer relevance, context precision / recall)
are in `evaluation/ragas_score.py`.

Definitions (one answered question):
- citation correctness: of the model-written statements shown, the share whose every citation
  names an evidence item that IS in the package and whose quote is found in that item's text.
  The citation check enforces this in the app; this is the independent re-check (should be 1.0).
- citation completeness: of the answer key's records that reached the package, the share the
  answer cites. Low = the evidence was there but the answer left it out.
- context precision (by record): share of the package's records that are on the answer key.
- context recall (by record): share of the answer key's records that reached the package.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

_WS = re.compile(r"\s+")
_HYPHEN = re.compile(r" ?- ?")


def norm(text: str) -> str:
    """Form used to find a quote in a passage: case, whitespace and dashes only. Spaces around a
    hyphen go, so a date broken across a line in the source ("18-09-\n2026") matches its quote."""
    t = _WS.sub(" ", text.replace("\u2013", "-").replace("\u2014", "-")).strip().casefold()
    return _HYPHEN.sub("-", t)


def citation_correct(statement: Mapping[str, Any], spans: Mapping[str, str]) -> bool:
    """`statement`: {"quote": str|None, "citations": [{"evidence_id": ...}]};
    `spans`: evidence_id → passage text of the package."""
    cites = [c["evidence_id"] for c in statement.get("citations", ())]
    if not cites or any(e not in spans for e in cites):
        return False
    quote = statement.get("quote")
    if not quote:
        return False
    q = norm(quote)
    return any(q in norm(spans[e]) for e in cites)


def share(part: int, whole: int) -> float | None:
    """None when there is nothing to measure (never a made-up 0 or 1)."""
    return part / whole if whole else None


def record_scores(
    package: Iterable[str], cited: Iterable[str], expected: Iterable[str]
) -> dict[str, float | None]:
    pkg, cit, exp = set(package), set(cited), set(expected)
    reached = pkg & exp
    return {
        "context_precision_by_record": share(len(reached), len(pkg)),
        "context_recall_by_record": share(len(reached), len(exp)),
        "citation_completeness": share(len(reached & cit), len(reached)),
    }


def mean(values: Sequence[float | None]) -> float | None:
    got = [v for v in values if v is not None]
    return sum(got) / len(got) if got else None
