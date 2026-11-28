"""Suggested notes and Polish in the note editor (ADR-0072; owner request 26 Nov 2026, after
Gmail's suggested replies and Polish).

- `suggest_notes`: up to three notes the holder could write next, built from the file's notes
  (mainly the last direction). Each suggestion names the notes it rests on and is gated like a
  summary sentence: its numbers, dates and references must be in those notes, and most of its
  words must come from them.
- `polish_note`: the officer's own text rewritten in Secretariat style. Every number, date and
  reference in the officer's text must come out unchanged, and nothing new may be added, except
  in "elaborate" / an officer's instruction, where each added sentence names the note it comes
  from and is gated against that note.

Both stream (ADR-0033 pattern): each suggestion / sentence is passed to `emit` as soon as the
model has written it AND it passed its own check — never the model's unchecked words. The final
result is checked as a whole and replaces what was streamed.

Nothing is saved: the officer sees the text, edits it and saves the note themselves. Without a
model, suggestions fall back to an acknowledgement of the last direction and Polish to a
rule-based clean-up (abbreviations expanded, sentences capitalised and closed).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher, get_close_matches
from typing import Any

from app.agents.llm import LLMClient, LLMError, load_prompt, stream_json
from app.agents.streaming import StatementStream
from app.noting.draft_revision import unsupported_tokens

SUGGEST_PROMPT = "note_suggest.v1"
POLISH_PROMPT = "note_polish.v2"
MODES = ("polish", "formal", "short", "elaborate")
MIN_POLISH_WORDS = 12
MAX_SUGGESTIONS = 3
POLISH_MIN_OWN_WORDS = 0.5  # share of a rewritten sentence's words the officer or the file used

Emit = Callable[[dict[str, Any]], None]

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

# the connecting words of official noting and of English: never counted as made-up words
_DRAFTING = frozenset(
    "submitted kindly please placed below perusal approval orders order noted accordingly "
    "action taken necessary further directed direction directions ordered requested request "
    "hereby pursuance thereof herewith accordance respect regard regarding consideration "
    "proposed proposal same above said put being prepared prepare included include "
    "confirm confirmed informed inform sought seek seeking issue issued sri smt shri "
    "the and for from has have had been was were with this that his her its are will may can "
    "not also which who whom whose into upon under over after before about along per "
    "accordingly therefore however further furnished examined verified verification "
    "communicated received reported forwarded enclosed reference referred mentioned "
    "required requirement necessary needful early possible concerned matter case all my our".split()
)

# misspellings of notes typed in a hurry (owner report 27 Nov: "I aprove the file aftr cheking al
# the relted fils from myside."); corrected by the rule-based polish, case kept
MISSPELT: tuple[tuple[str, str], ...] = (
    (r"\baprove", "approve"),
    (r"\baproval\b", "approval"),
    (r"\baftr\b", "after"),
    (r"\bcheking\b", "checking"),
    (r"\bal(?= (?:the|of|my|our|these|those)\b)", "all"),
    (r"\brelted\b", "related"),
    (r"\bfils\b", "files"),
    (r"\bmyside\b", "my side"),
    (r"\brecieved\b", "received"),
    (r"\brecieve\b", "receive"),
    (r"\bpropsal\b", "proposal"),
    (r"\bsubmited\b", "submitted"),
    (r"\bverfied\b", "verified"),
    (r"\bimmediatly\b", "immediately"),
    (r"\bnecesary\b", "necessary"),
    (r"\bseperate\b", "separate"),
    (r"\bpls\b", "please"),
)
# words of official noting the rule-based polish may correct a lowercase misspelling to
_LEXICON = sorted(
    _DRAFTING
    | set(
        "approve approved approving check checked checking related relevant file files side office "
        "officer officers section department government proposal proposals pending immediate "
        "immediately recommend recommended recommendation forward examine circular memo "
        "representation transfer vacancy available sanction sanctioned budget amount release "
        "released permission complete completed report reports details detailed instructions "
        "letter letters enclosure enclosures meeting meetings agreed agree concurrence".split()
    )
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


def _subsequence(short: str, long: str) -> bool:
    it = iter(long)
    return all(c in it for c in short)


def _near(word: str, pool: set[str]) -> bool:
    """The word is the officer's own, allowing for their typing: "aprove" / "approve",
    "cheking" / "checking", "fils" / "files", "myside" / "side". Five letters or more for a
    spelling match, so a short name is never taken for another."""
    if word in pool:
        return True
    for own in pool:
        a, b = sorted((own, word), key=len)
        if len(a) < 3 or len(a) < 0.5 * len(b):
            continue
        if a in b or (len(b) >= 4 and _subsequence(a, b) and len(a) >= 0.6 * len(b)):
            return True
        if len(b) >= 5 and SequenceMatcher(None, own, word).ratio() >= 0.8:
            return True
    return False


def _overlap(text: str, source: str) -> float:
    words = _words(text)
    if not words:
        return 1.0
    pool = _words(source)
    return sum(1 for w in words if _near(w, pool)) / len(words)


def _respell(text: str) -> str:
    out = text
    for pat, right in MISSPELT:

        def keep_case(m: re.Match[str], r: str = right) -> str:
            return r[0].upper() + r[1:] if m.group(0)[0].isupper() else r

        out = re.sub(pat, keep_case, out, flags=re.I)

    def fix(m: re.Match[str]) -> str:
        w = m.group(0)
        if len(w) < 5 or w in _LEXICON:
            return w
        hit = get_close_matches(w, _LEXICON, n=1, cutoff=0.86)
        return hit[0] if hit else w

    return re.sub(r"\b[a-z]{5,}\b", fix, out)


def word_count(text: str) -> int:
    return len(text.split())


def rule_polish(text: str) -> str:
    """No model: expand the usual abbreviations, correct common misspellings (lowercase words
    only, never a name), capitalise and close each sentence; the
    officer's paragraphs are kept."""
    paras = []
    for para in text.strip().split("\n"):
        s = _respell(_expand(" ".join(para.split())))
        if not s:
            continue
        out = []
        for p in (x.strip() for x in _SENTENCE.split(s) if x.strip()):
            p = p[0].upper() + p[1:]
            out.append(p if p[-1] in ".!?" else p + ".")
        paras.append(" ".join(out))
    return "\n".join(paras)


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


def _by_no(notes: Sequence[dict[str, Any]]) -> dict[int, str]:
    return {
        n["note_no"]: f"{n.get('post') or ''} {n.get('date') or ''} {n['text']}"
        for n in notes
        if n.get("text") and isinstance(n.get("note_no"), int)
    }


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


_SUGGEST_SCHEMA: dict[str, Any] = {
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
}


def suggest_notes(
    llm: LLMClient | None,
    *,
    subject: str,
    notes: Sequence[dict[str, Any]],
    me_post: str | None,
    emit: Emit | None = None,
) -> SuggestResult:
    """Up to three notes the holder could write next; each gated against the notes it cites and
    streamed to `emit` as soon as it passed."""
    usable = [n for n in notes if n.get("text") and isinstance(n.get("note_no"), int)]
    last = last_direction(usable, me_post)
    if not usable:
        return SuggestResult((), reason="no notes on the file")
    if llm is None:
        return SuggestResult(_fallback_suggestions(last), reason="model not configured")
    by_no = _by_no(usable)
    refs = " ".join(f"N{i}" for i in by_no)
    kept: list[Suggestion] = []
    seen = [0]

    def check(s: Any) -> Suggestion | None:
        if not isinstance(s, dict):
            return None
        label = " ".join(str(s.get("label") or "").split())[:48]
        lines = str(s.get("text") or "").splitlines()
        text = "\n".join(" ".join(ln.split()) for ln in lines if ln.strip())
        cited = s.get("sources") or ()
        nos = tuple(dict.fromkeys(i for i in cited if isinstance(i, int) and i in by_no))
        if not label or not text or not nos or len(text) > 1500:
            return None
        base = subject + " " + " ".join(by_no[i] for i in nos)
        if unsupported_tokens(text, base, refs) or _overlap(_expand(text), _expand(base)) < 0.5:
            return None  # a figure the notes do not carry, or mostly its own words
        return Suggestion(label=label, text=text, sources=nos)

    def take(s: Any) -> None:
        seen[0] += 1
        got = check(s)
        if got is None or len(kept) >= MAX_SUGGESTIONS or any(k.text == got.text for k in kept):
            return
        kept.append(got)
        if emit is not None:
            emit({"type": "suggestion", "suggestion": _suggestion_json(got)})

    stream = StatementStream("suggestions")

    def feed(chunk: str) -> None:
        for s in stream.feed(chunk):
            take(s)

    try:
        out = stream_json(
            llm,
            prompt_id=SUGGEST_PROMPT,
            system=load_prompt(SUGGEST_PROMPT),
            user=(
                f"<subject>{subject}</subject>\n<your_post>{me_post or ''}</your_post>\n"
                f"<last_direction>N{last['note_no'] if last else ''}</last_direction>\n"
                f"<notes>\n{_listing(usable[-12:])}\n</notes>"
            ),
            schema=_SUGGEST_SCHEMA,
            on_text=feed if emit else None,
        )
    except LLMError:
        return SuggestResult(_fallback_suggestions(last), reason="model unavailable")
    if emit is None:  # not streamed: check them all now
        raw = out.get("suggestions") if isinstance(out, dict) else None
        for s in raw if isinstance(raw, list) else []:
            take(s)
    withheld = seen[0] - len(kept)
    if not kept:
        return SuggestResult(
            _fallback_suggestions(last),
            engine=llm.name,
            reason="no suggestion passed the checks",
            withheld=withheld,
        )
    return SuggestResult(tuple(kept), engine=llm.name, withheld=withheld)


def _suggestion_json(s: Suggestion) -> dict[str, Any]:
    return {"label": s.label, "text": s.text, "sources": list(s.sources)}


_POLISH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "from_note": {"type": "integer"},
                    "new_paragraph": {"type": "boolean"},
                },
                "required": ["text", "from_note", "new_paragraph"],
            },
        }
    },
    "required": ["sentences"],
}


def polish_note(
    llm: LLMClient | None,
    *,
    text: str,
    mode: str = "polish",
    instruction: str = "",
    subject: str = "",
    notes: Sequence[dict[str, Any]] = (),
    emit: Emit | None = None,
) -> PolishResult:
    """The officer's note rewritten, sentence by sentence; each sentence streamed to `emit` once
    it passed its check. The whole is then checked again (nothing of the officer's dropped);
    anything that fails withholds the model's version and returns the rule-based clean-up."""
    own = text.strip()
    mode = mode if mode in MODES else "polish"
    kept = tuple(dict.fromkeys(unsupported_tokens(own, "")))  # every figure in the note
    by_no = _by_no(notes)
    may_add = mode == "elaborate" or bool(instruction.strip())
    refs = " ".join(f"N{i}" for i in by_no)
    # the words a rewritten sentence may use: the officer's (abbreviations expanded), the
    # subject, the instruction and the file's notes (designations, places as the file has them);
    # figures may only be the officer's own
    vocab = " ".join([_expand(own), subject, instruction, *by_no.values()])

    def fallback(reason: str, engine: str | None = None, why: Sequence[str] = ()) -> PolishResult:
        return PolishResult(
            rule_polish(own), mode, kept=kept, engine=engine, reason=reason, withheld=tuple(why)
        )

    if llm is None:
        return fallback("model not configured")

    shown: list[tuple[str, int, bool]] = []  # (sentence, from note or 0, new paragraph)
    problems: list[str] = []

    def take(s: Any) -> None:
        if not isinstance(s, dict):
            return
        sent = " ".join(_TAG.sub("", str(s.get("text") or "")).split())
        if not sent:
            return
        got_no = s.get("from_note")
        no: int = got_no if isinstance(got_no, int) else 0
        para = bool(s.get("new_paragraph")) and bool(shown)
        if no:
            src = by_no.get(no)
            if not may_add or src is None:
                problems.append(f"N{no}")
                return
            if unsupported_tokens(sent, src) or _overlap(sent, src) < 0.5:
                problems.append(sent[:60])
                return
        else:
            new = unsupported_tokens(sent, own, subject, refs)
            if new:
                problems.extend(new)
                return
            if _overlap(sent, vocab) < POLISH_MIN_OWN_WORDS:
                problems.append(sent[:60])
                return
        shown.append((sent, no, para))
        if emit is not None:
            emit({"type": "sentence", "text": sent, "note_no": no or None, "new_paragraph": para})

    stream = StatementStream("sentences")

    def feed(chunk: str) -> None:
        for s in stream.feed(chunk):
            take(s)

    try:
        out = stream_json(
            llm,
            prompt_id=POLISH_PROMPT,
            system=load_prompt(POLISH_PROMPT),
            user=(
                f"<mode>{mode}</mode>\n"
                f'<instruction untrusted="true">{instruction.strip()[:200]}</instruction>\n'
                f"<subject>{subject}</subject>\n"
                + (f"<notes>\n{_listing(notes[-12:])}\n</notes>\n" if may_add and notes else "")
                + f'<officer_text untrusted="true">\n{own}\n</officer_text>'
            ),
            schema=_POLISH_SCHEMA,
            on_text=feed if emit else None,
        )
    except LLMError:
        return fallback("model unavailable")
    if emit is None:
        raw = out.get("sentences") if isinstance(out, dict) else None
        for s in raw if isinstance(raw, list) else []:
            take(s)
    if not shown:
        reason = "rewrote too much" if problems else "model returned nothing"
        return fallback(reason, llm.name, problems)
    final = ""
    for sent, _, para in shown:
        final += ("\n" if para else " " if final else "") + sent
    lost = unsupported_tokens(own, final)  # nothing of the officer's dropped or changed
    if lost or problems:
        return fallback("changed what the note says", llm.name, [*lost, *problems][:6])
    added = tuple((s, n) for s, n, _ in shown if n)
    return PolishResult(final, mode, added=added, kept=kept, engine=llm.name)
