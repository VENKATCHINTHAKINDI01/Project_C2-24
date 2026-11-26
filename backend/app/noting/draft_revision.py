"""AI-assisted draft revision based on higher officer review remarks (plan §11.5, ADR-0060).

When a senior officer returns a draft for changes with review remarks, this module provides
assisted wording revisions:
- Inputs: current draft text, reviewer's remarks, and file context.
- Model call: Gemini via FailoverLLM (prompt: draft_revise.v1), strictly bounded.
- Guardrails:
  * Modifies only what the senior officer requested.
  * Preserves official style, unchanged provisions, and references.
  * Deterministic fallback when the engine is unavailable.
  * Zero unauthorized disclosure: never cites or draws upon out-of-scope records.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.agents.llm import LLMClient, LLMError, load_prompt

PROMPT_ID = "draft_revise.v1"

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "revised_text": {"type": "string"},
        "changes_summary": {"type": "string"},
    },
    "required": ["revised_text", "changes_summary"],
}


# what a revision may not invent (ADR-0062 addendum, 24 Nov 2026): every number, date and order /
# file reference in the revised text must already be in the draft, the reviewer's remarks or the
# file subject. The prompt asks for this; this check enforces it (CLAUDE.md §7.7).
_CHECKABLE = re.compile(
    r"\b(?:G\.?\s*O\.?\s*(?:\(?(?:Ms|Rt|P)\)?\.?)?\s*No\.?\s*[\w/-]+"
    r"|(?:Memo|Circular|Rc|Lr|File)\.?\s*No\.?\s*[\w./-]+"
    r"|\d{1,2}[-./]\d{1,2}[-./]\d{2,4}"
    r"|(?:Rs\.?|₹)\s*[\d,]+(?:\.\d+)?"
    r"|\d[\d,]*(?:\.\d+)?)",
    re.I,
)


def _norm(token: str) -> str:
    return re.sub(r"[\s,]", "", token).lower().rstrip(".")


def unsupported_tokens(revised: str, *sources: str) -> list[str]:
    """Numbers, dates and references in `revised` that none of `sources` contains."""
    have = {_norm(t) for src in sources for t in _CHECKABLE.findall(src)}
    have_digits = {re.sub(r"\D", "", t) for t in have}
    out: list[str] = []
    for t in _CHECKABLE.findall(revised):
        n = _norm(t)
        if n in have or re.sub(r"\D", "", n) in have_digits and re.sub(r"\D", "", n):
            continue
        out.append(t.strip())
    return list(dict.fromkeys(out))


class DraftRevisionResult(BaseModel):
    """Result of an AI-assisted draft revision."""

    model_config = ConfigDict(frozen=True)

    revised_text: str
    changes_summary: str
    engine: str | None = None
    fallback: bool = False
    reason: str | None = None
    unsupported: tuple[str, ...] = ()  # what the model added that no source holds (withheld)


# the blank number line of an order ("G.O.Rt.No.____  Dated: ____"): filled only on issue
_BLANK_NUMBER = re.compile(r"^[^\n]*No\.\s*_{2,}[^\n]*Dated\s*:?\s*_{2,}[^\n]*$", re.MULTILINE)
_ANY_NUMBER = re.compile(r"^[^\n]*\bNo\.[^\n]{0,40}\bDated\b[^\n]*$", re.MULTILINE)


def keep_number_line(before: str, after: str) -> str:
    """A revision never fills or drops the order's blank number line (26 Nov 2026: a revised
    draft could not be put up). If the draft had one and the revision lost or filled it, the
    original line is put back where the revision wrote its own, else where it stood."""
    m = _BLANK_NUMBER.search(before)
    if m is None or _BLANK_NUMBER.search(after):
        return after
    line = m.group(0)
    got = _ANY_NUMBER.search(after)
    if got:
        return after[: got.start()] + line + after[got.end() :]
    lines = after.split("\n")
    at = before[: m.start()].count("\n")
    lines.insert(min(at, len(lines)), line)
    return "\n".join(lines)


def suggest_revision(
    *,
    current_text: str,
    review_remarks: str,
    subject: str = "",
    file_context: str = "",
    llm: LLMClient | None = None,
) -> DraftRevisionResult:
    """Revise draft text according to the senior reviewer's remarks."""
    clean_text = current_text.strip()
    clean_remarks = review_remarks.strip()

    if not clean_remarks:
        return DraftRevisionResult(
            revised_text=clean_text,
            changes_summary="No review remarks provided.",
            reason="no_remarks",
        )

    if not clean_text:
        return DraftRevisionResult(
            revised_text="",
            changes_summary="No current draft text provided.",
            reason="no_text",
        )

    if llm is None:
        return DraftRevisionResult(
            revised_text=clean_text,
            changes_summary=(
                f"AI engine off. Reviewer remarks to incorporate manually: '{clean_remarks}'"
            ),
            reason="engine_off",
        )

    prompt = load_prompt(PROMPT_ID)
    user_msg = (
        f"Subject: {subject}\n"
        f"File Context: {file_context}\n\n"
        f'<reviewer_remarks untrusted="true">\n{clean_remarks}\n</reviewer_remarks>\n\n'
        f'<current_draft untrusted="true">\n{clean_text}\n</current_draft>'
    )

    try:
        raw = llm.generate_json(
            prompt_id=PROMPT_ID,
            system=prompt,
            user=user_msg,
            schema=SCHEMA,
        )
        revised = str(raw.get("revised_text") or "").strip()
        summary = str(raw.get("changes_summary") or "").strip()
        if not revised:
            return DraftRevisionResult(
                revised_text=clean_text,
                changes_summary="Model did not return revised text; retaining original.",
                engine=llm.name,
                reason="empty_response",
            )
    except (LLMError, TypeError, ValueError):
        return DraftRevisionResult(
            revised_text=clean_text,
            changes_summary="AI revision service temporarily unavailable.",
            engine=llm.name,
            reason="engine_down",
        )

    added = unsupported_tokens(revised, clean_text, clean_remarks, subject, file_context)
    if added:  # withheld, never shown as a suggestion: the officer keeps their own text
        return DraftRevisionResult(
            revised_text=clean_text,
            changes_summary=(
                "The suggested revision was withheld: it introduced figures or references that "
                "are not in the draft or the remarks ("
                + ", ".join(added[:5])
                + "). Please revise by hand."
            ),
            engine=llm.name,
            reason="unsupported",
            unsupported=tuple(added),
        )

    revised = keep_number_line(clean_text, revised)
    used = str(getattr(llm, "last_used", None) or llm.name)
    primary = getattr(getattr(llm, "primary", None), "name", None)
    on_fallback = bool(primary and used != primary)

    return DraftRevisionResult(
        revised_text=revised,
        changes_summary=summary or "Applied requested changes from review remarks.",
        engine=used,
        fallback=on_fallback,
    )
