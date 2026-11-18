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

from app.identifiers.canonical import InvalidCanonicalIdError, parse_canonical_id
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
    FILE_RECORD = "File record"  # an e-File's own particulars (subject, previous references)
    GAZETTE = "Gazette Notification"
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
}  # "FILE" (a file record) is no instrument: it governs nothing


class RelKind(StrEnum):
    SUPERSEDES = "SUPERSEDES"
    AMENDS = "AMENDS"
    CLARIFIES = "CLARIFIES"
    REPEALS = "REPEALS"  # withdrawn / cancelled / rescinded by this order
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
    # The date the order says it takes effect ("with effect from 01.07.2016", "shall come into force
    # from …"); None when it states none or several. Not the issue date (data collection item 2).
    stated_effective_from: dt.date | None = None
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
# OCR of a two-column header often puts the number and "Dated:" on separate lines, in either order
# (seen on real Document AI output, 11 Nov 2026). Rejoined only for finding the own reference.
_NUMBER_ONLY = re.compile(
    r"^\s*(?:G\.?\s*O\.?\s*\(?\s*(?:Ms|Rt|P)\s*\)?\.?\s*No\.?\s*\d+"
    r"|(?:Circular\s+Memo|Memo|Rc)\.?\s*No\.?\s*\S+?/\d+/\d{4}(?:-\d+)?"
    r"|Standing\s+Order\s+No\.?\s*\d+\s*/\s*\d{4}),?\s*$",
    re.I,
)
_DATED_ONLY = re.compile(r"^\s*Dated\s*:?\s*\d{1,2}[-./]\d{1,2}[-./]\d{2,4}\s*$", re.I)


def _join_split_header(text: str) -> str:
    """A number line alone and a "Dated:" line alone, adjacent (blank lines aside, either order),
    become one line "<number> Dated: <date>". Nothing else changes."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not _NUMBER_ONLY.match(line):
            continue
        near = [j for j in (i - 1, i + 1, i - 2, i + 2) if 0 <= j < len(lines)]
        for j in near:
            between = lines[min(i, j) + 1 : max(i, j)]
            if _DATED_ONLY.match(lines[j]) and not any(b.strip() for b in between):
                lines[i] = f"{line.strip().rstrip(',')} {lines[j].strip()}"
                lines[j] = ""
                break
    return "\n".join(lines)


# The own line as real orders print it beyond the strict form above (corpus v2, 13 Nov 2026):
# "G.O. Ms. No.:117 Dated: 23.06.2016", "G.O.M s.No.141 Dated:16.08.2017",
# "G.O.Ms.No.175  Date:27.11.2017", "G.O.Ms.No. 63 Dated: 18th April 2016", "Dated:-14.09.2021".
# Read into the strict form, then resolved as before.
_OWN_GO_LOOSE = re.compile(
    r"^\s*G\.?\s*O\.?\s*\(?\s*(?P<kind>M\s?s|Rt|P)\s*\)?\.?\s*No\.?\s*[:.]?\s*"
    r"(?P<num>\d+)[ \t,.]*"
    r"(?:[ \t]*\S{0,3}[ \t]+)?Dat(?:ed|e)\s*[.:]?\s*-?\s*"
    r"(?P<date>\d{1,2}\s*[-./]\s*\d{1,2}\s*[-./]\s*\d{4}"
    r"|\d{1,2}\s*(?:st|nd|rd|th)?\s+[A-Za-z]{3,9}\.?,?\s+\d{4})",
    re.I | re.M,
)
_MONTHS = {
    m: i
    for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )
}


def _loose_own_line(header: str) -> str | None:
    """The own G.O. line in the strict form "G.O.Ms.No.117 Dated: 23.06.2016", or None."""
    m = _OWN_GO_LOOSE.search(header)
    if not m:
        return None
    raw = re.sub(r"\s+", "", m["date"]) if re.match(r"\d+\s*[-./]", m["date"]) else m["date"]
    if w := re.fullmatch(
        r"(\d{1,2})\s*(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", raw.strip()
    ):
        mon = _MONTHS.get(w.group(2)[:3].lower())
        if mon is None:
            return None
        raw = f"{int(w.group(1)):02d}.{mon:02d}.{w.group(3)}"
    kind = {"ms": "Ms", "rt": "Rt", "p": "P"}[re.sub(r"\s", "", m["kind"]).lower()]
    return f"G.O.{kind}.No.{m['num']} Dated: {raw}"


# Gazette masthead (AP e-Gazette): "W.No.3 AMARAVATI, THURSDAY, JANUARY 27, 2022 G.648" with its
# part line ("PART I EXTRAORDINARY", "RULES SUPPLEMENT TO PART I", "PART I - NOTIFICATIONS ...").
# Own ID: AP-GAZ-GAZETTE-<E|W><RS?><part>-<G. number>-<year> (ADR-0007). Part or edition not printed
# → no ID (review).
_GAZ_MAST = re.compile(
    r"^\s*(?P<weekly>W\.\s*)?No\.\s*\d+\s+AMARAVATI,\s*[A-Z]+,\s*(?P<mon>[A-Z]+)\s+(?P<day>\d{1,2}),\s*"
    r"(?P<year>(?:19|20)\d{2})\s+G\.\s*(?P<gno>\d+)\s*$",
    re.M,
)
_GAZ_PART = re.compile(
    r"\b(?P<rs>RULES\s+SUPPLEMENT\s+TO\s+)?PART\s*(?P<part>I{1,3}V?|IV(?:-[AB])?)\b"
    r"(?P<extra>\s*EXTRAORDINARY)?"
)


def _gazette(text: str) -> tuple[str, dt.date] | None:
    """(canonical ID, date of issue) when page 1 carries a gazette masthead with a readable part."""
    head = text[:1500]
    m = _GAZ_MAST.search(head)
    if not m or not re.search(r"Registered\s+No\.|ANDHRA\s+PRADESH\s+GAZETTE", head, re.I):
        return None
    around = head[max(0, m.start() - 300) : m.end() + 200]
    p = _GAZ_PART.search(around)
    mon = _MONTHS.get(m["mon"][:3].lower())
    if not p or mon is None:
        return None
    extraordinary = bool(p["extra"]) or "EXTRAORDINARY" in around
    if extraordinary == bool(m["weekly"]):
        return None  # edition unclear (weekly number on an extraordinary issue, or neither printed)
    code = ("E" if extraordinary else "W") + ("RS" if p["rs"] else "") + p["part"]
    try:
        issued = dt.date(int(m["year"]), mon, int(m["day"]))
    except ValueError:
        return None
    return f"AP-GAZ-GAZETTE-{code}-{int(m['gno'])}-{m['year']}", issued


def _gazette_instrument(text: str) -> str | None:
    """A gazette ranks as what it notifies (hierarchy.yaml, [To confirm]): "… Rules, <year>" →
    statutory rules; otherwise the instrument printed on its own line under the masthead — a
    circular memo (e.g. Gazette 3644/2024 notifies Finance Cir.Memo 25/2023) or a G.O.(Ms).
    None when the notification names neither (no level is guessed)."""
    head = text[:2500]
    if re.search(r"\bRules,?\s*(?:19|20)\d{2}\b", head, re.I):
        return _GAZETTE_RULES
    if re.search(r"^\s*Circular\s*\.?\s*Memo\s*\.?\s*No\b", head, re.I | re.M):
        return "CIRCULAR_MEMO"
    if re.search(r"^\s*G\.?\s*O\.?\s*\(?\s*Ms\s*\)?\.?\s*No\b", head, re.I | re.M):
        return "GO_MS"
    return None


GAZETTE_DEPARTMENT = "GAZ"  # department code of gazette notifications (masthead IDs)


def with_printed_masthead(text: str, page1_layer: str) -> str | None:
    """A gazette scan whose OCR text lost or scrambled the masthead (part line, G. number), while
    the PDF's own text layer on page 1 prints it (e.g. Gazettes 3644/2024, 1905/2023): the text
    with that layer in front, so the masthead rule can read it. Only when the text itself gives no
    gazette ID and the layer gives one; otherwise None (nothing changes, nothing is guessed)."""
    if _gazette(text) is not None or _gazette(page1_layer) is None:
        return None
    return f"{page1_layer.strip()}\n{text}"


_GAZETTE_RULES = (
    "RULES"  # a gazette that notifies "… Rules, <year>": statutory rules (hierarchy level 3)
)

_FILE = re.compile(
    r"File\s+No\.?\s*(?P<file>[A-Z]{2,6}\d{2}-[A-Z0-9]+/\d+/\d{4}-[A-Z][A-Z0-9.]*[A-Z0-9])(?:\s*\(Computer\s+No\.?\s*(?P<cno>\d+)\))?",
    re.I,
)
_FILE_CITE = re.compile(
    r"\bfile\s+No\.?\s*(?P<file>[A-Z]{2,6}\d{2}-[A-Z0-9]+/\d+/\d{4}-[A-Z][A-Z0-9.]*[A-Z0-9])", re.I
)
_FILE_RECORD = re.compile(r"\s*e-File record\b", re.I)
_OPENED_ON = re.compile(r"^\s*Opened on:\s*(\d{1,2}[-./]\d{1,2}[-./]\d{4})", re.I | re.M)
_SIGN_DATE = re.compile(r"(?:^|/)\s*(\d{2}/\d{2}/\d{4})\s+\d{1,2}:\d{2}\s*[AP]M", re.I | re.M)
_AS_ON = re.compile(r"\bAs\s+on\s+(\d{1,2}[-./]\d{1,2}[-./]\d{4})", re.I)
# A department heading is upper case; the section in brackets may not be:
# "FINANCE (HR-5-Pension, GPF) DEPARTMENT".
_HEADING = re.compile(r"^[^a-z\n(]*(?:\([^)\n]*\)[^a-z\n(]*)*\bDEPARTMENT\b[^a-z\n]*$", re.M)
_DATE = re.compile(r"(?:Dated|Dt)\s*[.:]?\s*(\d{1,2}[-./]\d{1,2}[-./]\d{2,4})", re.I)
_ORD = re.compile(r"(\d{1,2})(?:st|nd|rd|th)", re.I)
_ORD_WORDS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
}


def _operative(text: str) -> str:
    """The operative part: from the "ORDER:" heading (not "BY ORDER AND IN THE NAME …")."""
    op = re.search(r"^\s*(?:O\s*R\s*D\s*E\s*R|ORDER)\s*[:.\-]|^\s*NOTIFICATION\s*$", text, re.M)
    return text[op.end() :] if op else (text.split("ORDER", 1)[1] if "ORDER" in text else text)


def _suffix(n: int) -> str:
    return {1: "st", 2: "nd", 3: "rd"}.get(n, "th")


def _norm_ordinals(text: str) -> str:
    """'1 st' / '1 s t' (OCR) and 'first' … 'seventh' read above → '1st' …, for _ORD."""
    t = re.sub(
        r"\b(\d{1,2})\s+(s\s?t|n\s?d|r\s?d|t\s?h)\b",
        lambda m: m[1] + m[2].replace(" ", ""),
        text,
    )
    t = re.sub(r"\b(\d{1,2})(st|nd|rd|th)(read)\b", r"\1\2 \3", t, flags=re.I)  # "4thread"

    def word(m: re.Match[str]) -> str:
        n = _ORD_WORDS[m[1].lower()]
        return f"{n}{_suffix(n)}"

    return re.sub(
        r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth)"
        r"(?=\s+(?:read|cited)\b)",
        word,
        t,
        flags=re.I,
    )


_REF_LINE = re.compile(r"^\s*(?:Ref\s*[:.-]*\s*)?(\d{1,2})\s*[.)]+\s*(?=\S)(.+)$")
_ORDER_CITE = re.compile(
    r"G\.?\s*O\.?\s*\(?\s*(?:Ms|Rt|P)\s*\)?\.?\s*No\.?\s*\d+(?:(?!G\.?\s*O\.|Memo|Rc\.|Standing|File)[^\n]){0,120}?(?:Dt|Dated)[.:\s]*\d{1,2}[-./]\d{1,2}[-./]\d{2,4}"
    r"|(?:Circular\s+Memo|Memo|Rc)\.?\s*No\.?\s*[A-Z0-9()\-.]+/\d+/\d{4}(?:-\d+)?(?:(?!G\.?\s*O\.|Memo|Rc\.|Standing|File)[^\n]){0,120}?(?:Dt|Dated)[.:\s]*\d{1,2}[-./]\d{1,2}[-./]\d{2,4}"
    r"|Standing\s+Order\s+No\.?\s*\d+\s*/\s*\d{4}",
    re.I,
)
# A gazette cited in a note: "A.P. Gazette (Extraordinary / PART I) No.3880, dated 19.02.2024" or
# "(Weekly / Rules Supplement to Part I) No.648, dated 24.01.2022". Resolved to the masthead ID
# (AP-GAZ-GAZETTE-<E|W><RS?><part>-<G. number>-<year>) only when edition and part are both printed.
_GAZ_CITE = re.compile(
    r"A\.?\s*P\.?\s+Gazette\s*\(\s*(?P<ed>Extraordinary|Weekly)\s*/\s*"
    r"(?P<rs>Rules\s+Supplement\s+to\s+)?Part\s*(?P<part>I{1,3}V?|IV(?:-[AB])?)\s*\)\s*"
    r"No\.?\s*(?P<no>\d+)\s*,?\s*(?:Dt|Dated)[.:\s]*\d{1,2}[-./]\d{1,2}[-./](?P<year>(?:19|20)\d{2})",
    re.I,
)


def _gazette_cite(m: re.Match[str]) -> str:
    code = ("E" if m["ed"].lower().startswith("e") else "W") + ("RS" if m["rs"] else "")
    return f"AP-GAZ-GAZETTE-{code}{m['part'].upper()}-{int(m['no'])}-{m['year']}"


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
            r"ABSTRACT\s*\n(?P<s>.+?)\n(?=[^a-z\n(]*(?:\([^)\n]*\)[^a-z\n(]*)*\bDEPARTMENT\b[^a-z\n]*\n)",
            text,
            re.S,
        )
    if not m:
        m = re.search(
            r"^\s*Sub(?:ject)?\s*:\s*(?P<s>.+?)(?=\n\s*(?:Ref\s*:|\*|\[|NOTE\b|Note\s*#|1\.)|\Z)",
            text,
            re.S | re.M,
        )
    if not m:
        return None
    # A line with NUL characters lost glyphs in extraction (a font without a Unicode map, e.g.
    # the Telugu line of a bilingual abstract): leave it out of the subject, never show it garbled.
    lines = [ln for ln in m.group("s").splitlines() if "\x00" not in ln]
    return re.sub(r"\s+", " ", " ".join(lines)).strip() or None


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


_WEF = re.compile(
    r"(?:with\s+effect\s+from|w\.\s*e\.\s*f\.?|(?:shall\s+)?come\s+into\s+force\s+(?:with\s+effect\s+)?"
    r"(?:from|on)|take\s+effect\s+(?:from|on))\s*:?\s*(?:the\s+)?"
    r"(?P<d>\d{1,2}\s*[-./]\s*\d{1,2}\s*[-./]\s*(?:19|20)\d{2}"
    r"|\d{1,2}\s*(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?[A-Za-z]{3,9},?\s+(?:19|20)\d{2})",
    re.I,
)


def _wef_date(raw: str) -> dt.date | None:
    raw = re.sub(r"\s+", " ", raw).strip()
    if m := re.fullmatch(r"(\d{1,2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{4})", raw):
        try:
            return dt.date(int(m[3]), int(m[2]), int(m[1]))
        except ValueError:
            return None
    if m := re.fullmatch(
        r"(\d{1,2})\s*(?:st|nd|rd|th)?\s+(?:day of\s+)?([A-Za-z]{3,9}),?\s+(\d{4})", raw
    ):
        mon = _MONTHS.get(m[2][:3].lower())
        try:
            return dt.date(int(m[3]), mon, int(m[1])) if mon else None
        except ValueError:
            return None
    return None


def _stated_effective_from(subject: str | None, body: str) -> dt.date | None:
    """The subject's "with effect from" date; else the operative text's own commencement
    ("These orders shall come into force with effect from …"). Several different dates → None:
    an order listing dates for different categories states no single one (never guessed)."""
    for part in (subject or "", body):
        dates = {d for m in _WEF.finditer(re.sub(r"\s+", " ", part)) if (d := _wef_date(m["d"]))}
        if len(dates) == 1:
            return dates.pop()
        if dates:
            return None
    return None


def _read_list(text: str) -> list[tuple[int, str]]:
    m = re.search(
        r"Read\s*the\s*following\s*[:.]?\s*-?\s*\n(?P<b>.+?)\n\s*"
        r"(?:\*\s*\*|<>|&\s*&|#\s*#|ORDER\s*[:.-]|O\s+R\s+D\s+E\s+R\b|NOTIFICATION\b)",
        text,
        re.S | re.I,
    )
    if m:
        items: list[tuple[int, str]] = []
        for line in m.group("b").splitlines():
            # items are numbered 1, 2, 3 …: a line that only looks numbered ("15.10.2019." — the
            # end of item 1's date, wrapped) continues the previous item
            if (lm := _REF_LINE.match(line)) and int(lm.group(1)) == len(items) + 1:
                items.append((int(lm.group(1)), lm.group(2).strip()))
            elif items and line.strip():
                n, prev = items[-1]
                # a date broken after its hyphen ("Dt.27-" / "03-2024") joins without a space
                sep = "" if re.search(r"\d-$", prev) and re.match(r"\d", line.strip()) else " "
                items[-1] = (n, f"{prev}{sep}{line.strip()}")
        if not items:
            # "Read the Following: G.O.Ms.No.101, Finance (Budget.I) Dept. dated 14.08.2019": one
            # unnumbered entry is position 1, only when it names one order (as for "Read:-")
            body = re.sub(r"\s+", " ", m.group("b")).strip()
            if body and len(re.findall(r"\bNo\s*\.", body, re.I)) == 1:
                return [(1, body)]
        # OCR glues words: "dated30.04.2015", "Finance(HR.VI-TFR)Department" (G.O.Ms.No.17/2017 FIN)
        return [
            (n, re.sub(r"\)(?=[A-Za-z])", ") ", re.sub(r"(?i)\b(dated|dt)(?=\d)", r"\1 ", t)))
            for n, t in items
        ]
    # "Read:-" with a single unnumbered entry (e.g. G.O.Rt.No.2740/2019 GA: "Read:- G.O.Rt.No.2657,
    # G.A (Cabinet.I) Department, Dated.26.11.2019."): position 1, only when it names one order
    one = re.search(
        r"^[ \t]*Read\s*[:.]?\s*-?[ \t]*\n(?P<b>.+?)\n\s*(?:ORDER\s*[:.-]|O\s+R\s+D\s+E\s+R\b)",
        text,
        re.S | re.M,
    )
    if one:
        body = re.sub(r"\s+", " ", one.group("b")).strip()
        if body and not _REF_LINE.match(body) and len(re.findall(r"\bNo\s*\.", body, re.I)) == 1:
            return [(1, body)]
    ref = re.search(r"^\s*Ref\s*:\s*(?P<r>.+?)(?=\n\s*(?:\*|1\.)|\n\n)", text, re.S | re.M)
    return [(1, re.sub(r"\s+", " ", ref.group("r")).strip())] if ref else []


def _sentences_with(body: str, pattern: str) -> list[str]:
    flat = re.sub(r"\s+", " ", body)
    flat = re.sub(
        r"\b(No|Dt|dt|Rc|Lr|Ms|Rt)\.\s+(?=[\dA-Z(])", r"\1.", flat
    )  # "No. 34": no full stop
    # "G. O. Ms. No. 67" / "the G.O. 1st read above": the order's name is not a sentence end
    flat = re.sub(r"\bG\s?\.\s?O\s?\.\s+(?=\(?\s*(?:Ms|Rt|P)\b|\d)", "G.O.", flat)
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
    header = _join_split_header(text)
    gazette = _gazette(text)
    if gazette is None:
        for rx in (_OWN_GO, _OWN_MEMO, _OWN_SO):
            if m := rx.search(header):
                own_raw = re.sub(r"\s+", " ", m.group(1)).strip()
                break
        loose = _OWN_GO_LOOSE.search(header)
        strict = _OWN_GO.search(header)
        if loose and (own_raw is None or (strict is not None and loose.start() < strict.start())):
            own_raw = _loose_own_line(
                header
            )  # the earlier line is the order's own (body lines follow)

    canonical: str | None = None
    issue: dt.date | None = None
    typ: str | None = None
    if gazette is not None:
        canonical, issue = gazette
        typ, dept = "GAZETTE", GAZETTE_DEPARTMENT
    elif own_raw:
        r = resolve_reference(own_raw, departments, dept)
        # the gazette folder's tag is not a department: never borrow it for an order's own number
        borrow = source_department and source_department != GAZETTE_DEPARTMENT
        if r.unresolved is Unresolved.NO_DEPARTMENT and dept is None and borrow:
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
    elif typ == "GAZETTE":
        doc_type = DocType.GAZETTE
    elif own_raw is None and re.search(r"^\s*Report\s+of\b", text, re.M | re.I):
        doc_type, typ, dept = DocType.REPORT, "RPT", dept or file_dept
        if dm := _DATE.search(text):
            issue = _date(dm.group(1))
    elif own_raw is None and _FILE_RECORD.match(text):
        # the e-File's own particulars, written by the e-Office when the file is opened
        doc_type, typ, dept = DocType.FILE_RECORD, "FILE", dept or file_dept
        if om := _OPENED_ON.search(text):
            issue = _date(om.group(1))
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
    reads_citations = is_note or doc_type is DocType.FILE_RECORD
    if reads_citations:
        flat_text = re.sub(r"\s+", " ", text)  # citations wrap across lines in PDF layout
        refs.extend(cited_references(flat_text, departments, dept))
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

    relations = _relations(text, refs, doc_type, subject, reads_citations)
    seen: set[str] = set()
    unique: list[RelationCandidate] = []
    for rel in relations:
        key = f"{rel.kind}|{rel.target}"
        if key not in seen:
            seen.add(key)
            unique.append(rel)
    if canonical is None and typ not in ("NOTE", "RPT", "ANX", "FILE"):
        reasons.append("no own reference found")

    return DocumentMetadata(
        doc_type=doc_type,
        canonical_id=canonical,
        raw_reference=own_raw or (f"File No.{file_m.group('file')}" if file_m else None),
        instrument=_gazette_instrument(text)
        if typ == "GAZETTE"
        else INSTRUMENT_FOR_TYPE.get(typ or ""),
        issue_date=issue,
        department=dept,
        subject=subject,
        department_source=None if dept is None else "source_system" if dept_from_source else "text",
        valid_until=_valid_until(subject, doc_type),
        stated_effective_from=_stated_effective_from(subject, _operative(text))
        if doc_type in _DATED_TYPES or doc_type is DocType.GAZETTE
        else None,
        file_no=file_m.group("file") if file_m else None,
        computer_no=file_m.group("cno") if file_m else None,
        references=tuple(refs),
        relations=tuple(unique),
        review_reasons=tuple(reasons),
    )


def cited_references(
    text: str, departments: DepartmentTable, department: str | None
) -> tuple[Reference, ...]:
    """Orders and gazette notifications cited in running text, as a note cites them (plan §5.6).

    Also reads what an officer typed for a new draft. Unresolved citations keep their raw form."""
    flat = re.sub(r"\s+", " ", text)
    refs = [
        Reference(
            position=None,
            raw=m.group(0),
            canonical_id=resolve_reference(m.group(0), departments, department).canonical_id,
        )
        for m in _ORDER_CITE.finditer(flat)
    ]
    refs += [
        Reference(position=None, raw=m.group(0), canonical_id=_gazette_cite(m))
        for m in _GAZ_CITE.finditer(flat)
    ]
    return tuple(refs)


# Real orders often name the earlier order by number rather than by its place in the Read list
# ("in supersession of the orders issued in G.O.Ms.No.230 …", "the following amendments to the
# guidelines issued in G.O.Ms.No.25 …"). Such a number counts only when it matches exactly one
# order of the Read list (corpus v2, 13 Nov 2026).
_GO_NUM = re.compile(r"G\.?\s*O\.?\s*\(?\s*(?:Ms|Rt|P)\s*\)?\.?\s*No\.?\s*[:.]?\s*(\d+)", re.I)
_SUPERSEDE_ONLY = re.compile(
    r"in supersession of(?:(?!\bhereby\b|\bGovernment\b).){0,120}?\bread above\b", re.I
)
_SUPERSEDE_NUM = re.compile(
    r"in supersession of(?:(?!\bhereby\b|\bGovernment\b|\bGovernor\b|\bread above\b).){0,200}", re.I
)
# DR / DA orders "revise" an earlier order's rate ("raising it … from 12.052% to 15.196%")
_CHANGE_VERB = re.compile(
    r"\b(?:amend\w*|modif\w*|substitut\w*|replac\w*|revis\w*|enhanc\w*|rais(?:e|ed|ing))\b", re.I
)
_CHANGE_SUBJECT = re.compile(
    r"\b(?:Amendments?|Modifi\w*|Modified|Substitution|Replacement|Revised|Revision|Enhancement)\b",
    re.I,
)
# "In partial modification of the orders issued in the reference first read above, …": the order
# named is changed, not replaced (G.O.Ms.No.63/2016 and 123/2016 FIN; efiles_v2 type F, 18 Nov)
_PARTIAL_MOD = re.compile(
    r"in\s+partial\s+modification\s+of(?:(?!\bhereby\b|\bGovernment\b).){0,160}?read\s+above",
    re.I,
)
# a rate revised "from 15.196% … to 18.340%" of a Dearness Relief / Allowance sanctioned in an order
# of the Read list: that order is changed (G.O.Ms.No.17/2017, 115/2023 FIN)
_RATE_REVISION = re.compile(
    r"\brevision\s+of\s+(?:(?:the\s+)?rates?\s+of\s+)?Dearness\s+(?:Relief|Allowance)[^.]{0,80}?"
    r"\bsanctioned\s+in\s+the\s+(?:G\.?\s?O\.?s?|Government\s+orders?)\s*"
    r"(?P<o>\d{1,2})(?:st|nd|rd|th)\s+read\s+above.{0,200}?\bfrom\s+\d+(?:\.\d+)?\s*%"
    r".{0,120}?\bto\s+\d+(?:\.\d+)?\s*%",
    re.I,
)
# "Government … hereby withdraw the above G.O.Ms.No.187 … read with amendment G.O.Ms.No.190 …"
# (G.O.Ms.No.39/2023 SE): the orders named in the operative clause are withdrawn (efiles_v2, 18 Nov)
_WITHDRAW = re.compile(
    r"\bhereby\s+(?:withdraws?|cancels?|rescinds?)\b(?P<what>.{0,300}?)(?:\.\s+[A-Z0-9(]|$)",
    re.I,
)
# "… issued in G.O.Ms.No.32 … read with G.O.Ms.No.38 … and G.O.Ms.No.43 …": orders read together
# make up the Rules changed (G.O.Ms.No.50/2017 SE); "as amended in …" stays history
_READ_WITH = re.compile(r"^(?:(?!\bas\s+amended\b|\bAMENDMENTS?\b).){0,260}", re.S)
_DA_REVISION = re.compile(r"\brevision\s+of\s+(?:the\s+)?rates?\s+of\s+Dearness", re.I)
_OWN_CHANGE = re.compile(
    r"hereby\s+(?:make|makes|issue|issues)\s+the\s+following\s+(?:amendments?|modifications?)", re.I
)


def _is_letter(ref: Reference) -> bool:
    """A Read-list entry that is correspondence ("From the Commissioner …, Lr.Rc.No …"), not an
    order: it is never the order an amendment changes."""
    return bool(re.match(r"\s*From\b", ref.raw, re.I))


def _number_of(cid: str | None) -> int | None:
    if not cid:
        return None
    try:
        return parse_canonical_id(cid).number
    except InvalidCanonicalIdError:
        return None  # an ID the resolver could not form validly is never matched


def _by_number(sentence: str, refs: list[Reference]) -> list[Reference]:
    """Read-list orders named by number in `sentence`; a number two listed orders share → none."""
    out: list[Reference] = []
    for m in _GO_NUM.finditer(sentence):
        n = int(m.group(1))
        same = [r for r in refs if r.position is not None and _number_of(r.canonical_id) == n]
        if len(same) == 1 and same[0] not in out:
            out.append(same[0])
    return out


def _changed_by(after: str, refs: list[Reference]) -> list[Reference]:
    """The order(s) an amendment phrase changes: the first order named, and those "read with" it
    (they make up the Rules together); an order named "as amended in …" is history, not changed."""
    first = _by_number(after, refs)[:1]
    if not first:
        return []
    m = _GO_NUM.search(after)
    rest = after[m.end() :] if m else ""
    if not re.match(r".{0,90}?\bread\s+with\b", rest, re.I | re.S):
        return first
    clause = _READ_WITH.match(rest)
    more = _by_number(clause.group(0), refs) if clause else []
    return first + [r for r in more if r not in first]


def _relations(
    text: str, refs: list[Reference], doc_type: DocType, subject: str | None, is_note: bool
) -> list[RelationCandidate]:
    by_pos = {r.position: r for r in refs if r.position is not None}
    out: list[RelationCandidate] = []
    explicit_targets: set[int] = set()
    body = _norm_ordinals(_operative(text))

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
    if not is_note and len(by_pos) == 1 and not explicit_targets:
        # "In supersession of the orders issued in the G.O. read above": no ordinal is needed
        # (or printed) when the Read list has a single entry
        m1 = _SUPERSEDE_ONLY.search(flat)
        ((pos, only),) = by_pos.items()
        if m1 and not _ORD.search(m1.group(0)):
            add(RelKind.SUPERSEDES, only, True, m1.group(0))
            explicit_targets.add(pos)
    if not is_note:
        for m in _SUPERSEDE_NUM.finditer(flat):
            for ref in _by_number(m.group(0), refs):
                if ref.position is not None and ref.position not in explicit_targets:
                    add(RelKind.SUPERSEDES, ref, True, m.group(0))
                    explicit_targets.add(ref.position)
    if doc_type is DocType.AMENDMENT:
        for sentence in _sentences_with(body, r"amendment"):
            own = _OWN_CHANGE.search(sentence)
            named = _changed_by(sentence[own.end() :], refs) if own else []
            picks = named or [
                by_pos[n] for n in (int(x) for x in _ORD.findall(sentence)) if n in by_pos
            ]
            for ref in picks:
                at = ref.position
                if at is None or at in explicit_targets or not ref.canonical_id:
                    continue
                if not _is_letter(ref):
                    add(RelKind.AMENDS, ref, True, sentence)
                    explicit_targets.add(at)
    if not is_note:
        for m in _WITHDRAW.finditer(flat):
            named = _by_number(m.group("what"), refs) or [
                by_pos[n] for n in (int(x) for x in _ORD.findall(m.group("what"))) if n in by_pos
            ]
            for ref in named:
                if ref.position is not None and ref.canonical_id and not _is_letter(ref):
                    if ref.position not in explicit_targets:
                        add(RelKind.REPEALS, ref, True, m.group(0))
                        explicit_targets.add(ref.position)
    if not is_note:
        flat_ord = _norm_ordinals(flat)
        for pattern in (_PARTIAL_MOD, _RATE_REVISION):
            for m in pattern.finditer(flat_ord):
                ords = (
                    [int(m.group("o"))]
                    if "o" in pattern.groupindex
                    else [int(x) for x in _ORD.findall(m.group(0))]
                )
                if not ords and "read above" in m.group(0).lower() and len(by_pos) == 1:
                    ords = list(by_pos)
                for n in ords:
                    hit = by_pos.get(n)
                    if hit and hit.canonical_id and not _is_letter(hit):
                        if n not in explicit_targets:
                            add(RelKind.AMENDS, hit, True, m.group(0))
                            explicit_targets.add(n)
    changes_by_title = doc_type in (DocType.AMENDMENT, DocType.GAZETTE) or bool(
        subject and _CHANGE_SUBJECT.search(subject)
    )
    if not is_note:
        for sentence in _sentences_with(body, _CHANGE_VERB.pattern):
            if not (changes_by_title or _OWN_CHANGE.search(sentence)):
                continue
            if _DA_REVISION.search(sentence) or _PARTIAL_MOD.search(sentence):
                # read precisely above (_RATE_REVISION, _PARTIAL_MOD): only the order whose rate
                # was "sanctioned in" is changed; other orders the sentence names are conditions
                continue
            if doc_type is DocType.GAZETTE and not _CHANGE_SUBJECT.search(text[:2500]):
                continue
            own = _OWN_CHANGE.search(sentence)
            # "hereby make the following amendments to the … Rules issued in G.O.Ms.No.20, as
            # amended in G.O.Ms.No.130 …": the order changed is the first one named after the phrase
            named = _changed_by(sentence[own.end() :], refs) if own else []
            targets = (named or _by_number(sentence, refs)) + [
                by_pos[n]
                for n in (int(x) for x in _ORD.findall(sentence))
                if n in by_pos and by_pos[n].canonical_id
            ]
            for ref in targets:
                if (
                    ref.position is not None
                    and ref.position not in explicit_targets
                    and not _is_letter(ref)
                ):
                    add(RelKind.AMENDS, ref, True, sentence)
                    explicit_targets.add(ref.position)
        orders = [r for r in refs if r.position is not None and r.canonical_id]
        if changes_by_title and not explicit_targets and len(orders) == 1:
            # an amendment / modification whose Read list names exactly one order: that order is
            # the one changed. Inferred from the title, so a candidate (explicit=False) for review.
            add(RelKind.AMENDS, orders[0], False, subject or "amendment by title")
            explicit_targets.add(orders[0].position or 0)
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


class CitationSpan(_Frozen):
    """Where one citation sits in a text, as offsets into that text (ADR-0015 highlights)."""

    kind: str  # "order" (G.O. / memo / circular / standing order) or "efile"
    start: int
    end: int  # exclusive
    raw: str  # whitespace collapsed, as `extract_metadata` records it; e-File: the file number


def citation_spans(text: str) -> list[CitationSpan]:
    """The order and e-File citations in a note, located in the original text (plan §4.4).

    Uses the same patterns as `extract_metadata`, run over the whitespace-collapsed text (citations
    wrap across lines), with each collapsed position mapped back to the original offset."""
    flat: list[str] = []
    origin: list[int] = []
    for m in re.finditer(r"\s+|\S", text):
        flat.append(" " if m.group(0).isspace() else m.group(0))
        origin.append(m.start())
    s = "".join(flat)

    def span(kind: str, a: int, b: int, raw: str) -> CitationSpan:
        return CitationSpan(kind=kind, start=origin[a], end=origin[b - 1] + 1, raw=raw)

    out = [span("order", m.start(), m.end(), m.group(0)) for m in _ORDER_CITE.finditer(s)]
    out += [
        span("efile", m.start("file"), m.end("file"), m.group("file"))
        for m in _FILE_CITE.finditer(s)
    ]
    return sorted(out, key=lambda c: c.start)
