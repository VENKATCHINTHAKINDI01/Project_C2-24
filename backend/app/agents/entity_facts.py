"""People and offices a question names, resolved to the records the officer may see (ADR-0058).

The entity index (`app/identifiers/entities.py`) says which records name a person or an office; it
is not an access boundary. Here every record is re-checked with `visible_document`, and a person
or office is "found" only through records this officer may see. Roles are taken only from those
records. So a name that appears only in records outside the scope gives exactly what a name that
appears nowhere gives: nothing (CLAUDE.md §4.7).
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from app.agents.tools import ToolContext, visible_document
from app.identifiers.entities import EntityKind, QueryEntity, in_question

MAX_RECORDS = 12  # records listed for one person or office


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class NamedRecord(_Frozen):
    canonical_id: str
    doc_type: str
    file_no: str | None
    issue_date: dt.date | None
    signed: bool  # the person signed it (a noting signature), rather than being written about


class EntityMatch(_Frozen):
    kind: EntityKind
    asked: str  # as the question wrote it
    key: str
    shown_as: str  # how the visible records write the name
    roles: tuple[str, ...]  # designations / offices the visible records give, most frequent first
    records: tuple[NamedRecord, ...]  # visible records only, oldest first
    partial: bool  # the question gave no initials: a name-words match
    officer_id: str | None = None  # an e-Office officer: the ID is the identity (ADR-0058)


def named_entities(ctx: ToolContext) -> set[str]:
    return ctx.entities.person_names() if ctx.entities is not None else set()


def resolve(ctx: ToolContext, question: str) -> list[EntityMatch]:
    """Each person / office the question names that visible records name, with those records."""
    if ctx.entities is None:
        return []
    out: list[EntityMatch] = []
    for q in in_question(question, named_entities(ctx), ctx.entities.officer_ids()):
        for key in ctx.entities.keys_for(q):
            out += _match(ctx, q, key)
    return out


def _match(ctx: ToolContext, q: QueryEntity, key: str) -> list[EntityMatch]:
    assert ctx.entities is not None
    recs: list[NamedRecord] = []
    roles: dict[str, int] = {}
    written: list[str] = []
    for cid, ms in ctx.entities.records(key).items():
        doc = visible_document(ctx, cid)  # re-check every record
        if doc is None:
            continue
        signed = any(m.signed for m in ms)
        recs.append(
            NamedRecord(
                canonical_id=cid,
                doc_type=doc.doc_type,
                file_no=doc.tags.file_no,
                issue_date=doc.issue_date,
                signed=signed,
            )
        )
        for m in ms:
            written.append(m.surface)
            if m.role:
                roles[m.role] = roles.get(m.role, 0) + 1
    if not recs:
        return []
    recs.sort(key=lambda r: (r.issue_date or dt.date.min, r.canonical_id))
    # as the records write it: with an honorific when any visible record gives one
    honorific = [w for w in written if not w[:2].isupper() and w.split()[0][-1:] != "."]
    surface = (honorific or written)[0]
    return [
        EntityMatch(
            kind=q.kind,
            asked=q.surface,
            key=key,
            shown_as=surface,
            roles=tuple(sorted(roles, key=lambda r: (-roles[r], r))),
            records=tuple(recs),
            partial=q.partial,
            officer_id=key.removeprefix("officer:") if key.startswith("officer:") else None,
        )
    ]
