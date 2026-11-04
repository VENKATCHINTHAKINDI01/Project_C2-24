"""Access store: permissions as relationship tuples, read fresh on every request (plan §5.1).

`(subject, relation, object)` e.g. ``(user:U04, assigned, file:USD01-31/4/2025-VIG)``. This is the
"real access control" layer: grants and revocations live here, not on documents, and take effect
on the next request (CLAUDE.md §4.9). The in-memory store is the reference implementation and the
test double; the Cloud SQL store (`data/schemas/authz.sql`) implements the same Protocol.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.auth.models import Principal, SearchScope


class Relation(StrEnum):
    MEMBER_OF = "member_of"  # user → department:<code>
    IN_SECTION = "in_section"  # user → section:<code>
    HAS_CLEARANCE = "has_clearance"  # user → clearance:<name>
    HAS_RANK = "has_rank"  # user → rank:<int>   (from the post, ADR-0008)
    HAS_SEARCH_SCOPE = "has_search_scope"  # user → scope:<SearchScope>
    ASSIGNED = "assigned"  # user → file:<file_no>
    HANDLED = "handled"  # user → file:<file_no> (movement trail)


class AccessTuple(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    subject: str  # "user:U01"
    relation: Relation
    object: str  # "<type>:<id>"


class StoreError(Exception):
    """Incomplete or contradictory grants. Callers must deny (fail closed, plan §5.9)."""


@runtime_checkable
class AuthzStore(Protocol):
    @property
    def version(self) -> int:
        """Increases on every write or delete (audit / cache diagnostics)."""
        ...

    def principal(self, user_id: str) -> Principal:
        """Current grants for `user_id`. Raises StoreError if unknown or incomplete."""
        ...


_SINGLE = {
    Relation.MEMBER_OF: "department",
    Relation.IN_SECTION: "section",
    Relation.HAS_CLEARANCE: "clearance",
    Relation.HAS_RANK: "rank",
}


def _split(obj: str, expected: str) -> str:
    kind, sep, value = obj.partition(":")
    if not sep or kind != expected or not value:
        raise StoreError(f"bad object {obj!r}, expected {expected}:<id>")
    return value


class InMemoryAuthzStore:
    """Reference AuthzStore (plan §5.1 'simple-first'); mock data only."""

    def __init__(self, tuples: Iterable[AccessTuple] = ()) -> None:
        self._tuples: set[AccessTuple] = set()
        self._version = 0
        self.write(tuples)

    @property
    def version(self) -> int:
        return self._version

    def write(self, tuples: Iterable[AccessTuple]) -> None:
        for t in tuples:
            self._tuples.add(t)
        self._version += 1

    def delete(self, tuples: Iterable[AccessTuple]) -> None:
        for t in tuples:
            self._tuples.discard(t)
        self._version += 1

    def tuples_of(self, user_id: str) -> list[AccessTuple]:
        return sorted(
            (t for t in self._tuples if t.subject == f"user:{user_id}"),
            key=lambda t: (t.relation, t.object),
        )

    def principal(self, user_id: str) -> Principal:
        mine = [t for t in self._tuples if t.subject == f"user:{user_id}"]
        if not mine:
            raise StoreError("unknown user")
        single: dict[Relation, list[str]] = {r: [] for r in _SINGLE}
        scopes: set[SearchScope] = set()
        assigned: set[str] = set()
        handled: set[str] = set()
        for t in mine:
            if t.relation in _SINGLE:
                single[t.relation].append(_split(t.object, _SINGLE[t.relation]))
            elif t.relation is Relation.HAS_SEARCH_SCOPE:
                try:
                    scopes.add(SearchScope(_split(t.object, "scope")))
                except ValueError as exc:
                    raise StoreError("unknown search scope") from exc
            elif t.relation is Relation.ASSIGNED:
                assigned.add(_split(t.object, "file"))
            elif t.relation is Relation.HANDLED:
                handled.add(_split(t.object, "file"))
        for rel in (Relation.MEMBER_OF, Relation.HAS_CLEARANCE, Relation.HAS_RANK):
            if len(single[rel]) != 1:
                raise StoreError(f"user needs exactly one {rel.value}")
        if len(single[Relation.IN_SECTION]) > 1:
            raise StoreError("user has more than one section")
        try:
            rank = int(single[Relation.HAS_RANK][0])
        except ValueError as exc:
            raise StoreError("rank must be an integer") from exc
        return Principal(
            user_id=user_id,
            department=single[Relation.MEMBER_OF][0],
            section=single[Relation.IN_SECTION][0] if single[Relation.IN_SECTION] else None,
            clearance=single[Relation.HAS_CLEARANCE][0],
            role_rank=rank,
            search_scopes=frozenset(scopes),
            assigned_files=frozenset(assigned),
            handled_files=frozenset(handled),
        )
