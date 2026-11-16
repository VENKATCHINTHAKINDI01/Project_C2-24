"""Touchpoint 1 — "Diarising a receipt": read the letter on the receipt and pre-fill the diary
fields for the clerk to verify (plan §11.5, §4.1–4.3).

The fields come from the letter's own text — the native text layer, or the OCR draft of a scan —
through the same metadata reader ingestion uses (`extract_metadata`): the letter's reference and
date, the subject, the category (document type) and the sender (the signing post and the issuing
department). Each field says where it was read from; a field the text does not give is left
empty, never guessed. The clerk confirms or corrects every field; nothing is saved by the
assistant. An OCR read is marked as such (it has not passed review yet).
"""

from __future__ import annotations

import datetime as dt
import re

from pydantic import BaseModel, ConfigDict

from app.identifiers.resolver import DepartmentTable
from app.ingestion.metadata import DocType, extract_metadata

# e-Office "Main Category" for each document type the reader returns (sandbox categories)
CATEGORY = {
    DocType.GOVERNMENT_ORDER: "Government Order",
    DocType.AMENDMENT: "Amendment",
    DocType.CIRCULAR: "Circular",
    DocType.MEMO: "Memo",
    DocType.CLARIFICATION: "Clarification",
    DocType.STANDING_ORDER: "Standing Order",
    DocType.GAZETTE: "Gazette Notification",
    DocType.REPORT: "Report",
}

# the signature block: the line after "(BY ORDER ... GOVERNOR ...)" is the name, the next the post;
# a memo signs without that line, so the last "...TO GOVERNMENT" post before "To" also counts
_GOVERNOR = re.compile(r"BY ORDER AND IN THE NAME OF THE GOVERNOR", re.I)
_POST = re.compile(r"^[A-Z .()&,-]*(SECRETARY|COMMISSIONER|DIRECTOR|OFFICER)[A-Z .()&,-]*$")
_HEADING = re.compile(r"^\s*([A-Z][A-Z .&,()'-]+?)\s+DEPARTMENT\s*$", re.M)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Field(_Frozen):
    value: str | None
    read_from: str | None  # the line it was read from (short), for the clerk to check


class DiaryPrefill(_Frozen):
    letter_ref: Field
    letter_date: Field
    sender: Field
    main_category: Field
    subject: Field
    department: str | None  # department code, when the text names one
    from_ocr: bool  # read from an OCR draft that has not passed review
    ocr_confidence: float | None
    missing: tuple[str, ...]  # fields the text did not give: the clerk fills them


def _line_with(text: str, needle: str | None) -> str | None:
    if not needle:
        return None
    key = re.sub(r"\W+", "", needle.lower())[:24]
    for ln in text.splitlines():
        if key and key in re.sub(r"\W+", "", ln.lower()):
            return ln.strip()[:160]
    return None


def _department_name(text: str) -> tuple[str | None, str | None]:
    """'FINANCE (HR.I-PLG. & POLICY) DEPARTMENT' → 'Finance Department' (wing dropped)."""
    m = _HEADING.search(text)
    if not m:
        return None, None
    name = re.sub(r"\s*\([^)]*\)\s*", " ", m.group(1)).strip()
    return " ".join(w.capitalize() for w in name.split()) + " Department", m.group(0).strip()


def _signing_post(text: str) -> tuple[str | None, str | None]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for i, ln in enumerate(lines):
        if _GOVERNOR.search(ln) and i + 2 < len(lines) and _POST.match(lines[i + 2]):
            return lines[i + 2], lines[i + 2]
    end = next((i for i, ln in enumerate(lines) if ln in ("To", "To,")), len(lines))
    for ln in reversed(lines[:end]):
        if _POST.match(ln) and "TO GOVERNMENT" in ln.upper():
            return ln, ln
    return None, None


def _title(post: str) -> str:
    return " ".join(post.split()).title()  # "SECRETARY TO GOVERNMENT (SER.)" → e-Office style


def prefill(
    text: str,
    departments: DepartmentTable,
    *,
    from_ocr: bool = False,
    ocr_confidence: float | None = None,
) -> DiaryPrefill:
    """Plan §11.5 touchpoint 1."""
    meta = extract_metadata(text, departments)
    ref = meta.raw_reference
    if ref:  # the reference as diarised: number only, no "Dated ..." tail
        ref = re.split(r",?\s*(?:Dated|Dt\.?)\b", ref, maxsplit=1)[0].strip(" ,")
    date = meta.issue_date.isoformat() if isinstance(meta.issue_date, dt.date) else None
    dept_name, dept_line = _department_name(text)
    post, post_line = _signing_post(text)
    sender = f"{_title(post)}, {dept_name}" if post and dept_name else None
    category = CATEGORY.get(meta.doc_type)
    subject = " ".join(meta.subject.split()) if meta.subject else None
    fields = {
        "letter_ref": Field(value=ref, read_from=_line_with(text, ref)),
        "letter_date": Field(
            value=date,
            read_from=_line_with(text, f"{meta.issue_date:%d-%m-%Y}") if meta.issue_date else None,
        ),
        "sender": Field(
            value=sender, read_from=" / ".join(x for x in (post_line, dept_line) if x) or None
        ),
        "main_category": Field(
            value=category, read_from=_line_with(text, ref) if category else None
        ),
        "subject": Field(value=subject, read_from=_line_with(text, subject)),
    }
    return DiaryPrefill(
        **fields,
        department=meta.department,
        from_ocr=from_ocr,
        ocr_confidence=ocr_confidence,
        missing=tuple(k for k, f in fields.items() if not f.value),
    )
