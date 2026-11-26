"""Draft for approval (DFA) — touchpoint 14 (plan §11.5): the deterministic parts of draft
proceedings, put up with the file. Nothing here is written by a model.

- Abstract: proposed from the file's subject ("… – Reg." → "… – Orders – Issued.").
- "Read the following": the orders the draft note cites, plus the orders in force on the proposal's
  subject (L1 current-rule template; subject term from the proposal's action). Each is followed
  along its supersession chain to the latest order the officer may see; a cited order that was
  superseded is listed as its successor ("in place of …"). Orders not found, repealed, expired or
  not yet in force are left out and named in `left_out`. "Current" is not claimed for an order
  whose status the officer's records can't confirm (owner rule, 3 Nov 2026): it is listed with
  `status_confirmed=False`.
- Order paragraphs: NOT drafted (that is Gemini's job, GCP). The body says so in place.
- Open points: the pre-send check's flags travel with the draft, so the approver sees them.
The officer edits and clicks "Create DFA draft" (a draft via the connector); C2-24 never signs,
issues or dispatches.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Iterable, Mapping

from pydantic import BaseModel, ConfigDict

from app.agents.intents import ORDER_TYPES
from app.agents.tools import (
    ToolContext,
    current_rule_ladder,
    status_covered,
    visible_document,
    visible_facts,
)
from app.auth.models import DocumentAccessTags
from app.auth.policy import check
from app.conflict.deterministic import ConflictFlag
from app.conflict.procedural import Action
from app.graph.repository import Direction, EdgeKind
from app.identifiers.canonical import InvalidCanonicalIdError, lookup_keys, parse_canonical_id
from app.ingestion.metadata import DocumentMetadata
from app.retrieval.graph_expansion import expand
from app.temporal.engine import Instrument, Status, TemporalRelation, status_as_of

# The proposal's action → the word its orders carry in their subject (same vocabulary the facts
# reader uses to recognise the action in a note).
SUBJECT_TERMS: dict[Action, tuple[str, ...]] = {
    Action.TRANSFER: ("transfer",),
    Action.WORKS_SANCTION: ("works",),
    Action.OUTSOURCING: ("outsourcing",),
}


def action_in_words(*texts: str) -> Action | None:
    """The action a matter is about, read from its own words (file subject, notes) when the
    proposal reader found none (26 Nov 2026: "Request for transfer on spouse grounds" with a
    plain request note gave no orders). Same fixed terms as SUBJECT_TERMS; never a model."""
    words = " ".join(t.lower() for t in texts if t)
    hits = [
        a for a, terms in SUBJECT_TERMS.items() if any(re.search(rf"\b{t}", words) for t in terms)
    ]
    return hits[0] if len(hits) == 1 else None


# Orders found by subject (not cited in the note): at most this many, from the file's own
# department (first) or a department whose orders apply across departments, then the most
# relevant. 26 Nov 2026: on the
# cloud corpus "transfer" matched 68 orders (School Education teacher rules among them), the draft
# passed the 20,000-character limit and could not be inserted. Mock values [To confirm].
MAX_SUBJECT_ORDERS = 5
GENERAL_ORDER_DEPARTMENTS = ("FIN01", "GAD01")

ORDER_PARAGRAPHS_PENDING = (
    "[Order paragraphs: to be written by the officer. Model drafting (Gemini) is not available "
    "in this sandbox.]"
)
_MAX_CHAIN = 10


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ReadItem(_Frozen):
    canonical_id: str
    doc_type: str
    subject: str
    issue_date: dt.date | None
    in_place_of: tuple[str, ...] = ()  # cited orders this one supersedes in the list
    cited_in_note: bool
    status_confirmed: bool  # False: the officer's records can't confirm it is still in force


class LeftOut(_Frozen):
    cited: str  # canonical ID or the note's raw words
    reason: str


class DfaPreview(_Frozen):
    file_no: str
    draft_note: str | None
    abstract: str
    read_list: tuple[ReadItem, ...]
    left_out: tuple[LeftOut, ...]
    flags: tuple[ConflictFlag, ...]
    caveats: tuple[str, ...]
    body: str
    citations: tuple[str, ...]


def abstract_from_subject(subject: str) -> str:
    s = re.sub(r"\s*[–-]\s*Reg\.?\s*$", "", subject.strip())
    return f"{s} – Orders – Issued."


def _fmt(d: dt.date | None) -> str:
    return d.strftime("%d-%m-%Y") if d else "date not recorded"


def _resolve(ctx: ToolContext, cid: str, known: Iterable[str]) -> str | None:
    """A cited ID to the one visible record it names (exact, undated, or the single dated one)."""
    try:
        for k in lookup_keys(cid):
            if visible_document(ctx, k) is not None:
                return k
        base = parse_canonical_id(cid).base_id
    except InvalidCanonicalIdError:
        return None
    same = [k for k in known if _base(k) == base and visible_document(ctx, k) is not None]
    return same[0] if len(same) == 1 else None


def _base(cid: str) -> str | None:
    try:
        return parse_canonical_id(cid).base_id
    except InvalidCanonicalIdError:
        return None


def _walk(
    ctx: ToolContext, cid: str, inst: Mapping[str, Instrument], rels: list[TemporalRelation]
) -> tuple[str, str | None]:
    """Follow `cid` along its supersession chain (visible facts only) to the latest order;
    the reason it cannot be read, if any (repealed / expired / not yet in force)."""
    here, hops = cid, 0
    while hops < _MAX_CHAIN and here in inst:
        st = status_as_of(here, ctx.as_of, inst, rels)
        if st.status is Status.SUPERSEDED and st.by:
            here, hops = st.by, hops + 1
            continue
        if st.status is Status.REPEALED:
            return here, f"repealed{' by ' + st.by if st.by else ''}"
        if st.status is Status.EXPIRED:
            return here, "no longer in force on the proposal date"
        if st.status is Status.NOT_YET_EFFECTIVE:
            return here, "not yet in force on the proposal date"
        break
    return here, None


class OutdatedAuthority(BaseModel):
    """An order a paper rests on that is no longer in force on the as-of date (ADR-0045)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order: str
    status: str  # superseded / repealed / expired
    use_instead: str | None  # the latest order in its chain the officer may see


# plan §14.4: the graph store failed while checking what a decision rested on
AUTHORITIES_UNVERIFIED = OutdatedAuthority(order="", status="unverified", use_instead=None)


def outdated_authorities(ctx: ToolContext, cid: str) -> tuple[OutdatedAuthority, ...]:
    """The orders a paper cites (its direct graph edges, walked within the officer's scope and
    each re-checked) that are no longer in force on `ctx.as_of`. A decision that rested on one is
    history, not current practice: callers say so wherever it is quoted. Facts about records the
    officer may not see are never used."""
    hop = expand(
        ctx.user_id,
        [cid],
        graph=ctx.graph,
        kinds=frozenset({EdgeKind.CITES, EdgeKind.REFERENCES}),
        direction=Direction.OUT,
        max_hops=1,  # what the paper itself cites: a structural choice, not a tuned threshold
        store=ctx.store,
        policy=ctx.policy,
        classification=ctx.classification,
    )
    if hop.unavailable:  # nothing may be read as "still in force": say it could not be checked
        return (AUTHORITIES_UNVERIFIED,)
    cited = sorted(
        {
            h.canonical_id
            for h in hop.hits
            if (d := visible_document(ctx, h.canonical_id)) is not None
            and d.doc_type in ORDER_TYPES
        }
    )
    inst, rels = visible_facts(ctx, set(cited))
    out: list[OutdatedAuthority] = []
    for order in cited:
        if order not in inst:
            continue
        st = status_as_of(order, ctx.as_of, inst, rels)
        if st.status in (Status.SUPERSEDED, Status.REPEALED, Status.EXPIRED):
            latest, _ = _walk(ctx, order, inst, rels)
            out.append(
                OutdatedAuthority(
                    order=order,
                    status=st.status.value,
                    use_instead=latest if latest != order else None,
                )
            )
    return tuple(out)


def follow_chain(ctx: ToolContext, cid: str) -> tuple[str, str | None]:
    """`cid` → the latest order in its chain the officer may see, and why it cannot be read
    (None if it can). Only facts about records the officer may see are used."""
    inst, rels = visible_facts(ctx, {cid})
    return _walk(ctx, cid, inst, rels)


def governing_orders(
    ctx: ToolContext, meta: DocumentMetadata | None, action: Action | None
) -> tuple[tuple[ReadItem, ...], tuple[LeftOut, ...]]:
    """The orders that govern a proposal, as the officer's records show them (see module doc):
    cited + in force on the action's subject, each followed to its latest visible version."""
    left_out: list[LeftOut] = []
    cited: list[tuple[str, str]] = []  # (raw, visible canonical ID)
    for ref in meta.references if meta else ():
        if ref.raw.startswith("file:"):
            continue
        hit = _resolve(ctx, ref.canonical_id, ctx.instruments) if ref.canonical_id else None
        if hit is None:
            left_out.append(
                LeftOut(
                    cited=ref.canonical_id or ref.raw.strip(),
                    reason="not found in the records available to you",
                )
            )
        else:
            cited.append((ref.raw, hit))

    found: list[str] = [c for _, c in cited]
    if action is not None and action in SUBJECT_TERMS:
        res = current_rule_ladder(ctx, SUBJECT_TERMS[action])
        found += [d.canonical_id for d in res.documents if d.doc_type in ORDER_TYPES]

    inst, rels = visible_facts(ctx, set(found))
    items: dict[str, ReadItem] = {}
    dept: dict[str, str] = {}
    rank: dict[str, int] = {}  # latest version → its best position among the orders found
    cited_ids = {c for _, c in cited}
    for cid in dict.fromkeys(found):
        here, reason = _walk(ctx, cid, inst, rels)
        if reason:
            if cid in cited_ids:
                left_out.append(LeftOut(cited=cid, reason=reason))
            continue
        doc = visible_document(ctx, here)
        if doc is None:
            continue
        dept[here] = doc.tags.department
        rank.setdefault(here, len(rank))
        prev = items.get(here)
        replaced = (cid,) if (cid != here and cid in cited_ids) else ()
        items[here] = ReadItem(
            canonical_id=here,
            doc_type=doc.doc_type,
            subject=doc.subject,
            issue_date=doc.issue_date,
            in_place_of=tuple(dict.fromkeys((*(prev.in_place_of if prev else ()), *replaced))),
            cited_in_note=(here in cited_ids) or bool(prev and prev.cited_in_note),
            status_confirmed=status_covered(ctx, doc),
        )
    home = meta.department if meta else None
    by_subject = sorted(
        (
            c
            for c, i in items.items()
            if not i.cited_in_note
            and (dept.get(c) == home or dept.get(c) in GENERAL_ORDER_DEPARTMENTS)
        ),
        # the department's own orders first, then the ladder's own order (most relevant first)
        key=lambda c: (dept.get(c) != home, rank.get(c, len(rank))),
    )[:MAX_SUBJECT_ORDERS]
    items = {c: i for c, i in items.items() if i.cited_in_note or c in by_subject}
    read_list = tuple(
        sorted(items.values(), key=lambda i: (i.issue_date or dt.date.min, i.canonical_id))
    )
    return read_list, tuple(left_out)


def draft_for_approval(
    *,
    ctx: ToolContext,
    file_no: str,
    subject: str,
    draft_note: str | None,
    meta: DocumentMetadata | None,
    action: Action | None,
    flags: Iterable[ConflictFlag],
    awaiting_review: Iterable[DocumentAccessTags] = (),
    label: Callable[[str], str] | None = None,
) -> DfaPreview:
    """`meta`/`action`: read from the file's latest note the officer may see (None: no note)."""
    read_list, left_out = governing_orders(ctx, meta, action)
    caveats: list[str] = []
    if any(not i.status_confirmed for i in read_list):
        caveats.append(
            "Some orders are listed as the latest version in your records; whether they are "
            "still current could not be confirmed from the records available to you."
        )
    if any(
        check(ctx.user_id, t, ctx.store, ctx.policy, ctx.classification).allowed
        for t in awaiting_review
    ):
        caveats.append(
            "Some records you may see are awaiting review (for example scans not yet read); "
            "orders among them are not in this list."
        )
    flags = tuple(flags)
    abstract = abstract_from_subject(subject)
    name = label or (lambda c: c)
    lines = [
        "DRAFT FOR APPROVAL — prepared with C2-24 Assist; not approved, signed or issued.",
        "",
        "ABSTRACT",
        abstract,
        "",
        "Read the following:",
        *[
            f"{n}. {name(i.canonical_id)}, dated {_fmt(i.issue_date)} — {i.subject}"
            + (f" (in place of {', '.join(i.in_place_of)})" if i.in_place_of else "")
            for n, i in enumerate(read_list, 1)
        ],
        "",
        "ORDER:",
        ORDER_PARAGRAPHS_PENDING,
    ]
    if flags or left_out:
        lines += ["", "Open points for the approving officer (from the pre-send check):"]
        lines += [f"- {f.type.value}: {f.explanation}" for f in flags]
        lines += [f"- Not listed: {x.cited} — {x.reason}." for x in left_out]
    return DfaPreview(
        file_no=file_no,
        draft_note=draft_note,
        abstract=abstract,
        read_list=read_list,
        left_out=tuple(left_out),
        flags=flags,
        caveats=tuple(caveats),
        body="\n".join(lines),
        citations=tuple(i.canonical_id for i in read_list),
    )
