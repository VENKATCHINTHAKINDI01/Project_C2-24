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

log = logging.getLogger(__name__)

INTENT_PROMPT = "intent_route.v3"
COMPOSE_PROMPT = "answer_compose.v1"

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


SUMMARY_PROMPT = "file_summary.v2"
MAX_SUMMARY_INPUT = 12_000  # characters of note text sent; the latest notes are kept


def summarise_file(
    llm: LLMClient | None, request: str, notes: Sequence[dict[str, Any]]
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
            f"N{n['note_no']} · {n.get('post') or 'post not stated'} · {n.get('signed_at') or ''}"
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
    try:
        out = llm.generate_json(
            prompt_id=SUMMARY_PROMPT,
            system=load_prompt(SUMMARY_PROMPT),
            user=f"<request>{request[:300]}</request>\n<notes>\n"
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
        return text, nos

    points = [
        {"text": g[0], "notes": g[1]}
        for p in (out.get("points") or [])[:6]
        if isinstance(p, dict) and (g := gate(p.get("text"), p.get("notes"), 400))
    ]
    if not points:
        return None
    lead = gate(out.get("lead"), out.get("lead_notes"), 400)
    return {
        "lead": lead[0] if lead else None,
        "lead_notes": lead[1] if lead else [],
        "points": points,
    }


DRAFT_INPUTS_PROMPT = "draft_inputs.v1"
DRAFT_FIELDS = ("subject", "request", "facts", "proposal", "signatory", "addressees", "copy_to")
_FIELD_MAX = {"subject": 500, "signatory": 200}


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
            f"N{n['note_no']} · {n.get('post') or 'post not stated'} · {n.get('signed_at') or ''}"
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
