"""The assistant as a conversation partner (ADR-0067, owner-approved change to plan §5.6).

Two optional model steps around the unchanged, scoped answer pipeline:

1. **Intent** (`route_intent`): Gemini reads the officer's message and picks ONE of a fixed,
   closed list of the file's tools, or "search". It never writes a query, never sees records and
   never widens access: every tool is the same scoped endpoint the officer could click, and
   "search" is the unchanged ladder (whose rung choice stays rule-based, plan §5.6). Anything
   outside the list, an error or no model: `None`, and the screen falls back to the fixed rules.
2. **Composition** (`compose_answer`): after the citation check, Gemini arranges the CHECKED
   statements like an assistant would answer: a one-line direct answer, then the statements under
   short headings. It sees only the statements (already shown to this officer), not the evidence.
   Deterministic gates keep it honest: every statement appears exactly once (none dropped,
   none invented); headings carry no numbers, dates or order references; the lead may only use
   numbers/dates/references present in the statements it names, and most of its words must come
   from them. A lead or heading that fails is dropped, never repaired; if nothing passes, the
   answer is shown as before.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from typing import Any

from app.agents.llm import LLMClient, LLMError, load_prompt
from app.connectors.eoffice import FileContext

log = logging.getLogger(__name__)

INTENT_PROMPT = "intent_route.v4"
COMPOSE_PROMPT = "answer_compose.v2"

# the file's own tools, as the screen names them (FileChatTools.tsx); "search" = the scoped ladder
FILE_TOOLS: tuple[str, ...] = (
    "summary", "movements", "records", "brief", "since", "presend", "related",
    "first_cut", "dfa", "closing", "note_ref", "reference", "ask_file",
)  # fmt: skip
SEARCH = "search"

_NUM = re.compile(r"\d+(?:[./-]\d+)*")  # numbers, dates, order numbers
_WORD = re.compile(r"[A-Za-z][A-Za-z'-]{3,}")
_STOP = frozenset(
    "this that with from have were been which their there these those about into also only "
    "under than when where what will would shall should could upon such each other more most "
    "file files record records order orders".split()
)


def route_intent(
    llm: LLMClient | None, message: str, *, on_file: bool, allowed: Sequence[str]
) -> str | None:
    """The tool the officer is asking for, or SEARCH; None when the model cannot say (the screen
    then uses its fixed rules). `allowed` is the screen's own list; the answer must be in it."""
    choices = [t for t in allowed if t in FILE_TOOLS]
    if llm is None or not choices:
        return None
    options = [*choices, SEARCH]
    try:
        out = llm.generate_json(
            prompt_id=INTENT_PROMPT,
            system=load_prompt(INTENT_PROMPT),
            user=(
                f"Place: {'a file the officer has open' if on_file else 'the general chat'}\n"
                f"Tools offered: {', '.join(options)}\n"
                f"<message>{message[:500]}</message>"
            ),
            schema={
                "type": "object",
                "properties": {"tool": {"type": "string", "enum": options}},
                "required": ["tool"],
            },
        )
    except LLMError as e:
        log.info("intent route: model unavailable (%s)", type(e).__name__)
        return None
    tool = out.get("tool") if isinstance(out, dict) else None
    return str(tool) if isinstance(tool, str) and tool in options else None


def _content(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text)} - _STOP


# What a written sentence may claim happened (meaning check, 25 Nov 2026): a sentence that says a
# proposal was approved, an order issued, a file closed... must find that word in the records it
# names, with the same polarity ("not approved" vs "approved").
_CLAIMS = (
    "approved", "agreed", "sanctioned", "issued", "rejected", "returned", "closed", "completed",
    "cancell?ed", "withdrawn", "superseded", "rescinded", "disposed",
)  # fmt: skip
_NEG = re.compile(
    # a negation up to three words before, in the same clause ("No. It is closed" is not one)
    r"(?:\b(?:not|no|never|nor|without|yet to be)|n't)(?:[^\w.,;:!?]+\w+){0,3}?[^\w.,;:!?]+$",
    re.IGNORECASE,
)


def _polarities(text: str, word: str) -> set[bool]:
    """For each occurrence of `word`: True when said plainly, False when negated."""
    out: set[bool] = set()
    for m in re.finditer(rf"\b{word}\b", text, re.IGNORECASE):
        before = text[max(0, m.start() - 40) : m.start()]
        out.add(_NEG.search(before) is None)
    return out


def claims_supported(text: str, base: str) -> bool:
    """Every claim word in `text` occurs in `base`, and a plain claim has a plain occurrence there
    (a negated one, a negated one). Deterministic; never asks the model."""
    for root in _CLAIMS:
        said = _polarities(text, root)
        if not said:
            continue
        found = _polarities(base, root)
        if not found or not said <= found:
            return False
    return True


_HELLO = (
    r"^\s*(?:hi|hello|hey|namaste|namaskaram|good (?:morning|afternoon|evening))\b"
    r"[\s,!.]*(?:there)?[\s,!.]*$"
)
_HELP = (
    r"\b(?:what can you do|how can you help|what do you do|who are you|help me$|^help$"
    r"|how (?:do|should) i use you)\b"
)
_THANKS = (
    r"^\s*(?:thanks|thank you|thank u|ok(?:ay)?|got it|great|super|fine)\b[\s,!.]*"
    r"(?:thanks|thank you)?[\s,!.]*$"
)
_SMALL_TALK: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(_HELLO, re.IGNORECASE),
        "Hello! Ask me about the orders, circulars and files you have access to — for example "
        '"is G.O.Ms.No.31 of 2025 still in force?" or "has a spouse-grounds transfer been '
        'decided before?". On an open file, use the AI button there to ask about that file.',
    ),
    (
        re.compile(_HELP, re.IGNORECASE),
        "I answer from the records you are allowed to see, and every statement links to the order "
        "or note it comes from. I can:\n"
        "- find the orders, circulars and rules on a subject, and say whether they are still in "
        "force;\n"
        "- find how similar matters were decided before in other files;\n"
        "- explain what an order says, and flag possible conflicts between records.\n"
        "On an open file I can also summarise it, tell you where it is and what is pending, check "
        "a note before you send it, and prepare a draft for approval. I only draft — you approve "
        "and sign.",
    ),
    (
        re.compile(_THANKS, re.IGNORECASE),
        "You're welcome. Ask me anything else about your records or files.",
    ),
)


_SENTENCE = re.compile(r"(?<=[.;:])\s+|\n+")


def closest_extracts(
    question: str, docs: Sequence[tuple[str, str]], per_doc: int = 2, most: int = 4
) -> list[dict[str, str]]:
    """When no statement could be confirmed but records were found (25 Nov 2026): the sentences
    of those records that share the most words with the question, verbatim, each with its
    record. Nothing is written or paraphrased, so nothing needs checking; records come only
    from the officer's evidence package, re-checked by the caller."""
    want = _content(question)
    if not want:
        return []
    out: list[tuple[int, int, dict[str, str]]] = []
    for rank, (cid, text) in enumerate(docs):
        best: list[tuple[int, str]] = []
        for raw in _SENTENCE.split(text or ""):
            s = " ".join(raw.split())
            if not 40 <= len(s) <= 400:
                continue
            hit = len(want & _content(s))
            if hit >= 2:
                best.append((hit, s))
        best.sort(key=lambda x: -x[0])
        for hit, s in best[:per_doc]:
            out.append((hit, -rank, {"canonical_id": cid, "quote": s}))
    out.sort(key=lambda x: (-x[0], -x[1]))
    return [x[2] for x in out[:most]]


def small_talk(message: str) -> str | None:
    """A fixed reply for greetings, thanks and "what can you do" (ADR-0067 addendum 2): no
    retrieval, no model, nothing from any record. None for every other message."""
    msg = message.strip()
    if len(msg) > 60:
        return None
    for rx, reply in _SMALL_TALK:
        if rx.search(msg):
            return reply
    return None


def _clean_heading(h: Any) -> str | None:
    if not isinstance(h, str):
        return None
    out = " ".join(str(h).split()).strip(" :.-")
    if not out or len(out) > 60 or _NUM.search(out):
        return None  # a heading names a theme; facts stay in the checked statements
    return out


def _clean_lead(lead: Any, uses: Any, texts: Sequence[str]) -> tuple[str, tuple[int, ...]] | None:
    if not isinstance(lead, str) or not isinstance(uses, list):
        return None
    lead = " ".join(lead.split())
    idx = tuple(dict.fromkeys(i for i in uses if isinstance(i, int) and 1 <= i <= len(texts)))
    if not lead or len(lead) > 300 or not idx:
        return None
    base = " ".join(texts[i - 1] for i in idx)
    compact = re.sub(r"\s+", "", base)
    if any(n not in compact for n in _NUM.findall(lead)):
        return None  # a number, date or order the named statements do not carry
    words = _content(lead)
    if words and len(words & _content(base)) / len(words) < 0.6:
        return None  # mostly its own words: not a summary of the statements
    if not claims_supported(lead, base):
        return None  # says something happened (or did not) that the statements do not say
    return lead, idx


def compose_answer(
    llm: LLMClient | None, question: str, statements: Sequence[dict[str, Any]]
) -> dict[str, Any] | None:
    """{"lead": str | None, "lead_uses": [n], "sections": [{"heading": str | None, "items": [n]}]}
    over statement numbers 1..N (the order shown), or None (show the answer as it is)."""
    texts = [str(s.get("text", "")) for s in statements]
    if llm is None or len(texts) < 2:
        return None  # one statement is already a direct answer
    listing = "\n".join(f"S{i}. {t}" for i, t in enumerate(texts, 1))
    try:
        out = llm.generate_json(
            prompt_id=COMPOSE_PROMPT,
            system=load_prompt(COMPOSE_PROMPT),
            user=f"<question>{question[:500]}</question>\n<statements>\n{listing}\n</statements>",
            schema={
                "type": "object",
                "properties": {
                    "lead": {"type": "string"},
                    "lead_uses": {"type": "array", "items": {"type": "integer"}},
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "heading": {"type": "string"},
                                "items": {"type": "array", "items": {"type": "integer"}},
                            },
                            "required": ["items"],
                        },
                    },
                },
                "required": ["lead", "lead_uses", "sections"],
            },
        )
    except LLMError as e:
        log.info("compose: model unavailable (%s)", type(e).__name__)
        return None
    if not isinstance(out, dict):
        return None
    lead = _clean_lead(out.get("lead"), out.get("lead_uses"), texts)
    seen: set[int] = set()
    sections: list[dict[str, Any]] = []
    for sec in out.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        items: list[int] = []
        for i in sec.get("items") or []:
            if isinstance(i, int) and 1 <= i <= len(texts) and i not in seen:
                seen.add(i)
                items.append(i)
        if items:
            sections.append({"heading": _clean_heading(sec.get("heading")), "items": items})
    rest = [i for i in range(1, len(texts) + 1) if i not in seen]
    if rest:  # every checked statement is shown, whatever the model left out
        sections.append({"heading": None, "items": rest})
    if lead is None and all(s["heading"] is None for s in sections):
        return None
    return {
        "lead": lead[0] if lead else None,
        "lead_uses": list(lead[1]) if lead else [],
        "sections": sections,
    }


SUMMARY_PROMPT = "file_summary.v4"
# the parts of a full file summary, in reading order (headings are fixed words, never model text)
SUMMARY_SECTIONS = ("about", "history", "decision", "pending")
# "You approved …": the asking officer is never made the author of a note (the post that signed
# it may have been held by someone else); notes are attributed to their post
_YOU_AUTHOR = re.compile(
    r"\byou(?:\s+(?:had|have|then))?\s+(?:approved|agreed|directed|ordered|signed|recommended|"
    r"proposed|submitted|decided|sanctioned|rejected|returned|forwarded|instructed|noted|wrote)\b",
    re.IGNORECASE,
)
FACTS_NO = 0  # the e-Office record lines are cited as "note 0"


def _dmy(v: Any) -> str:
    """dd-mm-yyyy, the way officers write dates; '' when there is none."""
    if v is None:
        return ""
    if isinstance(v, str):
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else v
    return f"{v.day:02d}-{v.month:02d}-{v.year}"


def record_lines(fctx: FileContext, user_id: str, last_direction: Any | None) -> list[str]:
    """What e-Office itself records about the file, in words (ADR-0067 addendum 2): its state,
    who holds it now and whether that is the asking officer, the last direction in the notes the
    officer may read, and the pages placed on it. Deterministic; the summary cites it as note 0,
    so an action question is answered from the records, never from the model's guess."""
    out = [
        f"This file is about {fctx.subject.rstrip('.')}.",
        f"The file is {fctx.state} in e-Office.",
    ]
    if fctx.movements:
        m = fctx.movements[-1]
        out.append(
            f"It is currently with the {m.to_post or m.to_user}, sent by the "
            f"{m.from_post or m.from_user} on {_dmy(m.sent_at)}."
        )
        out.append(
            "The file is with you now." if m.to_user == user_id else "The file is not with you now."
        )
        if m.due_on:
            out.append(f"It is due on {_dmy(m.due_on)}.")
    else:
        out.append("The file has not been moved since it was created.")
    if last_direction is not None:
        out.append(
            f"The last direction in the notes is Note #{last_direction.note_no} by the "
            f"{last_direction.post or 'post not stated'} on {_dmy(last_direction.signed_at)}."
        )
    else:
        out.append("No direction is recorded in the notes available to you.")
    if fctx.pages:
        titles = "; ".join(p.title for p in fctx.pages[-6:])
        out.append(f"Correspondence placed on the file: {titles}.")
    else:
        out.append("No correspondence page is placed on the file.")
    return out


MAX_SUMMARY_INPUT = 12_000  # characters of note text sent; the latest notes are kept


def holder_contradicts(text: str, record: str | bool) -> bool:
    """Whether the sentence gets wrong who holds the file, against the e-Office record."""
    if not isinstance(record, str):
        return False
    with_you = "The file is with you now." in record
    low = text.lower()
    if "with you" not in low:
        return False
    says_not = bool(re.search(r"\b(?:not|isn't|no longer)\b[^.]{0,30}\bwith you\b", low))
    return with_you == says_not


def summarise_file(
    llm: LLMClient | None,
    request: str,
    notes: Sequence[dict[str, Any]],
    facts: Sequence[str] = (),
) -> dict[str, Any] | None:
    """A written summary of the file's notes (ADR-0067 addendum): {"lead", "lead_notes",
    "points": [{"text", "notes"}]}, or None (the notes are shown as they are).

    Input: only notes the officer may read (the route filters them, as for File so far). Every
    sentence is gated against the notes it names: numbers, dates and references must occur in
    them, and most of its words must come from them (or the post / date lines). A sentence that
    fails is dropped; at least one point must survive."""
    usable = [n for n in notes if n.get("text") and isinstance(n.get("note_no"), int)]
    if llm is None or not usable:
        return None
    blocks: list[str] = []
    size = 0
    for n in reversed(usable):  # newest first, so the last direction is always included
        head = (
            f"N{n['note_no']} · {n.get('post') or 'post not stated'} · {_dmy(n.get('signed_at'))}"
        )
        b = f"{head}\n{n['text']}"
        if size + len(b) > MAX_SUMMARY_INPUT and blocks:
            break
        blocks.append(b)
        size += len(b)
    sent = {int(b.split(" ", 1)[0][1:]) for b in blocks}
    by_no = {
        n["note_no"]: f"{n.get('post') or ''} {n.get('signed_at') or ''} {n['text']}"
        for n in usable
        if n["note_no"] in sent
    }
    record = ""
    if facts:
        by_no[FACTS_NO] = " ".join(facts)
        record = f"<record>\nN{FACTS_NO} · e-Office record\n" + "\n".join(facts) + "\n</record>\n"
    try:
        out = llm.generate_json(
            prompt_id=SUMMARY_PROMPT,
            system=load_prompt(SUMMARY_PROMPT),
            user=f"<request>{request[:300]}</request>\n{record}<notes>\n"
            + "\n\n".join(reversed(blocks))
            + "\n</notes>",
            schema={
                "type": "object",
                "properties": {
                    "lead": {"type": "string"},
                    "lead_notes": {"type": "array", "items": {"type": "integer"}},
                    "points": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "notes": {"type": "array", "items": {"type": "integer"}},
                                "section": {"type": "string", "enum": list(SUMMARY_SECTIONS)},
                            },
                            "required": ["text", "notes"],
                        },
                    },
                },
                "required": ["lead", "lead_notes", "points"],
            },
        )
    except LLMError as e:
        log.info("file summary: model unavailable (%s)", type(e).__name__)
        return None
    if not isinstance(out, dict):
        return None

    def gate(text: Any, cites: Any, longest: int) -> tuple[str, list[int]] | None:
        if not isinstance(text, str) or not isinstance(cites, list):
            return None
        text = " ".join(text.split())
        nos = [i for i in dict.fromkeys(cites) if isinstance(i, int) and i in by_no]
        if not text or len(text) > longest or not nos:
            return None
        base = " ".join(by_no[i] for i in nos)
        dates = " ".join(
            re.sub(r"(\d{4})-(\d{2})-(\d{2})", r"\3-\2-\1 \3/\2/\1 \3.\2.\1", base).split()
        )
        compact = re.sub(r"\s+", "", base + " " + dates)
        if any(x not in compact for x in _NUM.findall(text)):
            return None
        words = _content(text)
        if words and len(words & _content(base)) / len(words) < 0.5:
            return None
        if not claims_supported(text, base):
            return None  # approved / issued / closed ... that the cited records do not say
        if _YOU_AUTHOR.search(text):
            return None  # the officer asking is not the author of a note
        if facts and holder_contradicts(text, FACTS_NO in by_no and by_no[FACTS_NO]):
            return None  # "with you" when e-Office says it is not, or the other way round
        return text, nos

    points = [
        {"text": g[0], "notes": g[1]}
        | ({"section": p["section"]} if p.get("section") in SUMMARY_SECTIONS else {})
        for p in (out.get("points") or [])[:10]
        if isinstance(p, dict) and (g := gate(p.get("text"), p.get("notes"), 400))
    ]
    lead = gate(out.get("lead"), out.get("lead_notes"), 400)
    if not points and not lead:
        return None  # nothing passed the checks: the notes are shown as they are
    return {
        "lead": lead[0] if lead else None,
        "lead_notes": lead[1] if lead else [],
        "points": points,
    }


DRAFT_INPUTS_PROMPT = "draft_inputs.v1"
DRAFT_FIELDS = ("subject", "request", "facts", "proposal", "signatory", "addressees", "copy_to")
_FIELD_MAX = {"subject": 500, "signatory": 200}


_APPROVED = re.compile(
    r"\b(?:approved|agreed|sanctioned|accepted"
    r"|orders? may (?:be )?issue[sd]?|issue (?:the )?orders?)\b",
    re.IGNORECASE,
)


def choose_format(
    notes: Sequence[dict[str, Any]], last_direction: int | None, state: str, note: bool = False
) -> tuple[str, str]:
    """Which draft a plain "prepare a draft" means on this file (25 Nov 2026), decided from the
    record, never by the model: once the last direction approves, the order that carries it out
    (G.O.Rt.); before that, the note that puts the proposal up. Returns (format id, why)."""
    last = next((n for n in notes if n.get("note_no") == last_direction), None)
    closed = (
        " The file is closed in e-Office; it would have to be reopened first."
        if state == "closed"
        else ""
    )
    if last and _APPROVED.search(str(last.get("text") or "")):
        who = last.get("post") or "the competent authority"
        when = _dmy(last.get("signed_at"))
        if note:  # a note after approval: the one that puts the draft orders up (DFA)
            return (
                "note_dfa",
                f"The {who} approved the proposal in Note #{last['note_no']}"
                + (f" on {when}" if when else "")
                + ", so this note puts up the draft orders for approval."
                + closed,
            )
        return (
            "go_rt",
            f"The {who} approved the proposal in Note #{last['note_no']}"
            + (f" on {when}" if when else "")
            + ", so this is the draft order that carries it out."
            + closed,
        )
    return (
        "note_proposal",
        "No approval is recorded in the notes you can see, so this is a note putting the proposal"
        " up for orders." + closed,
    )


def draft_inputs(
    llm: LLMClient | None,
    request: str,
    fmt: dict[str, Any],
    notes: Sequence[dict[str, Any]],
) -> dict[str, Any] | None:
    """The inputs of a draft filled from the file's notes (ADR-0067 addendum 4), so the officer
    starts from a filled draft: {"inputs": {field: text}, "sources": {field: [note numbers]}}, or
    None. Only the format's own inputs; each one is gated like a summary sentence (numbers, dates
    and references must occur in the notes it names; most of its words must come from them). A
    field that fails stays empty and is shown to the officer as a gap."""
    usable = [n for n in notes if n.get("text") and isinstance(n.get("note_no"), int)]
    wanted = [f for f in fmt.get("inputs", ()) if f in DRAFT_FIELDS]
    if llm is None or not usable or not wanted:
        return None
    by_no = {
        n["note_no"]: f"{n.get('post') or ''} {n.get('signed_at') or ''} {n['text']}"
        for n in usable
    }

    def head(n: dict[str, Any]) -> str:
        return (
            f"N{n['note_no']} · {n.get('post') or 'post not stated'} · {_dmy(n.get('signed_at'))}"
        )

    listing = "\n\n".join(f"{head(n)}\n{n['text']}" for n in usable)[:MAX_SUMMARY_INPUT]
    try:
        out = llm.generate_json(
            prompt_id=DRAFT_INPUTS_PROMPT,
            system=load_prompt(DRAFT_INPUTS_PROMPT),
            user=(
                f"<request>{request[:300]}</request>\n"
                f"<format>{fmt.get('title', '')} — used when: {fmt.get('use_when', '')}; "
                f"inputs needed: {', '.join(wanted)}</format>\n<notes>\n{listing}\n</notes>"
            ),
            schema={
                "type": "object",
                "properties": {
                    "inputs": {
                        "type": "object",
                        "properties": {f: {"type": "string"} for f in DRAFT_FIELDS},
                    },
                    "sources": {
                        "type": "object",
                        "properties": {
                            f: {"type": "array", "items": {"type": "integer"}} for f in DRAFT_FIELDS
                        },
                    },
                },
                "required": ["inputs", "sources"],
            },
        )
    except LLMError as e:
        log.info("draft inputs: model unavailable (%s)", type(e).__name__)
        return None
    if not isinstance(out, dict):
        return None
    got = out.get("inputs") if isinstance(out.get("inputs"), dict) else {}
    src = out.get("sources") if isinstance(out.get("sources"), dict) else {}
    iso = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
    inputs: dict[str, str] = {}
    sources: dict[str, list[int]] = {}
    for f in wanted:
        text = got.get(f) if isinstance(got, dict) else None
        cites = src.get(f) if isinstance(src, dict) else None
        if not isinstance(text, str) or not text.strip() or not isinstance(cites, list):
            continue
        text = "\n".join(" ".join(ln.split()) for ln in text.strip().splitlines() if ln.strip())
        nos = [i for i in dict.fromkeys(cites) if isinstance(i, int) and i in by_no]
        if not nos or len(text) > _FIELD_MAX.get(f, 4000):
            continue
        base = " ".join(by_no[i] for i in nos)
        compact = re.sub(r"\s+", "", base + " " + iso.sub(r"\3-\2-\1 \3/\2/\1 \3.\2.\1", base))
        if any(x not in compact for x in _NUM.findall(text)):
            continue  # a number, date or reference the notes it names do not carry
        words = _content(text)
        if words and len(words & _content(base)) / len(words) < 0.5:
            continue  # mostly its own words
        inputs[f], sources[f] = text, nos
    return {"inputs": inputs, "sources": sources} if inputs else None
