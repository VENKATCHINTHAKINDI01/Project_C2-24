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


class DraftRevisionResult(BaseModel):
    """Result of an AI-assisted draft revision."""

    model_config = ConfigDict(frozen=True)

    revised_text: str
    changes_summary: str
    engine: str | None = None
    fallback: bool = False
    reason: str | None = None


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

    used = str(getattr(llm, "last_used", None) or llm.name)
    primary = getattr(getattr(llm, "primary", None), "name", None)
    on_fallback = bool(primary and used != primary)

    return DraftRevisionResult(
        revised_text=revised,
        changes_summary=summary or "Applied requested changes from review remarks.",
        engine=used,
        fallback=on_fallback,
    )
