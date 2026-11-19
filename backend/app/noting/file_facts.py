"""The request and the verified facts of a file, from its own notes (plan §8.1 noting sections,
§11.5 touchpoint 6; ADR-0060 and its addendum). Deterministic, quoted, cited by paragraph; nothing
is written by a model, and nothing is assumed.

An e-Office note on a receipt starts by stating what the PUC asks for ("… has requested …",
"It is submitted that a reference has been received from … (PUC, p.1)"), and the dealing hand then
records what was verified ("As verified, (a) the station period …"). The next note needs both.

Three layers, so that real notes worded differently are not misread:
1. **Structure** (`chain.note_structure`): only the numbered body paragraphs of a note are read —
   never its "Sub:" line or the items of its "Ref:" list — and the role of each paragraph is
   judged: a request, a record of facts, a restatement of an order, a submission or a decision.
2. **Context**: a paragraph is weighed with signals from the file itself — it is in the first
   note, it refers to the PUC (Flag A, PUC, a receipt in the note's reference list), it names the
   person or matter the file subject names — not on its wording alone. Phrases only propose
   candidates; the signals decide.
3. **Validation**: every quoted paragraph is re-checked against the note it came from (the same
   words, at that paragraph number). A paragraph that fails is dropped, never repaired.

Confidence decides what happens: a request with enough independent signals is quoted; a likely
one that is not certain, and any fact the file records without saying it was verified, go to
`review` — shown to the officer as points to confirm, never stated as facts. When nothing fits,
the gap stays for the officer and says so. The officer's own words always take precedence.

The notes of one e-File share one run of paragraph numbers: a new note continues after the last
paragraph of the notes before it (`next_paragraph`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.noting.chain import NoteEntry

# ---- candidate phrases (layer 1: they propose; the signals decide) -----------------------------

_REQUEST = re.compile(
    r"\b(?:has|have)\s+(?:requested|applied|sought|represented|prayed)\b|\brequests?\s+(?:for|to)\b"
    r"|\bapplied\s+for\b|\b(?:reference|representation|application|request|proposal|letter)s?\s+"
    r"(?:has|have|was|were|is)\s+(?:been\s+)?(?:received|placed|submitted|forwarded)\b"
    r"|\brepresentation\s+of\b",
    re.I,
)
_PUC = re.compile(r"\bPUC\b|\bFlag\s*['\"]?A\b|\bplaced\s+(?:below|at)\b|\bReceipt\s+No\b", re.I)
_VERIFIED = re.compile(
    r"\b(?:as\s+verified|it\s+is\s+verified|on\s+verification|verified\s+(?:that|from|with)"
    r"|as\s+per\s+(?:the\s+)?(?:service\s+register|records?|roster|seniority\s+list|S\.?R\.?)"
    r"|it\s+is\s+seen\s+(?:that|from)|it\s+is\s+reported\s+(?:that|by)|confirmed\s+(?:that|from))\b",
    re.I,
)
# a paragraph about the individual or the matter with something checkable in it
_FACTUAL = re.compile(
    r"\b\d{1,2}[-./]\d{1,2}[-./]\d{2,4}\b|\b\d+\s+(?:years?|months?|days?|posts?|transfers?)\b"
    r"|\b(?:is|was|are|were)\s+working\b|\bstation\s+period\b|\bno\s+(?:disciplinary|vigilance)\b"
    r"|\b(?:pending|not\s+pending)\b|\b\d+(?:\.\d+)?\s*%",
    re.I,
)
# not facts about the matter: an order restated, a submission, a decision, an approval sought
_ORDER_TALK = re.compile(
    r"^\s*\d{1,3}[.)]\s*(?:as\s+per|according\s+to|under)\s+(?:para|G\.?O|rule|the\s+orders)"
    r"|\borders\s+on\s+the\s+subject\s+are\s+(?:contained\s+)?in\b|\bproposal\s+(?:relies|rests)\s+on\b"
    r"|\b(?:relevant|applicable)\s+orders\s+are\b|\bfile\s+was\s+(?:referred|sent|returned)\b"
    r"|\bas\s+ordered\s+(?:at|in)\s+para\b"
    r"|\bGovernment,?\s+(?:in|vide)\s+(?:G\.?O|Memo|Circular|the\s+orders?)\b"
    r"|\b(?:G\.?O\.?\s*\(?(?:Ms|Rt|P)\)?|Memo|Circular)[^.]{0,80}\bprovides?\b",
    re.I,
)
_PROCEDURAL = re.compile(
    r"^\s*\d{1,3}[.)]\s*(?:Sir,?\s+)?(?:submitted|approved|agreed|put\s+up|approval\s+requested"
    r"|may\s+(?:kindly\s+)?(?:approve|see|be\s+seen)|not\s+agreed|para\s+\d+\s*[-–]?\s*agreed"
    r"|para\s+\d+\s+may\s+(?:kindly\s+)?be\s+seen"
    r"|issue\s+orders|orders?\s+(?:may|are)|discussed|seen|noted)\b",
    re.I,
)
_FLAGGED_ORDER = re.compile(
    r"\b(?:G\.?O\.?\s*\(?(?:Ms|Rt|P)\)?\.?\s*No|Memo\s+No|Circular).{0,140}?\(\s*Flag\s*['\"]?A",
    re.I,
)
_PERSON = re.compile(
    r"\b(?:Sri|Smt|Kum|Dr|Mr|Ms|Mrs)\.?\s+((?:[A-Z][a-z]?\.\s*)*[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)"
    r"|\bin\s+respect\s+of\s+((?:[A-Z][a-z]?\.\s*)*[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)"
)
_STOP = frozenset(
    "the and for with from that this regarding reg request requested transfer orders order issued "
    "government department establishment section officer office regional proposal".split()
)

REQUEST_QUOTE_AT = 6  # score at which a request (with a request phrase) is quoted
REQUEST_REVIEW_AT = 3  # score at which a paragraph is offered for the officer to confirm
MAX_REVIEW = 3

Status = Literal["stated", "verified"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FileParagraph(_Frozen):
    note_no: int
    paragraph: int
    text: str  # verbatim, with its own number
    source: str  # canonical ID of the note document
    ref: str  # "<source>#note-<n>-para-<p>": what the draft cites
    status: Status = "stated"  # "verified": the paragraph itself says it was verified
    basis: tuple[str, ...] = ()  # why it was chosen, in words the officer can check


class ReviewItem(_Frozen):
    kind: Literal["request", "fact"]
    reason: str
    paragraph: FileParagraph


class FileFacts(_Frozen):
    request: tuple[FileParagraph, ...] = ()  # quoted: confident, validated
    facts: tuple[FileParagraph, ...] = ()  # quoted: each says it was verified, validated
    review: tuple[ReviewItem, ...] = ()  # for the officer to confirm; never stated as facts
    request_status: Literal["found", "review", "not_found"] = "not_found"
    last_paragraph: int = 0  # the last paragraph number on the file's notes (0: none numbered)

    @property
    def next_paragraph(self) -> int:
        return self.last_paragraph + 1


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _para(
    n: NoteEntry,
    number: int,
    words: str,
    *,
    status: Status = "stated",
    basis: tuple[str, ...] = (),
) -> FileParagraph:
    return FileParagraph(
        note_no=n.note_no,
        paragraph=number,
        text=words,
        source=n.source,
        ref=f"{n.source}#note-{n.note_no}-para-{number}",
        status=status,
        basis=basis,
    )


def _validated(fp: FileParagraph, by_note: dict[int, NoteEntry]) -> bool:
    """The quote is the note's own words at that paragraph number (layer 3)."""
    n = by_note.get(fp.note_no)
    if n is None or n.source != fp.source:
        return False
    at = dict(n.by_paragraph).get(fp.paragraph)
    return at is not None and _norm(at) == _norm(fp.text) and _norm(fp.text) in _norm(n.text)


def _subject_terms(subject: str) -> tuple[set[str], set[str]]:
    """The people the file subject names (surnames and given names) and its content words."""
    people: set[str] = set()
    for m in _PERSON.finditer(subject):
        name = m.group(1) or m.group(2) or ""
        people |= {w.lower() for w in re.findall(r"[A-Za-z]{3,}", name)}
    words = {
        w for w in re.findall(r"[a-z]{4,}", subject.lower()) if w not in _STOP and w not in people
    }
    return people, words


def _request_score(
    words: str,
    *,
    first_note: bool,
    first_para: bool,
    puc_in_refs: bool,
    people: set[str],
    terms: set[str],
) -> tuple[int, tuple[str, ...], bool]:
    """(score, basis, has a request phrase) for one body paragraph (layer 2)."""
    score, basis = 0, []
    phrase = bool(_REQUEST.search(words))
    if phrase:
        score += 3
        basis.append("states a request or a reference received")
    if _PUC.search(words):
        score += 2
        basis.append("refers to the PUC")
    elif puc_in_refs and first_note:
        score += 1
        basis.append("the note lists the receipt in its references")
    if first_note:
        score += 1
        basis.append("in the first note on the file")
    if first_para:
        score += 1
        basis.append("the first paragraph of the file")
    low = words.lower()
    if people and any(p in low for p in people):
        score += 2
        basis.append("names the person in the file subject")
    elif terms and sum(t in low for t in terms) / len(terms) >= 0.4:
        score += 1
        basis.append("matches the file subject")
    if _ORDER_TALK.search(words) or _PROCEDURAL.match(words):
        score -= 4
    if _FLAGGED_ORDER.search(words):
        score -= 2  # the flagged paper is an order, not a request
    return score, tuple(basis), phrase


def file_facts(notes: Iterable[NoteEntry], *, subject: str = "", max_facts: int = 4) -> FileFacts:
    """From the notes of ONE file the officer may see (any order) and the file's subject: the
    paragraph stating the request, the paragraphs recording what was verified (up to
    `max_facts`), the points the officer should confirm, and the last paragraph number used."""
    ordered = sorted(notes, key=lambda n: n.note_no)
    by_note = {n.note_no: n for n in ordered}
    people, terms = _subject_terms(subject)
    last = 0
    for n in ordered:
        for number, _ in n.by_paragraph:
            last = max(last, number)
        if n.paragraphs:
            last = max(last, n.paragraphs[1])

    # the request: the best-supported body paragraph, earliest on a tie
    best: tuple[int, FileParagraph, bool] | None = None
    first_body = next(((n.note_no, p) for n in ordered for p, _ in n.by_paragraph), None)
    for idx, n in enumerate(ordered):
        puc_in_refs = any(_PUC.search(r) for r in n.references)
        for number, words in n.by_paragraph:
            score, basis, phrase = _request_score(
                words,
                first_note=idx == 0,
                first_para=(n.note_no, number) == first_body,
                puc_in_refs=puc_in_refs,
                people=people,
                terms=terms,
            )
            if best is None or score > best[0]:
                best = (score, _para(n, number, words, basis=basis), phrase)

    request: tuple[FileParagraph, ...] = ()
    review: list[ReviewItem] = []
    status: Literal["found", "review", "not_found"] = "not_found"
    if best is not None and _validated(best[1], by_note):
        score, fp, phrase = best
        if score >= REQUEST_QUOTE_AT and phrase:
            request, status = (fp,), "found"
        elif score >= REQUEST_REVIEW_AT:
            status = "review"
            review.append(
                ReviewItem(
                    kind="request",
                    reason="may state the request, but the file does not say so clearly",
                    paragraph=fp,
                )
            )
    taken = {(p.note_no, p.paragraph) for p in request} | {
        (r.paragraph.note_no, r.paragraph.paragraph) for r in review
    }

    # facts: verified ones are quoted; facts recorded without saying so go to review
    facts: list[FileParagraph] = []
    for n in ordered:
        for number, words in n.by_paragraph:
            if (n.note_no, number) in taken:
                continue
            if _ORDER_TALK.search(words) or _PROCEDURAL.match(words):
                continue  # an order restated, or a submission / decision: not a fact
            if _VERIFIED.search(words):
                fp = _para(n, number, words, status="verified", basis=("states it was verified",))
                if len(facts) < max_facts and _validated(fp, by_note):
                    facts.append(fp)
            elif _FACTUAL.search(words) and _REQUEST.search(words) is None:
                fp = _para(n, number, words, basis=("records a fact",))
                if sum(r.kind == "fact" for r in review) < MAX_REVIEW and _validated(fp, by_note):
                    review.append(
                        ReviewItem(
                            kind="fact",
                            reason="recorded in the file, but not stated as verified",
                            paragraph=fp,
                        )
                    )
    return FileFacts(
        request=request,
        facts=tuple(facts),
        review=tuple(review),
        request_status=status,
        last_paragraph=last,
    )
