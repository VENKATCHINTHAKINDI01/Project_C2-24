"""First-cut note — touchpoint 6 (plan §11.5): the cited points an officer needs to write a Yellow
Note, every line with its source. Deterministic; nothing here is written by a model.

- Orders that apply: `dfa.governing_orders` (same list as the DFA, so the two never disagree).
- Points from those orders: their paragraphs on the topics a proposal of this kind turns on — the
  ban / relaxation window, ceilings (a percentage), the competent authority, and the proposal's own
  ground ("on spouse grounds" in the file subject). Quoted verbatim with the clause ID; a paragraph
  number that is not unique in its order is not quoted (`clauses.clause_text`).
- Earlier decisions: Link-File precedents the officer may see, kept only when their text concerns
  the same action (the DFA's subject term, e.g. "transfer"). The decision is the LAST paragraph
  of the precedent's last note, quoted verbatim with its date — not summarised or classified. The
  date is then checked against the action windows in the officer's records (inside / outside).
- Open points: the pre-send check's flags.
The officer writes the note around these points (Gemini drafting later) and clicks "Insert as
Yellow Note", which creates a draft through the connector.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Iterable

from pydantic import BaseModel, ConfigDict

from app.agents.dfa import (
    SUBJECT_TERMS,
    LeftOut,
    OutdatedAuthority,
    ReadItem,
    governing_orders,
    outdated_authorities,
)
from app.agents.tools import ToolContext, visible_document
from app.conflict.deterministic import ConflictFlag
from app.conflict.procedural import Action
from app.identifiers.canonical import InvalidCanonicalIdError, clause_id
from app.ingestion.clauses import clause_text, clauses
from app.ingestion.metadata import DocType, DocumentMetadata
from app.noting.chain import parse_notes
from app.temporal.windows import ActionWindow

NOTE_TEXT_PENDING = (
    "[Note text: to be written by the officer around the cited points. Model drafting (Gemini) "
    "is not available in this sandbox.]"
)
_GROUND = re.compile(r"\bon\s+([a-z]+(?:\s+[a-z]+)?)\s+grounds?\b", re.I)
# Checked in order; a paragraph gets the first topic it matches (the ground is checked before the
# ban, so a spouse paragraph that mentions the ban stays a spouse point).
TOPICS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Ceiling", re.compile(r"\d+\s*%")),
    (
        "Competent authority",
        # named as such, or laid down as who orders / sanctions ("shall be ordered by the …")
        re.compile(
            r"\bcompetent authority\b|\bshall\s+be\s+(?:ordered|sanctioned|approved)\s+by\b"
            r"|\bno\s+officer\s+below\s+the\s+rank\b|\bshall\s+order\b",
            re.I,
        ),
    ),
)
BAN = ("Ban / relaxation window", re.compile(r"\bban\b|\brelax", re.I))
# Only a paragraph that lays something down is quoted as a provision (ADR-0060): a rule, an
# instruction, a limit, a delegation. A preamble ("Government have examined the question of …"),
# a recital of what was read or an operative formula ("orders are issued") is not.
_NORMATIVE = re.compile(
    r"\b(?:shall|may|must|should|will\s+be|is\s+hereby|are\s+hereby|is\s+relaxed|are\s+relaxed"
    r"|not\s+exceed|is\s+delegated|are\s+delegated|is\s+prohibited|is\s+permitted|preference"
    r"|eligible|competent\s+authority\s+(?:is|shall|will|for\s+.{3,80}?\s+(?:is|shall|will)))\b",
    re.I,
)
_PREAMBLE = re.compile(
    r"\b(?:have\s+examined|has\s+examined|read\s+the\s+following|read\s+above"
    r"|in\s+the\s+(?:G\.?O\.?|reference|circumstances)\s+(?:\d+(?:st|nd|rd|th)\s+)?read"
    r"|after\s+careful\s+(?:examination|consideration)|the\s+following\s+orders\s+are\s+issued"
    r"|hereby\s+issue\s+the\s+following)\b",
    re.I,
)


def substantive(body: str) -> bool:
    """A paragraph that states a rule, instruction, limit or delegation — not a preamble."""
    return bool(_NORMATIVE.search(body)) and not _PREAMBLE.search(body)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CitedPoint(_Frozen):
    topic: str
    clause_id: str
    text: str  # the paragraph, verbatim


class PrecedentDecision(_Frozen):
    file_no: str
    source: str  # canonical ID of the precedent note document
    note_no: int
    paragraph: int | None
    decided_on: dt.date | None
    decision: str  # the last paragraph of the last note, verbatim
    windows: tuple[str, ...]  # clause IDs of action windows covering `decided_on`
    in_window: bool | None  # None: no date, or no windows for this action in the officer's records
    # orders the decision's note sheet relies on that are no longer in force on the as-of date: the
    # decision is history, never current practice (ADR-0045)
    outdated: tuple[OutdatedAuthority, ...] = ()


class FirstCut(_Frozen):
    file_no: str
    draft_note: str | None
    ground: str | None
    orders: tuple[ReadItem, ...]
    left_out: tuple[LeftOut, ...]
    points: tuple[CitedPoint, ...]
    precedents: tuple[PrecedentDecision, ...]
    flags: tuple[ConflictFlag, ...]
    body: str
    citations: tuple[str, ...]


def ground_of(subject: str) -> str | None:
    """'… Vijayawada on spouse grounds – Reg.' → 'spouse'."""
    m = _GROUND.search(subject)
    return m.group(1).lower() if m else None


def _points(order: str, text: str, ground: str | None) -> list[CitedPoint]:
    topics = list(TOPICS)
    if ground:
        topics.append((f"{ground.capitalize()} cases", re.compile(rf"\b{re.escape(ground)}", re.I)))
    topics.append(BAN)
    out: list[CitedPoint] = []
    seen: set[str] = set()
    for loc, _ in clauses(text):
        if loc in seen or "." not in loc and any(o.startswith(f"{loc}.") for o, _ in clauses(text)):
            continue  # a paragraph with sub-clauses: quote the sub-clauses, not the heading
        body = clause_text(text, loc)
        if body is None or not substantive(body):
            continue
        for name, pat in topics:
            if pat.search(body):
                try:
                    out.append(CitedPoint(topic=name, clause_id=clause_id(order, loc), text=body))
                except InvalidCanonicalIdError:
                    pass
                seen.add(loc)
                break
    return out


def _decision(
    file_no: str,
    cid: str,
    text: str,
    action: Action | None,
    windows: list[ActionWindow],
) -> PrecedentDecision | None:
    notes = parse_notes(text, cid)
    if not notes or not notes[-1].by_paragraph:
        return None
    last = notes[-1]
    para, words = last.by_paragraph[-1]
    day = last.signed_at.date() if last.signed_at else None
    mine = [w for w in windows if action is not None and w.action == action.value]
    hits = tuple(w.source for w in mine if day and w.start <= day <= w.end)
    return PrecedentDecision(
        file_no=file_no,
        source=cid,
        note_no=last.note_no,
        paragraph=para,
        decided_on=day,
        decision=words,
        windows=hits,
        in_window=(bool(hits) if day and mine else None),
    )


def first_cut_note(
    *,
    ctx: ToolContext,
    file_no: str,
    subject: str,
    draft_note: str | None,
    meta: DocumentMetadata | None,
    action: Action | None,
    flags: Iterable[ConflictFlag],
    precedents: Iterable[tuple[str, str]],
    text_of: Callable[[str], str],
    windows: Iterable[ActionWindow],
) -> FirstCut:
    """`precedents`: (file no., canonical ID) of precedent notes the officer may see (Link File);
    `windows`: action windows extracted at ingestion — only those from orders in `orders` or
    otherwise visible are used (the caller passes the officer's visible ones)."""
    orders, left_out = governing_orders(ctx, meta, action)
    ground = ground_of(subject)
    points = [p for o in orders for p in _points(o.canonical_id, text_of(o.canonical_id), ground)]
    wins = list(windows)
    term = SUBJECT_TERMS.get(action) if action is not None else None
    decisions = [
        d
        for f, cid in precedents
        if (not term or any(t in text_of(cid).lower() for t in term))  # same kind of case only
        # a proposal put up and not yet decided (a draft note) is no decision at all
        and (doc := visible_document(ctx, cid)) is not None
        and doc.doc_type != DocType.NOTING_DRAFT.value
        and (d := _decision(f, cid, text_of(cid), action, wins)) is not None
    ]
    decisions = [
        d.model_copy(update={"outdated": outdated_authorities(ctx, d.source)}) for d in decisions
    ]
    decisions.sort(key=lambda d: (d.decided_on or dt.date.min, d.source))
    flags = tuple(flags)

    def when(d: dt.date | None) -> str:
        return d.strftime("%d-%m-%Y") if d else "date not recorded"

    def window_line(p: PrecedentDecision) -> str:
        if p.in_window is None:
            return "no relaxation window in your records to compare"
        if p.in_window:
            return f"inside the window in {', '.join(p.windows)}"
        return "outside every relaxation window in your records"

    def outdated_line(p: PrecedentDecision) -> str:
        return "".join(
            " Whether the orders it rested on are still in force could not be checked just now."
            if x.status == "unverified"
            else f" It rested on {x.order}, since {x.status}"
            + (f" (use {x.use_instead})" if x.use_instead else "")
            + ": history, not current practice."
            for x in p.outdated
        )

    lines = [
        "FIRST-CUT NOTE — cited points, prepared with C2-24 Assist; a draft for the officer.",
        f"Subject: {subject}",
        "",
        "Orders that apply:",
        *[
            f"{n}. {o.canonical_id}, dated {when(o.issue_date)} — {o.subject}"
            + (f" (in place of {', '.join(o.in_place_of)})" if o.in_place_of else "")
            + ("" if o.status_confirmed else " [status not confirmed from your records]")
            for n, o in enumerate(orders, 1)
        ],
        "",
        "Points from those orders:",
        *[f"- {p.topic}: “{p.text}” [{p.clause_id}]" for p in points],
    ]
    if decisions:
        lines += ["", "Earlier decisions in similar cases (files you may see):"]
        lines += [
            f"- File {p.file_no}, Note #{p.note_no}, {when(p.decided_on)}: "
            f"“{p.decision}” [{p.source}] — {window_line(p)}.{outdated_line(p)}"
            for p in decisions
        ]
    if flags or left_out:
        lines += ["", "Open points (pre-send check):"]
        lines += [f"- {f.type.value}: {f.explanation}" for f in flags]
        lines += [f"- Not relied on: {x.cited} — {x.reason}." for x in left_out]
    lines += ["", NOTE_TEXT_PENDING]
    cites = [
        *(o.canonical_id for o in orders),
        *(p.clause_id for p in points),
        *(p.source for p in decisions),
        *(w for p in decisions for w in p.windows),
    ]
    return FirstCut(
        file_no=file_no,
        draft_note=draft_note,
        ground=ground,
        orders=orders,
        left_out=left_out,
        points=tuple(points),
        precedents=tuple(decisions),
        flags=flags,
        body="\n".join(lines),
        citations=tuple(dict.fromkeys(cites)),
    )
