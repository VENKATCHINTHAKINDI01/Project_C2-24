"""Semantic caching and re-ask detection (plan §10.3, Tier 2; ADR-0053).

A reworded repeat of a question answered earlier IN THE SAME SCOPE is served from the scoped
answer cache (§10.2 layer 2) instead of being answered again. Two questions match only when:

1. they were asked under the SAME scope signature (identical permissions — the rule of the exact
   cache, ADR-0009); and
2. their ANCHORS are identical — the facts the answer depends on, read by fixed rules: the intent,
   the orders / files named (resolved IDs), every number and year, negation, the outcome asked
   about, and the as-of date. "Is G.O.Ms.No.88 in force?" and "… No.89 …" never match, however
   alike their words; nor do "approved" and "rejected", or "is" and "is not"; and
3. they say the same thing in other words: the SAME content words once wording is normalised
   (plurals and verb endings, "para"/"paragraph", "G.O."/"GO", "Commissioner's"), ignoring only
   filler ("now", "please", "any", "kindly"). One different meaningful word — "spouse" for
   "medical", "promotion" for "recruitment" — and they never match.

Why not a similarity threshold (ADR-0053): calibration showed a one-word change in a six-word
question scores 0.83 and in a seven-word one 0.86, so any threshold that catches rewordings also
serves a wrong answer to some longer question. Exact content words make a wrong match impossible
by construction; the calibration pairs (`evaluation/data/semantic_cache_pairs.json`) are its
regression set. On / off: `config/runtime.yaml` cache.reworded_repeats.

The answer itself is still read through the scoped answer cache by its own exact key, so expiry
and invalidation (permission change, reclassification, new documents) apply unchanged: a match
whose answer was dropped is simply a miss. Words, not embeddings (ADR-0053): free, instant and
deterministic, where an embedding call per question would cost more time than a "latency nicety"
saves. The index lives in this instance's memory, bounded per scope.

Re-ask detection: the same officer asking a near-identical question again in the same session is
a signal that the first answer did not help (query analytics, plan §10.4). It is reported, never
used to change an answer.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import threading
from collections import OrderedDict, deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

_WORD = re.compile(r"[a-z]+|[ఀ-౿]+")
_NUMBER = re.compile(r"\d+(?:[./-]\d+)*")
_NEGATION = re.compile(r"\b(?:not|no|never|without|nor|cannot|isn't|wasn't|aren't|weren't)\b")
_OUTCOME = re.compile(
    r"\b(rejected|refused|declined|approved|sanctioned|allowed|granted|returned|pending)\b"
)
# function words and question scaffolding: they carry no meaning of their own here
_STOP = frozenset(
    "a an the of to in on for at by with from and or is are was were be been being do does did "
    "what which who whom whose when where why how it its there their they "
    "can could would should may might will shall please kindly tell "
    "show give list let us about per as into than then so if".split()
)  # NOT stop words: my / our / your / me / I / we / all / any / some / this / that / these /
# those — "my section" and "all sections" are different questions (owner review, 18 Nov)
# a question about how orders relate: the direction is in the word order ("which order replaced
# GO 88" vs "which order did GO 88 replace"), so these match only word for word, in order
_RELATION = re.compile(
    r"\b(?:replac|supersed|amend|cancel|withdr|rescind|clarif|modif|repeal|substitut|revis)\w*"
)
# words that change nothing about what is asked
_FILLER = frozenset(
    "now today currently presently present please kindly again before ever also just exactly "
    "still yet already been being has have had".split()
)
# the same word written two ways; order numbers are anchors, their "G.O.Ms.No." spelling is noise
_SAME = {"paragraph": "para", "paras": "para", "clause": "para", "government": "go"}
_NOISE = frozenset({"go", "g", "o", "ms", "rt", "no", "s", "dt", "dated", "of"})


def anchors(raw_query: str, entities: Sequence[str], intent: str, as_of: dt.date) -> str:
    """The facts an answer depends on, by fixed rules. Questions with different anchors never
    share an answer."""
    q = raw_query.lower()
    parts = (
        intent,
        "|".join(sorted(set(entities))),
        "|".join(sorted(set(_NUMBER.findall(q)))),
        "|".join(sorted(set(_NEGATION.findall(q)))),
        "|".join(sorted(set(_OUTCOME.findall(q)))),
        as_of.isoformat(),
    )
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _stem(w: str) -> str:
    for suf in ("ings", "ing", "ies", "es", "ed", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def stem(word: str) -> str:
    """The light stem the reworded-repeat test uses ("transfers" → "transfer")."""
    w = _SAME.get(word, word)
    return _SAME.get(_stem(w), _stem(w))


def content(raw_query: str) -> frozenset[str]:
    """What the question is about, in normalised words (numbers are anchors, not words)."""
    out = set()
    for w in _WORD.findall(raw_query.lower()):
        if w in _STOP or w in _FILLER or w in _NOISE:
            continue
        w = _SAME.get(w, w)
        out.add(_SAME.get(_stem(w), _stem(w)))
    return frozenset(out - _NOISE)


def topic_words(raw_query: str) -> list[str]:
    """The question's subject words as written (lower-case, not stemmed), for FAQ topics on the
    monitoring pad (ADR-0059): no stop words, filler, numbers or words under four letters."""
    out = []
    for w in _WORD.findall(raw_query.lower()):
        if len(w) < 4 or w.isdigit() or w in _STOP or w in _FILLER or w in _NOISE:
            continue
        out.append(w)
    return list(dict.fromkeys(out))


def _ordered(raw_query: str) -> tuple[str, ...]:
    """Every word but filler and noise, in order (for questions about how orders relate)."""
    out: list[str] = []
    for w in _WORD.findall(raw_query.lower()):
        if w in _FILLER or w in _NOISE:
            continue
        w = _SAME.get(w, w)
        out.append(_SAME.get(_stem(w), _stem(w)))
    return tuple(out)


def form(raw_query: str) -> frozenset[str] | tuple[str, ...]:
    """What two questions must share to be the same question (anchors aside): their content
    words — and, for a question about how orders relate, every word in the same order."""
    if _RELATION.search(raw_query.lower()):
        return _ordered(raw_query)
    return content(raw_query)


def same_question(a: str, b: str) -> bool:
    """Same question in other words (anchors are compared separately)."""
    fa, fb = form(a), form(b)
    return bool(fa) and fa == fb


@dataclass
class _Seen:
    words: frozenset[str] | tuple[str, ...]
    key: str  # the exact answer-cache key of the earlier question


@dataclass
class SemanticIndex:
    """Recent answered questions per (scope signature, anchors). Thread-safe, bounded."""

    enabled: bool
    per_scope: int = 200
    max_scopes: int = 2000
    hits: int = 0
    reasks: int = 0
    _seen: OrderedDict[str, deque[_Seen]] = field(default_factory=OrderedDict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def remember(self, scope_signature: str, anchor: str, raw_query: str, key: str) -> None:
        if not self.enabled or not form(raw_query):
            return
        bucket_id = f"{scope_signature}\x1f{anchor}"
        with self._lock:
            bucket = self._seen.setdefault(bucket_id, deque(maxlen=self.per_scope))
            self._seen.move_to_end(bucket_id)
            if all(s.key != key for s in bucket):
                bucket.append(_Seen(form(raw_query), key))
            while len(self._seen) > self.max_scopes:
                self._seen.popitem(last=False)

    def find(self, scope_signature: str, anchor: str, raw_query: str) -> str | None:
        """The exact cache key of an earlier question with the same scope, the same anchors and
        the same content words; else None."""
        words = form(raw_query)
        if not self.enabled or not words:
            return None
        with self._lock:
            bucket = self._seen.get(f"{scope_signature}\x1f{anchor}")
            for seen in reversed(bucket or ()):
                if seen.words == words:
                    return seen.key
        return None

    def stats(self) -> dict[str, Any]:
        return {
            "reworded_repeats": "on" if self.enabled else "off",
            "semantic_hits": self.hits,
            "reasks": self.reasks,
            "scopes": len(self._seen),
        }


def is_reask(previous: Sequence[tuple[str, str]], anchor: str, raw_query: str) -> bool:
    """`previous`: this session's earlier (anchors, question) turns. True when the officer asks
    the same question again in other words — a signal only (plan §10.4)."""
    return any(a == anchor and same_question(q, raw_query) for a, q in previous)
