"""Suggested notes and Polish in the note editor (ADR-0072; owner request 26 Nov 2026, after
Gmail's suggested replies and Polish).

- `suggest_notes`: up to three notes the holder could write next, built from the file's notes
  (mainly the last direction). Each suggestion names the notes it rests on and is gated like a
  summary sentence: its numbers, dates and references must be in those notes, and most of its
  words must come from them.
- `polish_note`: the officer's own text rewritten in Secretariat style. Every number, date and
  reference in the officer's text must come out unchanged, and nothing new may be added, except
  in "elaborate" / an officer's instruction, where each added sentence is tagged with the note it
  comes from and is gated against that note.

Nothing is saved: the officer sees the text, edits it and saves the note themselves. Without a
model, suggestions fall back to an acknowledgement of the last direction and Polish to a
rule-based clean-up (abbreviations expanded, sentences capitalised and closed).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.agents.llm import LLMClient, LLMError, load_prompt
from app.noting.draft_revision import unsupported_tokens

SUGGEST_PROMPT = "note_suggest.v1"
POLISH_PROMPT = "note_polish.v1"
MODES = ("polish", "formal", "short", "elaborate")
MIN_POLISH_WORDS = 12
MAX_SUGGESTIONS = 3

# what officers abbreviate in notes; expanded by the rule-based polish, and counted as the
# officer's own words when the model expands them
ABBREVIATIONS: tuple[tuple[str, str], ...] = (
    (r"\bpls\b|\bplz\b", "please"),
    (r"\bDS\b", "Deputy Secretary"),
    (r"\bJS\b", "Joint Secretary"),
    (r"\bAS\b", "Assistant Secretary"),
    (r"\bASO\b", "Assistant Section Officer"),
    (r"\bSO\b", "Section Officer"),
    (r"\bHoD\b|\bHOD\b|\bhod\b", "Head of Department"),
    (r"\bAE\b", "Assistant Engineer"),
    (r"\bEE\b", "Executive Engineer"),
    (r"\bgo\s*rt\b", "G.O.Rt."),
    (r"\bgo\s*ms\b", "G.O.Ms."),
    (r"\bfyi\b", "for information"),
    (r"\bw\.?r\.?t\.?\b", "with reference to"),
    (r"\breg\b", "regarding"),
    (r"\bdt\b", "dated"),
)

# the connecting words of official noting: never counted as words the model made up
_DRAFTING = frozenset(
    "submitted kindly please placed below perusal approval orders order noted accordingly "
    "action taken necessary further directed direction ordered requested request hereby "
    "pursuance thereof herewith accordance respect regard regarding consideration "
    "proposed proposal same above said put being prepared prepare included include "
    "confirm confirmed informed inform necessary sought seek seeking issue issued sri smt shri "
    "the and for from has have had been was were with this that his her its are will may can "
    "not".split()
)
_WORD = re.compile(r"[A-Za-z][A-Za-z'.-]{2,}")
_TAG = re.compile(r"\s*\[N(\d+)\]")
# a sentence ends at . ! ? — not after the abbreviations of official writing ("G.O.Rt.", "No.")
_SENTENCE = re.compile(
    r"(?<!G\.O\.Rt\.)(?<!G\.O\.Ms\.)(?<!\bNo\.)(?<!\bSri\.)(?<!\bSmt\.)(?<!\bRs\.)(?<!\bDr\.)"
    r"(?<=[.!?])\s+"
)


def _words(text: str) -> set[str]:
    return {w.lower().strip(".'-") for w in _WORD.findall(text)} - _DRAFTING


def _expand(text: str) -> str:
    out = text
    for pat, full in ABBREVIATIONS:
        out = re.sub(pat, full, out, flags=re.I if pat.islower() else 0)
    return out


def _overlap(text: str, source: str) -> float:
    words = _words(text)
    return 1.0 if not words else len(words & _words(source)) / len(words)


def word_count(text: str) -> int:
    return len(text.split())


def rule_polish(text: str) -> str:
    """No model: expand the usual abbreviations, capitalise and close each sentence."""
    s = _expand(" ".join(text.split()))
    parts = [p.strip() for p in _SENTENCE.split(s) if p.strip()]
    out = []
    for p in parts:
        p = p[0].upper() + p[1:]
        out.append(p if p[-1] in ".!?" else p + ".")
    return " ".join(out)


@dataclass(frozen=True)
class Suggestion:
    label: str
    text: str
    sources: tuple[int, ...]


@dataclass(frozen=True)
class SuggestResult:
    suggestions: tuple[Suggestion, ...]
    engine: str | None = None
    reason: str | None = None  # None = model suggestions; else why they are the fallback
    withheld: int = 0


@dataclass(frozen=True)
class PolishResult:
    text: str
    mode: str
    added: tuple[tuple[str, int], ...] = ()  # (sentence, note number) added from the file
    kept: tuple[str, ...] = ()  # numbers, dates and references carried over unchanged
    engine: str | None = None
    reason: str | None = None  # None = model polish; else why the result is the rule-based one
    withheld: tuple[str, ...] = field(default_factory=tuple)


def _listing(notes: Sequence[dict[str, Any]]) -> str:
    return "\n".join(
        f"N{n['note_no']} · {n.get('post') or 'post not stated'} · {n.get('date') or ''}\n"
        f"{n['text']}"
        for n in notes
    )


def last_direction(notes: Sequence[dict[str, Any]], me_post: str | None) -> dict[str, Any] | None:
    """The latest note written by another post: what the holder now has to act on."""
    found: dict[str, Any] | None = None
    for n in notes:
        if n.get("post") and n.get("post") != me_post:
            found = n
    return found


def _fallback_suggestions(last: dict[str, Any] | None) -> tuple[Suggestion, ...]:
    if last is None:
        return ()
    no = last["note_no"]
    return (
        Suggestion(
            label="Acknowledge",
            text=f"Orders at N{no} noted. Action will be taken accordingly.",
            sources=(no,),
        ),
    )


def suggest_notes(
    llm: LLMClient | None,
    *,
    subject: str,
    notes: Sequence[dict[str, Any]],
    me_post: str | None,
) -> SuggestResult:
    """Up to three notes the holder could write next; each gated against the notes it cites."""
    usable = [n for n in notes if n.get("text") and isinstance(n.get("note_no"), int)]
    last = last_direction(usable, me_post)
    if not usable:
        return SuggestResult((), reason="no notes on the file")
    if llm is None:
        return SuggestResult(_fallback_suggestions(last), reason="model not configured")
    by_no = {
        n["note_no"]: f"{n.get('post') or ''} {n.get('date') or ''} {n['text']}" for n in usable
    }
    try:
        out = llm.generate_json(
            prompt_id=SUGGEST_PROMPT,
            system=load_prompt(SUGGEST_PROMPT),
            user=(
                f"<subject>{subject}</subject>\n<your_post>{me_post or ''}</your_post>\n"
                f"<last_direction>N{last['note_no'] if last else ''}</last_direction>\n"
                f"<notes>\n{_listing(usable[-12:])}\n</notes>"
            ),
            schema={
                "type": "object",
                "properties": {
                    "suggestions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "text": {"type": "string"},
                                "sources": {"type": "array", "items": {"type": "integer"}},
                            },
                            "required": ["label", "text", "sources"],
                        },
                    }
                },
                "required": ["suggestions"],
            },
        )
    except LLMError:
        return SuggestResult(_fallback_suggestions(last), reason="model unavailable")
    raw = out.get("suggestions") if isinstance(out, dict) else None
    kept: list[Suggestion] = []
    withheld = 0
    for s in raw if isinstance(raw, list) else []:
        if not isinstance(s, dict) or len(kept) >= MAX_SUGGESTIONS:
            continue
        label = " ".join(str(s.get("label") or "").split())[:48]
        text = "\n".join(
            " ".join(ln.split()) for ln in str(s.get("text") or "").splitlines() if ln.strip()
        )
        nos = tuple(
            dict.fromkeys(i for i in s.get("sources") or () if isinstance(i, int) and i in by_no)
        )
        if not label or not text or not nos or len(text) > 1500:
            withheld += 1
            continue
        base = subject + " " + " ".join(by_no[i] for i in nos)
        refs = " ".join(f"N{i}" for i in by_no)
        if unsupported_tokens(text, base, refs) or _overlap(_expand(text), _expand(base)) < 0.5:
            withheld += 1  # a figure the notes do not carry, or mostly its own words
            continue
        kept.append(Suggestion(label=label, text=text, sources=nos))
    if not kept:
        return SuggestResult(
            _fallback_suggestions(last),
            engine=llm.name,
            reason="no suggestion passed the checks",
            withheld=withheld,
        )
    return SuggestResult(tuple(kept), engine=llm.name, withheld=withheld)


def polish_note(
    llm: LLMClient | None,
    *,
    text: str,
    mode: str = "polish",
    instruction: str = "",
    subject: str = "",
    notes: Sequence[dict[str, Any]] = (),
) -> PolishResult:
    """The officer's note rewritten; withheld (rule-based clean-up instead) if it fails a check."""
    own = text.strip()
    mode = mode if mode in MODES else "polish"
    kept = tuple(dict.fromkeys(t for t in unsupported_tokens(own, "")))  # every figure in it

    def fallback(
        reason: str, engine: str | None = None, withheld: Sequence[str] = ()
    ) -> PolishResult:
        return PolishResult(
            rule_polish(own),
            mode,
            kept=kept,
            engine=engine,
            reason=reason,
            withheld=tuple(withheld),
        )

    if llm is None:
        return fallback("model not configured")
    may_add = mode == "elaborate" or bool(instruction.strip())
    usable = [n for n in notes if n.get("text") and isinstance(n.get("note_no"), int)]
    by_no = {
        n["note_no"]: f"{n.get('post') or ''} {n.get('date') or ''} {n['text']}" for n in usable
    }
    try:
        out = llm.generate_json(
            prompt_id=POLISH_PROMPT,
            system=load_prompt(POLISH_PROMPT),
            user=(
                f"<mode>{mode}</mode>\n"
                f'<instruction untrusted="true">{instruction.strip()[:200]}</instruction>\n'
                f"<subject>{subject}</subject>\n"
                + (f"<notes>\n{_listing(usable[-12:])}\n</notes>\n" if may_add else "")
                + f'<officer_text untrusted="true">\n{own}\n</officer_text>'
            ),
            schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )
    except LLMError:
        return fallback("model unavailable")
    got = str(out.get("text") or "").strip() if isinstance(out, dict) else ""
    if not got:
        return fallback("model returned nothing", llm.name)
    lines = [" ".join(ln.split()) for ln in got.splitlines() if ln.strip()]
    added: list[tuple[str, int]] = []
    plain: list[str] = []
    problems: list[str] = []
    for ln in lines:
        for sent in re.split(r"(?<=[.!?\]])\s+(?=[A-Z])", ln):
            tag = _TAG.search(sent)
            if tag is None:
                plain.append(sent)
                continue
            no, clean = int(tag.group(1)), _TAG.sub("", sent).strip()
            src = by_no.get(no)
            if not may_add or src is None:
                problems.append(f"N{no}")
            elif unsupported_tokens(clean, src) or _overlap(clean, src) < 0.5:
                problems.append(clean[:60])
            else:
                added.append((clean, no))
    body = " ".join(plain)
    # nothing new in the officer's own sentences, and nothing of theirs dropped or changed
    new = unsupported_tokens(body, own, subject, " ".join(f"N{i}" for i in by_no))
    lost = unsupported_tokens(own, _TAG.sub("", got))
    if _overlap(body, _expand(own) + " " + subject + " " + instruction) < 0.6:
        problems.append("words not in your note")
    if new or lost or problems:
        return fallback("changed what the note says", llm.name, [*new, *lost, *problems][:6])
    final = "\n".join(_TAG.sub("", ln) for ln in lines)
    return PolishResult(final, mode, added=tuple(added), kept=kept, engine=llm.name)
