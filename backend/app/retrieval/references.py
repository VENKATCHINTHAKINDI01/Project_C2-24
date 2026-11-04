"""Reference lookup for L0 when the department may be missing (plan §3.2, §4.4; Q18 gap).

"GO Ms 88/2022" names no department. Instead of assuming the officer's own department, every
department's candidate is looked up INSIDE the officer's scope: one hit → found; several →
ambiguous, ask the officer (choices are only documents they may see, so asking leaks nothing);
none → not found. Restricted matches are invisible here, exactly as in every other rung.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.auth.models import AccessPolicy
from app.auth.store import AuthzStore
from app.config import Classification
from app.identifiers.resolver import DepartmentTable, reference_candidates
from app.retrieval.scoped import Rung, ScopedRetriever, retrieve


class LookupStatus(StrEnum):
    FOUND = "found"
    AMBIGUOUS = "ambiguous"  # ask the officer to choose
    NOT_FOUND = "not_found"  # resolvable, but nothing in the officer's records
    UNRESOLVED = "unresolved"  # not a resolvable reference (e.g. no year) → review / type E


class ReferenceLookup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    raw: str
    status: LookupStatus
    canonical_id: str | None = None
    choices: tuple[str, ...] = ()
    candidates_tried: int = 0


def lookup_reference(
    user_id: str,
    text: str,
    *,
    departments: DepartmentTable,
    retriever: ScopedRetriever,
    store: AuthzStore,
    policy: AccessPolicy,
    classification: Classification,
) -> ReferenceLookup:
    candidates = reference_candidates(text, departments)
    if not candidates:
        return ReferenceLookup(raw=text, status=LookupStatus.UNRESOLVED)
    found: list[str] = []
    for cid in candidates:
        res = retrieve(
            user_id,
            Rung.L0,
            cid,
            retriever=retriever,
            store=store,
            policy=policy,
            classification=classification,
        )
        for d in res.documents:
            if d.canonical_id not in found:
                found.append(d.canonical_id)
    n = len(candidates)
    if len(found) == 1:
        return ReferenceLookup(
            raw=text, status=LookupStatus.FOUND, canonical_id=found[0], candidates_tried=n
        )
    if found:
        return ReferenceLookup(
            raw=text, status=LookupStatus.AMBIGUOUS, choices=tuple(found), candidates_tried=n
        )
    return ReferenceLookup(raw=text, status=LookupStatus.NOT_FOUND, candidates_tried=n)
