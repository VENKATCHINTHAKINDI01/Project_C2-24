"""Canonical identifiers: parse, validate and format (plan §4.4, ADR-0007).

Format: ``AP-<DEPT>-<TYPE>-[<FILECODE>-]<NUMBER>-<YEAR>[-<SUFFIX>][-D<yyyymmdd>][#<clause>]``

- ``AP-FIN01-GOMS-88-2022``                              G.O.(Ms)
- ``AP-FIN01-MEMO-FIN01HRPLG0TRF-3-2025-2``              memo with e-File code and file suffix
- ``AP-FIN01-CIRMEMO-FIN01COOROMISC-93-2023-D20240305``  memo + issue-date tag (ADR-0007)
- ``AP-USD01-NOTE-USD0131-4-2025-R1``                    note revision
- ``AP-GAZ-GAZETTE-EI-137-2024``                         gazette (part in the file-code slot)
- ``AP-FIN01-GOMS-88-2022#para-2.v``                     clause-level ID
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

_ID_RE = re.compile(
    r"^AP-(?P<dept>[A-Z]{2,6}\d{2}|GAZ)"
    r"-(?P<type>[A-Z]+)"
    r"(?:-(?P<filecode>[A-Z][A-Z0-9]*))?"
    r"-(?P<number>[1-9]\d*)"
    r"-(?P<year>(?:19|20)\d{2})"
    r"(?:-(?P<suffix>(?!D\d{8}\b)[A-Z0-9]+))?"
    r"(?:-D(?P<date>\d{8}))?"
    r"(?:#(?P<clause>[a-z]+-[A-Za-z0-9.]+))?$"
)

DOC_TYPES = frozenset(
    {
        "GOMS",
        "GORT",
        "GOP",
        "SO",
        "MEMO",
        "CIRMEMO",
        "RC",
        "OO",
        "OM",
        "NOTIFICATION",
        "RULES",
        "ACT",
        "GAZETTE",
        "NOTE",
        "RPT",
        "ANX",
        "FILE",
    }
)


class InvalidCanonicalIdError(ValueError):
    """The string is not a well-formed canonical ID. Never 'repair' it by guessing."""


class CanonicalId(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    department: str
    doc_type: str
    file_code: str | None = None
    number: int
    year: int
    suffix: str | None = None
    date_tag: str | None = None  # yyyymmdd
    clause: str | None = None

    def __str__(self) -> str:
        return self.render()

    def render(self, *, with_clause: bool = True) -> str:
        parts = ["AP", self.department, self.doc_type]
        if self.file_code:
            parts.append(self.file_code)
        parts += [str(self.number), str(self.year)]
        if self.suffix:
            parts.append(self.suffix)
        if self.date_tag:
            parts.append("D" + self.date_tag)
        text = "-".join(parts)
        return f"{text}#{self.clause}" if (with_clause and self.clause) else text

    @property
    def document_id(self) -> str:
        """The document-level ID (clause dropped)."""
        return self.render(with_clause=False)

    @property
    def base_id(self) -> str:
        """Document ID without the ADR-0007 date tag; used as a fallback lookup key."""
        return self.model_copy(update={"date_tag": None, "clause": None}).render()


def parse_canonical_id(text: str) -> CanonicalId:
    """Strictly parse a canonical ID (plan §4.4). Raises InvalidCanonicalIdError."""
    m = _ID_RE.match(text.strip())
    if not m:
        raise InvalidCanonicalIdError(text)
    if m["type"] not in DOC_TYPES:
        raise InvalidCanonicalIdError(f"unknown document type in {text!r}")
    if m["dept"] == "GAZ" and m["type"] != "GAZETTE":
        raise InvalidCanonicalIdError(f"GAZ is only valid for gazettes: {text!r}")
    return CanonicalId(
        department=m["dept"],
        doc_type=m["type"],
        file_code=m["filecode"],
        number=int(m["number"]),
        year=int(m["year"]),
        suffix=m["suffix"],
        date_tag=m["date"],
        clause=m["clause"],
    )


def is_canonical_id(text: str) -> bool:
    try:
        parse_canonical_id(text)
    except InvalidCanonicalIdError:
        return False
    return True


def clause_id(document_id: str, paragraph: str) -> str:
    """Clause-level ID: ``AP-…-2022`` + ``2(v)`` → ``AP-…-2022#para-2.v`` (plan §4.4)."""
    doc = parse_canonical_id(document_id)
    if doc.clause:
        raise InvalidCanonicalIdError("already a clause ID")
    norm = re.sub(r"[()\s]+", ".", paragraph.strip()).strip(".")
    norm = re.sub(r"\.+", ".", norm)
    if not norm or not re.fullmatch(r"[A-Za-z0-9.]+", norm):
        raise InvalidCanonicalIdError(f"bad paragraph label {paragraph!r}")
    return f"{doc.document_id}#para-{norm}"


def lookup_keys(text: str) -> tuple[str, ...]:
    """IDs to try for an L0 lookup: exact, then without the ADR-0007 date tag (older records)."""
    cid = parse_canonical_id(text)
    exact = cid.document_id
    return (exact,) if cid.base_id == exact else (exact, cid.base_id)


_EFILE = re.compile(r"^(?P<dept>[A-Z]{2,6}\d{2})-(?P<head>[A-Z0-9]+)/(?P<num>\d+)/(?P<year>\d{4})-")
EFILE_TYPES = frozenset({"NOTE", "RPT", "ANX", "FILE"})  # FILE: the e-File's own record


def efile_document_id(file_no: str, doc_type: str) -> str:
    """ID for a document that lives in an e-File and has no printed number of its own
    (noting, report, annexure): ``USD01-12/31/2022-ESTT.I`` + NOTE →
    ``AP-USD01-NOTE-USD0112-31-2022``.
    A second document of the same type in the same file is a collision (ADR-0007 registry)."""
    if doc_type not in EFILE_TYPES:
        raise InvalidCanonicalIdError(f"not an e-File document type: {doc_type}")
    m = _EFILE.match(file_no.strip())
    if not m:
        raise InvalidCanonicalIdError(f"not an e-File number: {file_no!r}")
    cid = CanonicalId(
        department=m["dept"],
        doc_type=doc_type,
        file_code=f"{m['dept']}{m['head']}",
        number=int(m["num"]),
        year=int(m["year"]),
    )
    return cid.render()
