"""Approval brief for a senior officer who opens a file (plan §11.5 touchpoint 13). Deterministic.

Assembled only from parts that already enforce scope and the status-coverage rule:
- proposal: the draft note's own facts (`extract_proposal_facts`) and the file's note chain;
- governing orders: each order the draft cites, through the status tool (states supersession by a
  visible order; never "current" without full coverage);
- flags: the pre-send check (A / E / F / C, mock rules caveated);
- precedents: Link File suggestions within the officer's scope;
- movement: who the file has passed through (connector) and the note chain by post.
A model-written brief comes later (Gemini) on top of this; nothing here is free text from a model.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass

from app.agents.tools import ToolContext, ToolName, ToolResult, call_tool
from app.auth.models import DocumentAccessTags
from app.auth.policy import check
from app.conflict.facts import FactsResult, extract_proposal_facts
from app.conflict.presend import PreSendReport, presend_check
from app.conflict.procedural import AuthorityRules
from app.identifiers.canonical import InvalidCanonicalIdError, lookup_keys, parse_canonical_id
from app.identifiers.resolver import DepartmentTable
from app.ingestion.metadata import extract_metadata
from app.noting.chain import FileSoFar, file_so_far
from app.precedent.links import LinkSuggestion, suggest_links
from app.retrieval.scoped import IndexedDocument
from app.temporal.windows import ActionWindow


@dataclass(frozen=True)
class GoverningOrder:
    cited: str  # canonical ID as cited in the draft (matched to a visible record when possible)
    found: bool
    status: ToolResult | None  # check_document_status, under the coverage rule


@dataclass(frozen=True)
class ApprovalBrief:
    draft_id: str | None
    facts: FactsResult | None
    chain: FileSoFar
    governing: tuple[GoverningOrder, ...]
    presend: PreSendReport | None
    precedents: tuple[LinkSuggestion, ...]
    movement: tuple[str, ...]  # user / post ids in the order the file moved


def _visible_match(cid: str, visible: Callable[[str], bool], ids: Iterable[str]) -> str | None:
    try:
        hit = next((k for k in lookup_keys(cid) if visible(k)), None)
        if hit is None:
            base = parse_canonical_id(cid).base_id
            same = [i for i in ids if visible(i) and _base(i) == base]
            hit = same[0] if len(same) == 1 else None
        return hit
    except InvalidCanonicalIdError:
        return None


def _base(cid: str) -> str | None:
    try:
        return parse_canonical_id(cid).base_id
    except InvalidCanonicalIdError:
        return None


def approval_brief(
    *,
    ctx: ToolContext,
    file_no: str,
    subject: str,
    movement: tuple[str, ...],
    documents: list[IndexedDocument],
    text_of: Callable[[str], str],
    tags_of: Mapping[str, DocumentAccessTags],
    rules: AuthorityRules,
    windows: Iterable[ActionWindow],
    departments: DepartmentTable,
) -> ApprovalBrief:
    """`documents`: the indexed documents; only those the officer may see are used."""
    by_id = {d.canonical_id: d for d in documents}

    def visible(cid: str) -> bool:
        d = by_id.get(cid)
        return (
            d is not None
            and check(ctx.user_id, d.tags, ctx.store, ctx.policy, ctx.classification).allowed
        )

    notes = sorted(
        (
            d
            for d in documents
            if d.tags.file_no == file_no
            and d.doc_type.startswith("Noting")
            and visible(d.canonical_id)
        ),
        key=lambda d: (d.issue_date or dt.date.min, d.canonical_id),
    )
    chain = file_so_far((d.canonical_id, text_of(d.canonical_id)) for d in notes)
    draft = notes[-1] if notes else None
    facts = presend = None
    governing: list[GoverningOrder] = []
    if draft is not None:
        text = text_of(draft.canonical_id)
        meta = extract_metadata(text, departments)
        facts = extract_proposal_facts(text, meta, rules, draft.canonical_id)
        presend = presend_check(
            draft.canonical_id,
            text,
            meta,
            user_id=ctx.user_id,
            instruments=ctx.instruments,
            relations=list(ctx.relations),
            tags_of=tags_of,
            rules=rules,
            store=ctx.store,
            policy=ctx.policy,
            classification=ctx.classification,
            windows=windows,
        )
        for ref in meta.references:
            if ref.canonical_id is None or ref.raw.startswith("file:"):
                continue
            hit = _visible_match(ref.canonical_id, visible, by_id)
            status = (
                call_tool(ctx, ToolName.CHECK_DOCUMENT_STATUS, {"canonical_ids": (hit,)})
                if hit
                else None
            )
            governing.append(
                GoverningOrder(cited=hit or ref.canonical_id, found=bool(hit), status=status)
            )

    def file_of(cid: str) -> str | None:
        t = tags_of.get(cid)
        return t.file_no if t else None

    precedents = tuple(suggest_links(ctx, subject, file_no, file_of))
    return ApprovalBrief(
        draft_id=draft.canonical_id if draft else None,
        facts=facts,
        chain=chain,
        governing=tuple(governing),
        presend=presend,
        precedents=precedents,
        movement=movement,
    )
