"""Document-type classification, metadata and relationship extraction from text (plan §4.3, §4.4).

Deterministic rules that follow the printed layout of AP Government documents (the same layout the
data-collection tools parse on real orders): department heading → own reference line → ABSTRACT /
Sub: → "Read the following:" list → ORDER paragraphs ("in supersession of … reference 1st read
above"). e-Office notes: "File No. … (Computer No. …)" and "Note # n".

Nothing is guessed: an own reference that does not resolve leaves `canonical_id=None` with a review
reason; a relation is EXPLICIT only when the text states it ("in supersession of", "amendment",
"clarification"), otherwise it is a plain REFERENCES/CITES edge. Uncertain items go to review.
"""

from __future__ import annotations

import datetime as dt
import re
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.identifiers.canonical import parse_canonical_id
from app.identifiers.resolver import (
    DepartmentTable,
    Unresolved,
    normalise_telugu_markers,
    resolve_reference,
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class DocType(StrEnum):
    GOVERNMENT_ORDER = "Government Order"
    AMENDMENT = "Amendment"
    CIRCULAR = "Circular"
    MEMO = "Memo"
    CLARIFICATION = "Clarification"
    STANDING_ORDER = "Standing Order"
    NOTING = "Noting"
    NOTING_DRAFT = "Noting (draft proposal)"
    REPORT = "Report"
    ANNEXURE = "Annexure"
    UNKNOWN = "Unknown"


INSTRUMENT_FOR_TYPE = {  # canonical-ID type → instrument code in data/ontology/hierarchy.yaml
    "GOMS": "GO_MS",
    "GORT": "GO_RT",
    "GOP": "GO_MS",
    "SO": "STANDING_ORDER",
    "CIRMEMO": "CIRCULAR_MEMO",
    "MEMO": "CIRCULAR_MEMO",
    "RC": "CIRCULAR_MEMO",
    "NOTE": "DECISION_NOTING",
    "RPT": "DECISION_NOTING",
    "ANX": "DECISION_NOTING",
}


class RelKind(StrEnum):
    SUPERSEDES = "SUPERSEDES"
    AMENDS = "AMENDS"
    CLARIFIES = "CLARIFIES"
    REFERENCES = "REFERENCES"  # orders citing orders
    CITES = "CITES"  # notes citing orders


class Reference(_Frozen):
    position: int | None  # place in the "Read the following" list; None for in-text citations
    raw: str
    canonical_id: str | None


class RelationCandidate(_Frozen):
    kind: RelKind
    target: str  # canonical ID, or raw text when unresolved
    resolved: bool
    explicit: bool  # the text itself states the relation
    evidence: str  # the sentence it came from (short)


class DocumentMetadata(_Frozen):
    doc_type: DocType
    canonical_id: str | None
    raw_reference: str | None
    instrument: str | None
    issue_date: dt.date | None
    department: str | None
    subject: str | None
    department_source: str | None = None  # "text" | "source_system" (ADR-0011)
    valid_until: dt.date | None = None  # the order's OWN end date, read from its subject
    file_no: str | None = None
    computer_no: str | None = None
    references: tuple[Reference, ...] = ()
    relations: tuple[RelationCandidate, ...] = ()
    review_reasons: tuple[str, ...] = ()


_OWN_GO = re.compile(
    r"^\s*(G\.?\s*O\.?\s*\(?\s*(?:Ms|Rt|P)\s*\)?\.?\s*No\.?\s*\d+.*?Dated\s*:?\s*\d{1,2}[-./]\d{1,2}[-./]\d{2,4})",
    re.I | re.M,
)
_OWN_MEMO = re.compile(
    r"^\s*((?:Circular\s+Memo|Memo|Rc)\.?\s*No\.?\s*\S+?/\d+/\d{4}(?:-\d+)?,?\s+Dated\s*:?\s*\d{1,2}[-./]\d{1,2}[-./]\d{2,4})",
    re.I | re.M,
)
_OWN_SO = re.compile(
    r"^\s*(Standing\s+Order\s+No\.?\s*\d+\s*/\s*\d{4}(?:.*?Dated\s*:?\s*\d{1,2}[-./]\d{1,2}[-./]\d{2,4})?)",
    re.I | re.M,
)
_FILE = re.compile(
    r"File\s+No\.?\s*(?P<file>[A-Z]{2,6}\d{2}-[A-Z0-9]+/\d+/\d{4}-[A-Z][A-Z0-9.]*[A-Z0-9])(?:\s*\(Computer\s+No\.?\s*(?P<cno>\d+)\))?",
    re.I,
)
_FILE_CITE = re.compile(
    r"\bfile\s+No\.?\s*(?P<file>[A-Z]{2,6}\d{2}-[A-Z0-9]+/\d+/\d{4}-[A-Z][A-Z0-9.]*[A-Z0-9])", re.I
)
_SIGN_DATE = re.compile(r"(?:^|/)\s*(\d{2}/\d{2}/\d{4})\s+\d{1,2}:\d{2}\s*[AP]M", re.I | re.M)
_AS_ON = re.compile(r"\bAs\s+on\s+(\d{1,2}[-./]\d{1,2}[-./]\d{4})", re.I)
_HEADING = re.compile(r"^[^a-z\n]*\bDEPARTMENT\b[^a-z\n]*$", re.M)
_DATE = re.compile(r"(?:Dated|Dt)\s*[.:]?\s*(\d{1,2}[-./]\d{1,2}[-./]\d{2,4})", re.I)
_ORD = re.compile(r"(\d{1,2})(?:st|nd|rd|th)", re.I)
_REF_LINE = re.compile(r"^\s*(\d{1,2})\s*[.)]\s+(.+)$")
_ORDER_CITE = re.compile(
    r"G\.?\s*O\.?\s*\(?\s*(?:Ms|Rt)\s*\)?\.?\s*No\.?\s*\d+(?:(?!G\.?\s*O\.|Memo|Rc\.|Standing|File)[^\n]){0,120}?(?:Dt|Dated)[.:\s]*\d{1,2}[-./]\d{1,2}[-./]\d{2,4}"
    r"|(?:Circular\s+Memo|Memo|Rc)\.?\s*No\.?\s*[A-Z0-9()\-.]+/\d+/\d{4}(?:-\d+)?(?:(?!G\.?\s*O\.|Memo|Rc\.|Standing|File)[^\n]){0,120}?(?:Dt|Dated)[.:\s]*\d{1,2}[-./]\d{1,2}[-./]\d{2,4}"
    r"|Standing\s+Order\s+No\.?\s*\d+\s*/\s*\d{4}",
    re.I,
)


_SUPERSESSION = re.compile(
    r"in supersession of (?:all )?(?:the )?(?:orders?|instructions?) issued in (?:the )?"
    r"(?:G\.?\s*O\.?s?|Government Orders?|references?|Memo|Circular(?: Memo)?)\s+"
    r"(?P<ords>\d{1,2}(?:st|nd|rd|th)(?:\s*(?:,|and|&)\s*\d{1,2}(?:st|nd|rd|th))*)\s+read above",
    re.I,
)


def _date(raw: str) -> dt.date | None:
    for fmt in ("%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%y"):
        try:
            return dt.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _subject(text: str) -> str | None:
    m = re.search(r"ABSTRACT\s*\n(?P<s>.+?)\n\s*-{5,}", text, re.S)
    if not m:  # no rule line: the abstract ends at the department heading
        m = re.search(
            r"ABSTRACT\s*\n(?P<s>.+?)\n(?=[^a-z\n]*\bDEPARTMENT\b[^a-z\n]*\n)", text, re.S
        )
    if not m:
        m = re.search(
            r"^\s*Sub(?:ject)?\s*:\s*(?P<s>.+?)(?=\n\s*(?:Ref\s*:|\*|\[|NOTE\b|Note\s*#|1\.)|\Z)",
            text,
            re.S | re.M,
        )
    if not m:
        return None
    return re.sub(r"\s+", " ", m.group("s")).strip() or None


_DATED_TYPES = frozenset(
    {
        DocType.GOVERNMENT_ORDER,
        DocType.AMENDMENT,
        DocType.CIRCULAR,
        DocType.MEMO,
        DocType.CLARIFICATION,
    }
)
_TITLE = re.compile(
    r"^\s*(?P<s>(?:Report|Statement|Annexure)\s+of\b.+?)(?=\n\s*(?:\d+\s*[.)\t]|File\s+No|Sl\.)|\Z)",
    re.S | re.M | re.I,
)
_PERIOD_END = re.compile(
    r"(?:for\s+the\s+period\s+from\s+\d{1,2}[-./]\d{1,2}[-./]\d{4}\s+to"
    r"|(?:valid\s+)?up\s*to|valid\s+till)\s+(?P<d>\d{1,2}[-./]\d{1,2}[-./]\d{4})",
    re.I,
)


def _title(text: str) -> str | None:
    """Reports and statements carry no "Sub:" line; their title is the subject."""
    m = _TITLE.search(text)
    return re.sub(r"\s+", " ", m.group("s")).strip() if m else None


def _valid_until(subject: str | None, doc_type: DocType) -> dt.date | None:
    """An order's own end date, only when its subject states the period it covers ("… for the
    period from 01-04-2025 to 31-03-2026", "… up to 31-03-2025"). Body text is not used: it
    quotes other orders' periods. Several dates or none → None (never guessed)."""
    if not subject or doc_type not in _DATED_TYPES:
        return None
    ends = {d for m in _PERIOD_END.finditer(subject) if (d := _date(m.group("d")))}
    return ends.pop() if len(ends) == 1 else None


def _read_list(text: str) -> list[tuple[int, str]]:
    m = re.search(
        r"Read the following\s*:?\s*\n(?P<b>.+?)\n\s*(?:\*\s*\*|ORDER\s*:)", text, re.S | re.I
    )
    if m:
        items: list[tuple[int, str]] = []
        for line in m.group("b").splitlines():
            if lm := _REF_LINE.match(line):
                items.append((int(lm.group(1)), lm.group(2).strip()))
            elif items and line.strip():
                n, prev = items[-1]
                items[-1] = (n, f"{prev} {line.strip()}")
        return items
    ref = re.search(r"^\s*Ref\s*:\s*(?P<r>.+?)(?=\n\s*(?:\*|1\.)|\n\n)", text, re.S | re.M)
    return [(1, re.sub(r"\s+", " ", ref.group("r")).strip())] if ref else []


def _sentences_with(body: str, pattern: str) -> list[str]:
    flat = re.sub(r"\s+", " ", body)
    return [
        s.strip()
        for s in re.split(r"(?<=[.;:])\s+(?=\(?[A-Z0-9])", flat)
        if re.search(pattern, s, re.I)
    ]


def extract_metadata(
    text: str, departments: DepartmentTable, *, source_department: str | None = None
) -> DocumentMetadata:
    """Plan §4.3 for one native document. Never raises on odd text: unknowns go to review.

    `source_department` (ADR-0011): the department the source system recorded. Used ONLY when the
    text names none; `department_source` then says "source_system". The caller holds a document
    whose text names a different department for review.

    Telugu reference markers (ఆర్.సి.నెం., తేది, విషయం, సూచిక, జి.ఓ.ఎం.ఎస్.నెం.) are read through
    a fixed table; parsed fields show them in English form, the stored source text is unchanged."""
    text = normalise_telugu_markers(text)
    reasons: list[str] = []
    headings = [h.group(0) for h in _HEADING.finditer(text)]
    dept = departments.code_in(headings[0]) if headings else None
    dept_from_source = False
    file_m = _FILE.search(text)
    own_raw: str | None = None
    for rx in (_OWN_GO, _OWN_MEMO, _OWN_SO):
        if m := rx.search(text):
            own_raw = re.sub(r"\s+", " ", m.group(1)).strip()
            break

    canonical: str | None = None
    issue: dt.date | None = None
    typ: str | None = None
    if own_raw:
        r = resolve_reference(own_raw, departments, dept)
        if r.unresolved is Unresolved.NO_DEPARTMENT and dept is None and source_department:
            r = resolve_reference(own_raw, departments, source_department)
            dept_from_source = r.canonical_id is not None
        canonical, issue, typ = r.canonical_id, r.issue_date, r.doc_type
        if canonical is None:
            reasons.append(f"own reference not resolvable ({r.unresolved})")
        else:
            dept = dept or parse_canonical_id(canonical).department
    subject = _subject(text)

    is_note = bool(re.search(r"^\s*Note\s*#\s*\d+", text, re.M))
    file_dept = file_m.group("file").split("-")[0] if file_m else None
    if is_note and own_raw is None:
        draft = re.search(r"\[\s*Draft note\b", text, re.I)
        doc_type = DocType.NOTING_DRAFT if draft else DocType.NOTING
        typ = "NOTE"
        dept = dept or file_dept
        signed = [_date(d.replace("/", "-")) for d in _SIGN_DATE.findall(text)]
        issue = max((d for d in signed if d), default=None)  # date of the latest note
    elif own_raw is None and re.search(r"^\s*Report\s+of\b", text, re.M | re.I):
        doc_type, typ, dept = DocType.REPORT, "RPT", dept or file_dept
        if dm := _DATE.search(text):
            issue = _date(dm.group(1))
    elif own_raw is None and re.search(r"^\s*(?:Statement|Annexure)\b", text, re.M | re.I):
        doc_type, typ, dept = DocType.ANNEXURE, "ANX", dept or file_dept
        if am := _AS_ON.search(text):
            issue = _date(am.group(1))
    elif typ in ("GOMS", "GORT", "GOP"):
        doc_type = (
            DocType.AMENDMENT
            if subject and re.search(r"\bAmendment\b", subject, re.I)
            else DocType.GOVERNMENT_ORDER
        )
    elif typ in ("CIRMEMO", "RC"):
        doc_type = DocType.CIRCULAR
    elif typ == "MEMO":
        doc_type = (
            DocType.CLARIFICATION
            if subject and re.search(r"Clarification", subject, re.I)
            else DocType.MEMO
        )
    elif typ == "SO":
        doc_type = DocType.STANDING_ORDER
    else:
        doc_type = DocType.UNKNOWN
        reasons.append("document type not recognised")
    if subject is None and doc_type in (DocType.REPORT, DocType.ANNEXURE):
        subject = _title(text)
    if issue is None and own_raw:
        if dm := _DATE.search(own_raw):
            issue = _date(dm.group(1))

    # references: "Read the following" list (orders) or in-text citations (notes)
    refs: list[Reference] = []
    if is_note:
        flat_text = re.sub(r"\s+", " ", text)  # citations wrap across lines in PDF layout
        for m in _ORDER_CITE.finditer(flat_text):
            r = resolve_reference(m.group(0), departments, dept)
            refs.append(
                Reference(
                    position=None, raw=re.sub(r"\s+", " ", m.group(0)), canonical_id=r.canonical_id
                )
            )
        own_file = file_m.group("file") if file_m else None
        for m in _FILE_CITE.finditer(flat_text):
            if m.group("file") != own_file:  # another e-file: resolved against the file index later
                refs.append(
                    Reference(position=None, raw=f"file:{m.group('file')}", canonical_id=None)
                )
    else:
        for pos, raw in _read_list(text):
            r = resolve_reference(raw, departments, dept)
            refs.append(Reference(position=pos, raw=raw, canonical_id=r.canonical_id))

    relations = _relations(text, refs, doc_type, subject, is_note)
    seen: set[str] = set()
    unique: list[RelationCandidate] = []
    for rel in relations:
        key = f"{rel.kind}|{rel.target}"
        if key not in seen:
            seen.add(key)
            unique.append(rel)
    if canonical is None and typ not in ("NOTE", "RPT", "ANX"):
        reasons.append("no own reference found")

    return DocumentMetadata(
        doc_type=doc_type,
        canonical_id=canonical,
        raw_reference=own_raw or (f"File No.{file_m.group('file')}" if file_m else None),
        instrument=INSTRUMENT_FOR_TYPE.get(typ or ""),
        issue_date=issue,
        department=dept,
        subject=subject,
        department_source=None if dept is None else "source_system" if dept_from_source else "text",
        valid_until=_valid_until(subject, doc_type),
        file_no=file_m.group("file") if file_m else None,
        computer_no=file_m.group("cno") if file_m else None,
        references=tuple(refs),
        relations=tuple(unique),
        review_reasons=tuple(reasons),
    )


def _relations(
    text: str, refs: list[Reference], doc_type: DocType, subject: str | None, is_note: bool
) -> list[RelationCandidate]:
    by_pos = {r.position: r for r in refs if r.position is not None}
    out: list[RelationCandidate] = []
    explicit_targets: set[int] = set()
    body = text.split("ORDER", 1)[1] if "ORDER" in text else text

    def add(kind: RelKind, ref: Reference, explicit: bool, evidence: str) -> None:
        out.append(
            RelationCandidate(
                kind=kind,
                target=ref.canonical_id or ref.raw,
                resolved=ref.canonical_id is not None,
                explicit=explicit,
                evidence=evidence[:200],
            )
        )

    flat = re.sub(r"\s+", " ", body)
    for m in _SUPERSESSION.finditer(flat):
        for n in (int(x) for x in _ORD.findall(m.group("ords"))):
            if n in by_pos:
                add(RelKind.SUPERSEDES, by_pos[n], True, m.group(0))
                explicit_targets.add(n)
    if doc_type is DocType.AMENDMENT:
        for sentence in _sentences_with(body, r"amendment"):
            for n in (int(x) for x in _ORD.findall(sentence)):
                if n in by_pos and n not in explicit_targets:
                    add(RelKind.AMENDS, by_pos[n], True, sentence)
                    explicit_targets.add(n)
    if doc_type is DocType.CLARIFICATION and 1 in by_pos and len(by_pos) == 1:
        add(RelKind.CLARIFIES, by_pos[1], True, subject or "clarification")
        explicit_targets.add(1)
    for ref in refs:
        if ref.position is not None and ref.position in explicit_targets:
            continue
        if ref.canonical_id is None:
            if is_note and ref.raw.startswith("file:"):
                add(
                    RelKind.CITES, ref, True, ref.raw
                )  # unresolved: matched to the file index later
            continue  # letters / unresolvable mentions: kept in `references`, not as edges
        add(RelKind.CITES if is_note else RelKind.REFERENCES, ref, True, ref.raw)
    return out
