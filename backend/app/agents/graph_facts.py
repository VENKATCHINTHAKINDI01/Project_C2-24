"""Richer graph reasoning (Tier 2, plan §3.2 L3, §6.1, §12.3; ADR-0056).

Two questions the relationship graph answers better than any passage:
- how an order changed over time: its lineage of amendments, clarifications and replacements, in
  date order, with what is in force on the as-of date (`order_history`);
- how it links to other departments: records of another department that cite, refer to, amend or
  replace it, or that it cites (`cross_department_links`).

Both are deterministic and scoped: the history is computed only from the facts this officer may
see (`visible_facts`), the links only from the scope-constrained L3 walk (`expand`, both
enforcement layers) with every record re-checked. Nothing outside the officer's scope is named,
counted or used as a stepping stone, and nothing says that anything was left out.
"""

from __future__ import annotations

import datetime as dt
import re

from pydantic import BaseModel, ConfigDict

from app.agents.tools import ToolContext, status_covered, visible_document, visible_facts
from app.graph.repository import Direction, EdgeKind
from app.retrieval.graph_expansion import expand
from app.temporal.history import History, history

# "how has … changed", "history of …", "amendments to …", "over the years", "timeline"
HISTORY_Q = re.compile(
    r"\b(?:histor(?:y|ical)|timeline|over (?:the )?(?:years|time)|evolv\w*|chang(?:e|ed|es)|"
    r"amendments?|amended|revisions?|revised|modifi(?:ed|cations?)|sequence of)\b",
    re.I,
)
# "which other departments …", "any department that refers to …", "cross-department links"
CROSS_Q = re.compile(
    r"\b(?:other|another|different|which|any|all|outside)\s+(?:\w+\s+)?departments?\b|"
    r"\bcross[- ]?department\w*|\bdepartments?\s+(?:that\s+|which\s+)?"
    r"(?:refer|cite|rel(?:y|ies)|use|follow|link|depend)",
    re.I,
)
LINK_KINDS = frozenset(
    {
        EdgeKind.CITES,
        EdgeKind.REFERENCES,
        EdgeKind.AMENDS,
        EdgeKind.CLARIFIES,
        EdgeKind.SUPERSEDES,
        EdgeKind.REPEALS,
    }
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class OrderHistory(_Frozen):
    history: History
    covered: bool  # the scope covers the status of every member (else no "in force" is said)


class LinkedRecord(_Frozen):
    canonical_id: str
    department: str
    doc_type: str
    issue_date: dt.date | None
    kind: EdgeKind
    outward: bool  # True: the order asked about → this record; False: this record → the order


class IndirectLink(_Frozen):
    """seed —(first)— via —(second)— record of another department, every record visible."""

    via: LinkedRecord  # relative to the seed
    end: LinkedRecord  # relative to `via`


class CrossDepartment(_Frozen):
    seed: str
    department: str
    links: tuple[LinkedRecord, ...]  # only records of OTHER departments, all visible
    indirect: tuple[IndirectLink, ...] = ()  # two links away, through a visible record
    unavailable: bool = False  # the graph store failed: nothing may be read as "no links"


def order_history(ctx: ToolContext, seed: str) -> OrderHistory | None:
    """The visible lineage of `seed` on `ctx.as_of`, or None if the officer may not see it."""
    doc = visible_document(ctx, seed)
    if doc is None or seed not in ctx.instruments:
        return None
    inst, rels = visible_facts(ctx, {seed})
    if seed not in inst:
        return None
    h = history(seed, ctx.as_of, inst, rels)
    # "in force" is a status claim about EVERY member it names, so the officer's scope must cover
    # each member's status, not only the order asked about (the coverage rule, ADR-0050 add. 2)
    covered = all(
        (d := visible_document(ctx, m)) is not None and status_covered(ctx, d)
        for m in dict.fromkeys((seed, *h.lineage))
    )
    return OrderHistory(history=h, covered=covered)


MAX_STEPPING_STONES = 15  # records one link away that a two-link chain may pass through
MAX_INDIRECT = 10  # two-link chains described for one order


class _UnavailableError(Exception):
    """The graph store failed during a step: no link may be read as absent."""


def _neighbours(ctx: ToolContext, cid: str) -> list[LinkedRecord]:
    """Records one link from `cid`, both directions, each through the scoped walk AND re-checked.
    Raises _UnavailableError when the graph store fails (plan §14.4)."""
    out: dict[tuple[str, EdgeKind, bool], LinkedRecord] = {}
    for direction in (Direction.OUT, Direction.IN):
        exp = expand(
            ctx.user_id,
            [cid],
            graph=ctx.graph,
            kinds=LINK_KINDS,
            direction=direction,
            max_hops=1,
            store=ctx.store,
            policy=ctx.policy,
            classification=ctx.classification,
        )
        if exp.unavailable:
            raise _UnavailableError
        for h in exp.hits:
            other = visible_document(ctx, h.canonical_id)  # re-check every record named
            if other is None:
                continue
            key = (other.canonical_id, h.via, direction is Direction.OUT)
            out[key] = LinkedRecord(
                canonical_id=other.canonical_id,
                department=other.tags.department,
                doc_type=other.doc_type,
                issue_date=other.issue_date,
                kind=h.via,
                outward=direction is Direction.OUT,
            )
    return sorted(out.values(), key=_order)


def _order(r: LinkedRecord) -> tuple[str, dt.date, str, str]:
    return (r.department, r.issue_date or dt.date.min, r.canonical_id, r.kind.value)


def cross_department_links(ctx: ToolContext, seed: str) -> CrossDepartment | None:
    """Records of other departments linked to `seed`: one link away (both directions), and two
    links away through a stepping-stone record — each step a separate scoped walk with every
    record re-checked, so a chain never passes through a record outside the officer's scope."""
    doc = visible_document(ctx, seed)
    if doc is None:
        return None
    home = doc.tags.department
    try:
        first = _neighbours(ctx, seed)
        direct = [r for r in first if r.department != home]
        named = {seed} | {r.canonical_id for r in direct}
        indirect: dict[tuple[str, str], IndirectLink] = {}
        for via in first[:MAX_STEPPING_STONES]:
            for end in _neighbours(ctx, via.canonical_id):
                if end.department in (home, via.department) or end.canonical_id in named:
                    # a chain is worth telling only when it reaches a THIRD department (e.g. a
                    # Finance order → a GAD circular → an Urban Services file); a record of the
                    # stepping stone's own department, or one already linked directly, is not
                    continue
                key = (end.canonical_id, via.canonical_id)
                indirect.setdefault(key, IndirectLink(via=via, end=end))
    except _UnavailableError:
        return CrossDepartment(seed=seed, department=home, links=(), unavailable=True)
    chains = sorted(indirect.values(), key=lambda i: (_order(i.end), i.via.canonical_id))
    return CrossDepartment(
        seed=seed, department=home, links=tuple(direct), indirect=tuple(chains[:MAX_INDIRECT])
    )


class FileCitation(_Frozen):
    order: str  # an order the file's paper cites or refers to
    paper: str  # the paper (note, letter, draft) of the e-File that cites it
    paper_date: dt.date | None


def file_cited_orders(ctx: ToolContext, papers: list[str]) -> list[FileCitation] | None:
    """Orders the given e-File papers cite or refer to, through the scoped walk (one link out)
    with every record re-checked; oldest citation first. None when the graph store failed."""
    out: dict[tuple[str, str], FileCitation] = {}
    for paper in papers:
        doc = visible_document(ctx, paper)
        if doc is None:
            continue
        exp = expand(
            ctx.user_id,
            [paper],
            graph=ctx.graph,
            kinds=frozenset({EdgeKind.CITES, EdgeKind.REFERENCES}),
            direction=Direction.OUT,
            max_hops=1,
            store=ctx.store,
            policy=ctx.policy,
            classification=ctx.classification,
        )
        if exp.unavailable:
            return None
        for h in exp.hits:
            if h.canonical_id in ctx.instruments and visible_document(ctx, h.canonical_id):
                out[(h.canonical_id, paper)] = FileCitation(
                    order=h.canonical_id, paper=paper, paper_date=doc.issue_date
                )
    return sorted(out.values(), key=lambda f: (f.paper_date or dt.date.min, f.paper, f.order))
