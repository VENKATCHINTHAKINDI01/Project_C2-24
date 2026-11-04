"""Canonical-ID collision registry (plan §4.4; ADR-0007 suffix rule, owner decision 2026-11-03).

Two different orders can share department, type, number and year (e.g. two Finance G.O.Ms.126 of
2023). Rules:

1. The first record keeps the unsuffixed ID (compatibility: existing citations stay valid).
2. A later colliding record gets the order's own **section code** as suffix
   (``AP-FIN01-GOMS-126-2023-HRIII``) when the order prints one AND it distinguishes the record
   from every other member of the collision group.
3. Otherwise (no reliable section code, or the code does not distinguish) a **registry suffix**
   ``-C01``, ``-C02`` … from a per-group counter that only ever increases.
4. An assignment is tied to the record's **source identity** and never reassigned; suffixes are
   never derived from collection or issue order.
5. A lookup by the bare base ID of a group with more than one member returns AMBIGUOUS for review —
   it never picks one. Exact suffixed IDs, and the source identity, resolve directly.

The suffix uses the single existing suffix slot of the canonical ID, so the general pattern is
unchanged. IDs that already use that slot (memo file suffix ``-2``, note revision ``-R1``) cannot
take a collision suffix and are refused for human review.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import tempfile
from collections.abc import Iterable
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from app.identifiers.canonical import InvalidCanonicalIdError, parse_canonical_id


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SuffixKind(StrEnum):
    NONE = "none"  # the unsuffixed ID (first record of a group)
    SECTION = "section"  # official section code printed on the order
    REGISTRY = "registry"  # persistent -Cnn from the collision registry


class Evidence(_Frozen):
    """Where the section code was read (same shape as ADR-0007 date evidence)."""

    method: str  # e.g. "heading_ocr", "native_text", "manual"
    page: int | None = Field(default=None, ge=1)
    text: str = ""


class Assignment(_Frozen):
    source_key: str  # stable source identity, e.g. "goir:gid=184522" or "sha256:<hex>"
    canonical_id: str
    base_id: str
    suffix: str | None
    suffix_kind: SuffixKind
    section_code: str | None  # normalised, as printed on the order (kept even when unused)
    evidence: Evidence | None
    assigned_at: dt.datetime


class LookupStatus(StrEnum):
    FOUND = "found"
    AMBIGUOUS = "ambiguous"  # bare base ID of a multi-record group → human review
    NOT_FOUND = "not_found"


class LookupResult(_Frozen):
    status: LookupStatus
    canonical_id: str | None = None
    candidates: tuple[str, ...] = ()


class CollisionError(Exception):
    """The record cannot be given a safe ID automatically; send it to review."""


_RESERVED = re.compile(r"^(?:C\d{2,}|D\d{8}|R\d+|\d+)$")


def normalise_section_code(label: str | None) -> str | None:
    """Printed section label → suffix: ``HR.III`` / ``(HR-III)`` / ``H.R. III`` → ``HRIII``.

    Returns None when the label is missing or cannot serve as a reliable code (too short/long,
    no letters, or the shape of a registry/date/revision/number suffix).
    """
    if not label:
        return None
    code = re.sub(r"[^A-Z0-9]", "", label.upper())
    if not (2 <= len(code) <= 12) or not code[0].isalpha() or _RESERVED.match(code):
        return None
    return code


class CollisionRegistry:
    """Persistent registry. With `path`, every change is written atomically to a JSON file
    (works today without GCP; a Cloud SQL table can take over with the same behaviour)."""

    FORMAT_VERSION = 1

    def __init__(self, path: Path | None = None, *, clock: dt.datetime | None = None) -> None:
        self._path = path
        self._clock = clock
        self._by_source: dict[str, Assignment] = {}
        self._by_id: dict[str, Assignment] = {}
        self._groups: dict[str, list[str]] = {}  # base_id → canonical IDs, assignment order
        self._counters: dict[str, int] = {}  # base_id → last registry number used
        if path is not None and path.exists():
            self._load(path)

    # ---- persistence ----------------------------------------------------------------------

    def _load(self, path: Path) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format_version") != self.FORMAT_VERSION:
            raise CollisionError("unsupported registry format")
        for raw in data["assignments"]:
            self._index(Assignment.model_validate(raw))
        self._counters = {k: int(v) for k, v in data["counters"].items()}
        for base, ids in self._groups.items():
            used = [
                int(sfx[1:])
                for i in ids
                if self._by_id[i].suffix_kind is SuffixKind.REGISTRY
                and (sfx := self._by_id[i].suffix)
            ]
            if used and self._counters.get(base, 0) < max(used):
                raise CollisionError(f"registry counter behind assignments for {base}")

    def _save(self) -> None:
        if self._path is None:
            return
        data = {
            "format_version": self.FORMAT_VERSION,
            "assignments": [
                a.model_dump(mode="json")
                for base in sorted(self._groups)
                for a in (self._by_id[i] for i in self._groups[base])
            ],
            "counters": dict(sorted(self._counters.items())),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".collisions-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=1)
                fh.write("\n")
            os.replace(tmp, self._path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _index(self, a: Assignment) -> None:
        if a.source_key in self._by_source:
            raise CollisionError(f"duplicate source identity {a.source_key}")
        if a.canonical_id in self._by_id:
            raise CollisionError(f"duplicate canonical ID {a.canonical_id}")
        self._by_source[a.source_key] = a
        self._by_id[a.canonical_id] = a
        self._groups.setdefault(a.base_id, []).append(a.canonical_id)

    # ---- assignment -----------------------------------------------------------------------

    def assign(
        self,
        base_id: str,
        source_key: str,
        *,
        section_label: str | None = None,
        evidence: Evidence | None = None,
    ) -> Assignment:
        """Give `source_key` its canonical ID under `base_id`. Idempotent per source identity."""
        if not source_key.strip():
            raise CollisionError("source identity is required")
        if existing := self._by_source.get(source_key):
            if existing.base_id != base_id:
                raise CollisionError(
                    f"{source_key} already holds {existing.canonical_id}; base ID changed to "
                    f"{base_id} — review (never reassigned automatically)"
                )
            return existing
        try:
            base = parse_canonical_id(base_id)
        except InvalidCanonicalIdError as exc:
            raise CollisionError(f"invalid base ID {base_id!r}") from exc
        if base.clause or base.document_id != base_id:
            raise CollisionError("base ID must be a document-level ID")
        section_code = normalise_section_code(section_label)
        members = [self._by_id[i] for i in self._groups.get(base_id, [])]

        if not members:
            suffix, kind = None, SuffixKind.NONE
        else:
            if base.suffix:
                raise CollisionError(
                    f"{base_id} already uses the suffix slot ({base.suffix}); review"
                )
            taken_codes = {m.section_code for m in members if m.section_code}
            taken_suffixes = {m.suffix for m in members if m.suffix}
            if (
                section_code
                and section_code not in taken_codes
                and section_code not in taken_suffixes
            ):
                suffix, kind = section_code, SuffixKind.SECTION
            else:
                n = self._counters.get(base_id, 0) + 1
                self._counters[base_id] = n
                suffix, kind = f"C{n:02d}", SuffixKind.REGISTRY

        canonical = base.model_copy(update={"suffix": suffix}).render() if suffix else base_id
        assignment = Assignment(
            source_key=source_key,
            canonical_id=canonical,
            base_id=base_id,
            suffix=suffix,
            suffix_kind=kind,
            section_code=section_code,
            evidence=evidence,
            assigned_at=self._clock or dt.datetime.now(dt.UTC),
        )
        self._index(assignment)
        self._save()
        return assignment

    # ---- lookup ---------------------------------------------------------------------------

    def lookup(self, canonical_id: str) -> LookupResult:
        group = self._groups.get(canonical_id, [])
        if len(group) > 1:  # bare base ID of a real collision: never pick one
            return LookupResult(status=LookupStatus.AMBIGUOUS, candidates=tuple(group))
        if canonical_id in self._by_id:
            return LookupResult(status=LookupStatus.FOUND, canonical_id=canonical_id)
        return LookupResult(status=LookupStatus.NOT_FOUND)

    def by_source(self, source_key: str) -> Assignment | None:
        return self._by_source.get(source_key)

    def group(self, base_id: str) -> tuple[Assignment, ...]:
        return tuple(self._by_id[i] for i in self._groups.get(base_id, []))

    def assignments(self) -> Iterable[Assignment]:
        return tuple(self._by_id.values())
