"""Conflict types B and G (plan §6.2, §6.5): grounded Gemini judgment on pairs of instruments the
officer may see and the note relies on. Deterministic around the model:

- which pairs are asked: two instruments of the note's evidence that no supersession / amendment
  link joins (those are types A / F), at least one of them below a G.O. (circular, memo,
  proceedings); two G.O.s of the same level are not asked yet;
- what the model sees: only excerpts of those two authorised texts (CLAUDE.md §7.1), as data; the
  excerpt of a long order is its head plus the line windows that best match the other text and the
  note (the note itself is not sent);
- whether an answer counts: both quotes must appear word for word in the excerpts it was given
  (citation check, §7.7); otherwise the answer is dropped;
- B or G: from the instruments' hierarchy levels (same level → B; different → G), never the model;
- every flag is advisory, uncertain and needs review (§6.6).
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Iterable, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.agents.llm import LLMClient, LLMError, load_prompt
from app.conflict.deterministic import ConflictFlag, ConflictType

PROMPT_ID = "conflict_contradiction.v2"
GO_LEVEL = 4  # G.O.(Ms) in data/ontology/hierarchy.yaml; lower instruments have higher numbers
EXCERPT_CHARS = 6000  # per document sent to the model
HEAD_CHARS = 500  # title, number, date, subject
WINDOW_CHARS = 400
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["contradiction", "consistent", "insufficient"]},
        "quote_a": {"type": "string"},
        "quote_b": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["verdict", "quote_a", "quote_b", "explanation"],
}


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    canonical_id: str
    level: int | None  # hierarchy level (lower number = higher authority)
    text: str


class JudgmentResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    flags: tuple[ConflictFlag, ...]
    asked: int
    failed: int  # model unavailable / no recorded answer: the check is incomplete


def _words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z]{4,}", text)}


def _terms(text: str) -> set[str]:
    """Words and word pairs ("apply transfer" counts more than "transfer" alone)."""
    ws = [w.lower() for w in re.findall(r"[A-Za-z]{3,}", text)]
    return set(ws) | {f"{x} {y}" for x, y in itertools.pairwise(ws)}


def _spans(text: str, size: int = WINDOW_CHARS) -> list[tuple[int, int]]:
    """Windows of whole lines, about `size` characters, starting every half window so that a
    clause cut by one window is whole in the next (OCR text has no reliable paragraph breaks;
    a very long line is cut)."""
    starts = [0] + [m.end() for m in re.finditer(r"\n", text)]
    spans: list[tuple[int, int]] = []
    nxt = 0
    for i, st in enumerate(starts):
        if st < nxt or st >= len(text):
            continue
        end = st
        for e in starts[i + 1 :]:
            if e - st > size:
                break
            end = e
        if end <= st:  # one line longer than a window
            end = min(len(text), st + size)
        spans.append((st, end if end < len(text) else len(text)))
        nxt = st + max(1, (end - st) // 2)
    if spans and spans[-1][1] < len(text):
        spans.append((spans[-1][1], min(len(text), spans[-1][1] + size)))
    return spans


def excerpt(text: str, focus: str, limit: int = EXCERPT_CHARS, note: str = "") -> str:
    """The head of `text` plus the passages that best match `focus` (the other document), in
    document order. `note` (the officer's note) only breaks ties: it may name the point at
    issue but also carries much unrelated wording. A term counts more the fewer windows of
    `text` contain it, so the clause on the point in question outranks boilerplate."""
    if len(text) <= limit:
        return text
    head = text[:HEAD_CHARS]
    spans = [(a, b) for a, b in _spans(text) if b > HEAD_CHARS]
    sets = [_terms(text[a:b]) for a, b in spans]
    df: dict[str, int] = {}
    for ts in sets:
        for t in ts:
            df[t] = df.get(t, 0) + 1
    want, hint = _terms(focus), _terms(note)
    score = [
        sum(1.0 / df[t] for t in ts & want) + 0.25 * sum(1.0 / df[t] for t in (ts & hint) - want)
        for ts in sets
    ]
    covered: list[tuple[int, int]] = []

    def size_with(a: int, b: int) -> int:
        merged = sorted([*covered, (max(a, HEAD_CHARS), b)])
        total, cur_a, cur_b = 0, -1, -1
        for x, y in merged:
            if x > cur_b:
                total += cur_b - cur_a + (3 if cur_b > 0 else 0)
                cur_a, cur_b = x, y
            else:
                cur_b = max(cur_b, y)
        return total + cur_b - cur_a + 3

    for i in sorted(range(len(spans)), key=lambda i: (-score[i], i)):
        if score[i] <= 0:
            break
        a, b = spans[i]
        if HEAD_CHARS + size_with(a, b) > limit:
            continue
        covered.append((max(a, HEAD_CHARS), b))
    parts: list[list[int]] = []
    for x, y in sorted(covered):
        if parts and x <= parts[-1][1]:
            parts[-1][1] = max(parts[-1][1], y)
        else:
            parts.append([x, y])
    return head + "\n…\n" + "\n…\n".join(text[x:y].strip() for x, y in parts)


def _norm(s: str) -> str:
    """Whitespace collapsed, and none around a hyphen: OCR splits "self-declaration" as
    "self -\ndeclaration". Only spacing is forgiven; every character else must match."""
    return re.sub(r"\s*-\s*", "-", re.sub(r"\s+", " ", s)).strip().lower()


def _quoted(quote: str, source: str) -> bool:
    q = _norm(quote).strip(" .\"'“”")
    return len(q) >= 10 and q in _norm(source)


def _short(q: str) -> str:
    q = re.sub(r"\s+", " ", q).strip()
    return q if len(q) <= 220 else q[:217] + "…"


def settled_pairs(relations: Iterable[Any]) -> list[frozenset[str]]:
    """Pairs left to types A / F: joined by a supersession / amendment / repeal the text states, or
    one an officer confirmed. An UNCONFIRMED supersession inferred only from matching subjects
    (plan §7.3, `updates/reconcile.py`) settles nothing: two same-subject instruments that say
    different things are exactly the type B case to put before the officer."""
    return [
        frozenset((r.source, r.target))
        for r in relations
        if r.confirmed or str(getattr(r.kind, "value", r.kind)) != "SUPERSEDES"
    ]


def contradiction_flags(
    docs: Sequence[Evidence],
    llm: LLMClient,
    linked: Iterable[frozenset[str]] = (),
    context: str = "",
) -> JudgmentResult:
    """`context` is the officer's note: it steers which parts of a long order are excerpted.
    It is never sent to the model."""
    system = load_prompt(PROMPT_ID)
    skip = set(linked)
    flags: list[ConflictFlag] = []
    asked = failed = 0
    for a, b in itertools.combinations(docs, 2):
        if (
            a.level is None
            or b.level is None
            or frozenset((a.canonical_id, b.canonical_id)) in skip
        ):
            continue
        if max(a.level, b.level) <= GO_LEVEL:
            continue  # two orders / rules: not asked yet (only pairs with a lower instrument)
        ea = excerpt(a.text, b.text[:EXCERPT_CHARS], note=context)
        eb = excerpt(b.text, a.text[:EXCERPT_CHARS], note=context)
        user = (
            f"DOCUMENT A ({a.canonical_id})\n<<<\n{ea}\n>>>\n\n"
            f"DOCUMENT B ({b.canonical_id})\n<<<\n{eb}\n>>>"
        )
        asked += 1
        try:
            ans = llm.generate_json(prompt_id=PROMPT_ID, system=system, user=user, schema=SCHEMA)
        except LLMError:
            failed += 1
            continue
        if ans.get("verdict") != "contradiction":
            continue
        qa, qb = str(ans.get("quote_a", "")), str(ans.get("quote_b", ""))
        if not (_quoted(qa, ea) and _quoted(qb, eb)):
            continue  # unsupported: a quote is not in the text the model was given
        if a.level == b.level:
            ctype = ConflictType.B
            explanation = (
                f"Potential conflict — {a.canonical_id} says “{_short(qa)}”, while "
                f"{b.canonical_id} says “{_short(qb)}” on the same point. Review recommended: "
                "establish which instruction applies."
            )
        else:
            (lo, ql), (hi, qh) = sorted(
                ((a, qa), (b, qb)), key=lambda x: -(x[0].level or 0)
            )  # lo = lower authority (higher level number)
            ctype = ConflictType.G
            explanation = (
                f"Potential conflict — {lo.canonical_id} says “{_short(ql)}”, but the higher "
                f"{hi.canonical_id} says “{_short(qh)}”. The higher instrument prevails unless "
                "saved. Review recommended."
            )
        flags.append(
            ConflictFlag(
                type=ctype,
                cited=a.canonical_id,
                evidence_ids=(a.canonical_id, b.canonical_id),
                explanation=explanation,
                dates={},
                certain=False,
            )
        )
    return JudgmentResult(flags=tuple(flags), asked=asked, failed=failed)
