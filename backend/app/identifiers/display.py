"""A canonical ID as an officer writes it in a note (plan §11.5 touchpoint 7; ADR-0034).

`AP-FIN01-GOMS-31-2025#para-2.v` → "G.O.Ms.No.31, Finance Department, dated 12-05-2025, para 2(v)".
Only what the ID and the record's own date say: no number, date or department is guessed. A form
not listed here is shown as the canonical ID itself.
"""

from __future__ import annotations

import datetime as dt
import functools
import re
from collections.abc import Mapping

from app.identifiers.canonical import InvalidCanonicalIdError, parse_canonical_id

_LABEL = {
    "GOMS": "G.O.Ms.No.",
    "GORT": "G.O.Rt.No.",
    "GOP": "G.O.P.No.",
    "MEMO": "Memo No.",
    "CIRMEMO": "Circular Memo No.",
    "RC": "Rc.No.",
    "OO": "Office Order No.",
    "OM": "O.M.No.",
    "NOTIFICATION": "Notification No.",
    "SO": "Standing Order No.",
}


@functools.cache
def department_names() -> Mapping[str, str]:
    """Department code → name, from the versioned ontology (departments.yaml)."""
    from app.config import get_settings  # noqa: PLC0415 — avoid a config import at module load
    from app.identifiers.resolver import load_departments  # noqa: PLC0415

    table = load_departments(get_settings().ontology_dir / "departments.yaml")
    return {d.code: d.name for d in table.departments}


def _clause(clause: str) -> str:
    """`para-2.v` → `para 2(v)`; `para-3` → `para 3`."""
    kind, _, where = clause.partition("-")
    head, *rest = where.split(".")
    return f"{kind} {head}" + "".join(f"({r})" for r in rest)


def reference_text(
    canonical_id: str,
    issue_date: dt.date | None = None,
    names: Mapping[str, str] | None = None,
) -> str:
    try:
        c = parse_canonical_id(canonical_id)
    except InvalidCanonicalIdError:
        return canonical_id
    label = _LABEL.get(c.doc_type)
    if label is None:
        return canonical_id  # notes, rules, gazettes: the ID is the reference
    names = department_names() if names is None else names
    number = f"{c.number}/{c.year}" if c.doc_type in {"MEMO", "CIRMEMO", "RC"} else str(c.number)
    parts = [f"{label}{number}"]
    if c.department in names:
        parts.append(f"{names[c.department]} Department")
    if issue_date is None and c.date_tag:  # the issue date carried in the ID (ADR-0007)
        issue_date = dt.datetime.strptime(c.date_tag, "%Y%m%d").date()
    if issue_date is not None:
        parts.append(f"dated {issue_date:%d-%m-%Y}")
    elif c.doc_type not in {"MEMO", "CIRMEMO", "RC"}:
        parts.append(f"of {c.year}")
    if c.clause and re.fullmatch(r"[a-z]+-[A-Za-z0-9.]+", c.clause):
        parts.append(_clause(c.clause))
    return ", ".join(parts)
