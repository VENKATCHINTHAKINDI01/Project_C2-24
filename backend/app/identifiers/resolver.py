"""Reference normaliser: free-text references → canonical IDs (plan §3.2 canonical query, §4.4).

Rules (CLAUDE.md §5.5-§5.6):
- the department comes from an explicit code (FIN01) or a department name inside the reference;
  the caller's `default_dept` is used only when the reference names no department at all;
- the year comes from the reference itself (its date or ``/2023``) — never from today;
- anything that cannot be resolved stays raw with ``canonical_id=None`` and a reason (type E input).
"""

from __future__ import annotations

import datetime as dt
import re
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from app.identifiers.canonical import CanonicalId


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Department(_Frozen):
    code: str
    name: str
    aliases: tuple[str, ...]
    synthetic: bool = False


class DepartmentTable(_Frozen):
    version: str
    status: str
    departments: tuple[Department, ...]

    def code_in(self, text: str) -> str | None:
        """Explicit code first, then a whole-word department name. None if absent or ambiguous."""
        codes: set[str] = {str(c).upper() for c in _DEPT_CODE_RE.findall(text)}
        known = {d.code for d in self.departments}
        explicit = codes & known
        if len(explicit) == 1:
            return explicit.pop()
        if explicit:
            return None
        hits = {
            d.code
            for d in self.departments
            for a in (d.name, *d.aliases)
            if re.search(r"(?<![A-Za-z])" + re.escape(a) + r"(?![A-Za-z])", text, re.I)
        }
        return hits.pop() if len(hits) == 1 else None


def load_departments(path: Path) -> DepartmentTable:
    with path.open(encoding="utf-8") as fh:
        return DepartmentTable.model_validate(yaml.safe_load(fh))


class Unresolved(StrEnum):
    NOT_A_REFERENCE = "not_a_reference"
    NO_DEPARTMENT = "no_department"
    NO_YEAR = "no_year"


class ResolvedReference(_Frozen):
    raw: str
    doc_type: str | None
    canonical_id: str | None
    issue_date: dt.date | None = None
    file_no: str | None = None
    unresolved: Unresolved | None = None


_DEPT_CODE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{2,6}\d{2})(?![0-9])")
_MID = r"(?P<mid>(?:(?!\b(?:Dt|Dated|date)\b|G\.?\s*O\.|Memo\b|Rc\.)[^\n]){0,120})"
_DATE = r"(?P<date>\d{1,2}[-./]\d{1,2}[-./](?:\d{4}|\d{2}))"
_DATED = r"(?:,?\s*(?:Dt|Dated|dt|dated|date)[\s.:;,]*" + _DATE + r")?"

_GO_RE = re.compile(
    r"G\.?\s*O\.?\s*\(?\s*(?P<kind>Ms|Rt|P)\s*\)?\.?\s*(?:No\.?)?\s*(?P<num>\d+)"
    r"(?:\s*/\s*(?P<slashyear>(?:19|20)\d{2})|\s+of\s+(?P<ofyear>(?:19|20)\d{2})\b)?"
    + _MID
    + _DATED,
    re.I,
)
_MEMO_RE = re.compile(
    r"(?P<kind>Circular\s+Memo|Cir\.?\s*Memo|Memo|Rc)\.?\s*No\.?\s*"
    r"(?P<code>[A-Za-z0-9()\-.]+?)/(?P<num>\d+)/(?P<year>(?:19|20)\d{2})(?:-(?P<suffix>\d+))?"
    + _MID
    + _DATED,
    re.I,
)
_SO_RE = re.compile(
    r"Standing\s+Order\s+No\.?\s*(?P<num>\d+)\s*/\s*(?P<year>(?:19|20)\d{2})" + _DATED, re.I
)
_FILE_RE = re.compile(
    r"File\s+No\.?\s*(?P<file>[A-Z]{2,6}\d{2}-[A-Z0-9]+/\d+/(?:19|20)\d{2}-[A-Z][A-Z0-9.]*[A-Z0-9])",
    re.I,
)


def _dept_from_mid(mid: str, departments: DepartmentTable, default_dept: str | None) -> str | None:
    """A department named in the reference wins; a named but unknown/ambiguous one → None.

    `default_dept` applies only when the reference names no department at all.
    """
    if code := departments.code_in(mid):
        return code
    names_a_department = re.search(r"\bDep(?:artmen)?t\b|శాఖ", mid, re.I) or _DEPT_CODE_RE.search(
        mid
    )
    return None if names_a_department else default_dept


# Telugu reference markers → the English forms the patterns read (plan §4.1 Telugu/English).
# Fixed, reviewed table — longest first; nothing outside it is translated. [To confirm against
# real Telugu orders when they arrive.]
TELUGU_MARKERS: tuple[tuple[str, str], ...] = (
    ("జి.ఓ.ఎం.ఎస్.నెం.", "G.O.Ms.No."),
    ("జి.ఓ.ఆర్.టి.నెం.", "G.O.Rt.No."),
    ("ఆర్.సి.నెం.", "Rc.No."),
    ("మెమో నెం.", "Memo No."),
    ("తేదీ", "Dated"),
    ("తేది", "Dated"),
    ("విషయం", "Sub"),
    ("సూచిక", "Ref"),
)


def normalise_telugu_markers(text: str) -> str:
    """Rewrite only the fixed Telugu reference markers; every other word is left as written."""
    for te, en in TELUGU_MARKERS:
        text = text.replace(te, en)
    return text


def _ocr_fix(text: str) -> str:
    t = normalise_telugu_markers(text).replace("–", "-").replace("—", "-")
    t = re.sub(r"\b([A-Z]{2,5})O(\d)(?=\b|-|/)", r"\g<1>0\2", t)  # FINO1 → FIN01
    return re.sub(r"\b[G6]\s*\.\s*[0O]\s*\.?\s*(?=(?:Ms|MS|Rt|RT|P\b|No|\())", "G.O.", t)


def _date(raw: str | None) -> dt.date | None:
    if not raw:
        return None
    for fmt in ("%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%y", "%d.%m.%y", "%d/%m/%y"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _clean_code(code: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", code.upper())


def resolve_reference(
    text: str,
    departments: DepartmentTable,
    default_dept: str | None = None,
    *,
    memo_date_tag: bool = True,
) -> ResolvedReference:
    """Resolve the first reference in `text` (plan §4.4). Never guesses a department or year.

    `memo_date_tag` adds ADR-0007's ``-D<yyyymmdd>`` tag to memo/Rc IDs (accepted 2026-11-03).
    """
    t = _ocr_fix(text).strip()

    if m := _GO_RE.search(t):
        kind = m["kind"].lower()
        typ = {"ms": "GOMS", "rt": "GORT"}.get(kind, "GOP")
        issued = _date(m["date"])
        printed = m["slashyear"] or m["ofyear"]  # "88/2022" or "No.31 of 2025"
        year = int(printed) if printed else (issued.year if issued else None)
        dept = _dept_from_mid(m["mid"], departments, default_dept)
        return _result(t, typ, dept, None, int(m["num"]), year, None, issued, False)

    if m := _MEMO_RE.search(t):
        kind = m["kind"].lower()
        typ = "CIRMEMO" if kind.startswith("cir") else ("RC" if kind == "rc" else "MEMO")
        code = _clean_code(m["code"])
        lead = _DEPT_CODE_RE.match(code)
        dept = lead.group(1) if lead and departments.code_in(lead.group(1)) else None
        if dept is None:
            dept = _dept_from_mid(m["mid"], departments, default_dept)
        issued = _date(m["date"])
        return _result(
            t, typ, dept, code, int(m["num"]), int(m["year"]), m["suffix"], issued, memo_date_tag
        )

    if m := _SO_RE.search(t):
        return _result(
            t,
            "SO",
            default_dept,
            None,
            int(m["num"]),
            int(m["year"]),
            None,
            _date(m["date"]),
            False,
        )

    if m := _FILE_RE.search(t):
        # A file reference names an e-File, not one document; the caller picks the note/report.
        return ResolvedReference(raw=t, doc_type="FILE", canonical_id=None, file_no=m["file"])

    return ResolvedReference(
        raw=t, doc_type=None, canonical_id=None, unresolved=Unresolved.NOT_A_REFERENCE
    )


def _result(
    raw: str,
    typ: str,
    dept: str | None,
    file_code: str | None,
    number: int,
    year: int | None,
    suffix: str | None,
    issued: dt.date | None,
    date_tag: bool,
) -> ResolvedReference:
    if dept is None:
        return ResolvedReference(
            raw=raw, doc_type=typ, canonical_id=None, issue_date=issued,
            unresolved=Unresolved.NO_DEPARTMENT,
        )  # fmt: skip
    if year is None:
        return ResolvedReference(
            raw=raw, doc_type=typ, canonical_id=None, issue_date=issued,
            unresolved=Unresolved.NO_YEAR,
        )  # fmt: skip
    cid = CanonicalId(
        department=dept,
        doc_type=typ,
        file_code=file_code,
        number=number,
        year=year,
        suffix=suffix,
        date_tag=issued.strftime("%Y%m%d") if (date_tag and issued) else None,
    )
    return ResolvedReference(raw=raw, doc_type=typ, canonical_id=cid.render(), issue_date=issued)


def reference_candidates(
    text: str, departments: DepartmentTable, *, memo_date_tag: bool = True
) -> tuple[str, ...]:
    """Every canonical ID `text` could mean (plan §3.2 canonical query).

    A reference that names its department (or carries a code) has one candidate. One that names
    none ("GO Ms 88/2022") has one per known department — the caller looks them up within the
    officer's scope and asks the officer if more than one exists. Never picks one by guessing.
    """
    ids = {
        r.canonical_id
        for d in departments.departments
        if (
            r := resolve_reference(text, departments, d.code, memo_date_tag=memo_date_tag)
        ).canonical_id
    }
    return tuple(sorted(ids))
