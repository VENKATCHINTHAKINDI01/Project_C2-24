"""Authorization schemas: principal, document access tags, policy, scope, decision (plan §5.1-§5.2).

Permissions are NOT stored on documents. Documents carry only where they live (department,
section, file, classification). Who may see them is decided per request from the access store
(`app.auth.store`): rank, e-Office search scope, section, clearance, file assignments, movements.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SearchScope(StrEnum):
    """e-Office search-privilege scopes (eFile 7.x user manual; plan §11.2, §11.4)."""

    GLOBAL = "global"
    DEPARTMENT = "department"
    SECTION_HIERARCHY = "section_hierarchy"
    SECTION = "section"
    POST_HIERARCHY = "post_hierarchy"
    INDIVIDUAL = "individual"


class Principal(_Frozen):
    """The signed-in officer as the access store knows them at request time (plan §11.4).

    Built by `AuthzStore.principal`, never from caller-supplied claims.
    `section=None` means no single section (e.g. "ALL"); it never widens access by itself.
    """

    user_id: str = Field(min_length=1)
    department: str = Field(min_length=1)
    section: str | None = None
    clearance: str = Field(min_length=1)
    role_rank: int = Field(ge=0)
    search_scopes: frozenset[SearchScope] = frozenset()
    assigned_files: frozenset[str] = frozenset()
    handled_files: frozenset[str] = frozenset()  # files that passed through the officer


class DocumentAccessTags(_Frozen):
    """Where a document lives (plan §4.6). Mirrored into indexes as filterable fields."""

    doc_id: str = Field(min_length=1)
    department: str = Field(min_length=1)
    section: str | None = None
    classification: str = Field(min_length=1)
    file_no: str | None = None


class StatusCoverage(StrEnum):
    """How much of an issuing department an officer must be able to see before a temporal status
    is reported (owner decision, 3 Nov 2026). Decided from the officer's scope only, never from
    which records exist, so the outcome cannot reveal a hidden superseding order."""

    FULL_DEPARTMENT = "full_department"  # department-wide up to the top classification (strict)
    UP_TO_DOCUMENT = "up_to_document"  # department-wide up to the order's own classification;
    #                                    public orders: everyone (assumes an order is only changed
    #                                    by records no more restricted than itself — [To confirm])


class AccessPolicy(_Frozen):
    """Policy parameters from `data/ontology/access_policy.yaml` (mock, [To confirm])."""

    version: str
    status: str
    public_classification: str
    department_wide_min_role_rank: int = Field(ge=1)
    department_wide_scopes: frozenset[SearchScope]
    section_scopes: frozenset[SearchScope]
    handled_files_grant_access: bool
    status_coverage: StatusCoverage = StatusCoverage.FULL_DEPARTMENT


class DecisionReason(StrEnum):
    """Why a decision was taken. For audit only — never shown to the officer (plan §5.4)."""

    PUBLIC = "public"
    SENIOR_IN_DEPARTMENT = "senior_in_department"
    SAME_SECTION = "same_section"
    ASSIGNED_FILE = "assigned_file"
    HANDLED_FILE = "handled_file"
    OTHER_DEPARTMENT = "other_department"
    CLEARANCE_TOO_LOW = "clearance_too_low"
    NO_SECTION_OR_ASSIGNMENT = "no_section_or_assignment"
    UNKNOWN_CLASSIFICATION = "unknown_classification"
    UNKNOWN_USER = "unknown_user"
    ERROR = "error"


class AccessDecision(_Frozen):
    allowed: bool
    reason: DecisionReason
    policy_version: str


class Scope(_Frozen):
    """Pre-retrieval filter from `compute_scope` (plan §5.2), required by every retriever.

    Plain values so it renders to BigQuery / Vertex AI Search filters later; `admits` is the
    in-memory form.
    """

    user_id: str
    policy_version: str
    classification_ranks: dict[str, int]
    public_rank: int
    department: str
    max_rank: int
    department_wide: bool
    sections: frozenset[str]
    file_nos: frozenset[str]

    def covers_status_domain(self, department: str, ceiling: str) -> bool:
        """True if this scope sees EVERY record of `department` up to `ceiling` (plan §5.4).

        Depends only on the scope, so it is the same whether or not restricted records exist.
        Unknown ceiling → False (fail closed).
        """
        rank = self.classification_ranks.get(ceiling)
        if rank is None:
            return False
        if rank == self.public_rank:
            return True  # public records are visible to everyone
        return self.department == department and self.department_wide and self.max_rank >= rank

    def admits(self, doc: DocumentAccessTags) -> bool:
        """True if `doc` is inside this scope. Unknown classification → outside (fail closed)."""
        rank = self.classification_ranks.get(doc.classification)
        if rank is None:
            return False
        if rank == self.public_rank and doc.file_no is None:
            return True  # a published instrument; papers inside an e-File are never public
        if doc.department != self.department or rank > self.max_rank:
            return False
        return (
            self.department_wide
            or (doc.section is not None and doc.section in self.sections)
            or (doc.file_no is not None and doc.file_no in self.file_nos)
        )

    @property
    def signature(self) -> str:
        """Hash of everything that defines what the scope can see; keys the shared answer cache
        (plan §10.2, ADR-0009: officers with identical permissions share answers). Excludes the
        user ID; any change in rank, search scope, clearance, section, assignment, movement or
        policy version changes it, so stale answers can never be served after a permission change.
        """
        payload = {
            "policy": self.policy_version,
            "ranks": sorted(self.classification_ranks.items()),
            "public": self.public_rank,
            "dept": self.department,
            "max": self.max_rank,
            "wide": self.department_wide,
            "sections": sorted(self.sections),
            "files": sorted(self.file_nos),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(blob).hexdigest()
