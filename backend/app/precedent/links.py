"""Link File suggestions — precedent files within the officer's scope (plan §11.5 touchpoint 9).

The open file's subject is the query (a precedent lookup through the scoped ladder, so only
documents the officer may see are ever scored). Hits from the open file itself are dropped and the
rest are grouped by e-File, best first. Nothing is linked here: the officer chooses, and the
connector records at most a *suggested reference* draft.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from app.agents.intents import IntentSlots
from app.agents.tools import DocRef, ToolContext, find_precedents


class LinkSuggestion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    file_no: str
    rank: int  # 1 = best
    documents: tuple[DocRef, ...]  # the precedent notes in that file that matched


def suggest_links(
    ctx: ToolContext,
    subject: str,
    open_file_no: str,
    file_of: Callable[[str], str | None],
    limit: int = 5,
) -> list[LinkSuggestion]:
    """`file_of(canonical_id)` → e-File number from the document's access tags."""
    res = find_precedents(ctx, IntentSlots(text=subject[:500]))
    groups: dict[str, list[DocRef]] = {}
    for d in res.documents:
        f = file_of(d.canonical_id)
        if f and f != open_file_no:
            groups.setdefault(f, []).append(d)
    return [
        LinkSuggestion(file_no=f, rank=i, documents=tuple(docs))
        for i, (f, docs) in enumerate(list(groups.items())[:limit], start=1)
    ]
