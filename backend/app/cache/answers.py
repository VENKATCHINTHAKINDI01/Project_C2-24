"""Scoped answer cache (plan §5.7, §10.2; ADR-0009).

Key = hash(canonical_query + scope_signature). Officers with IDENTICAL permissions share answers
(owner decision, 3 Nov 2026) — useful when many offices draft similar notings. Different
permissions never share: the signature changes with any change in rank, search scope, clearance,
section, assignments, movements or policy version. Entries are dropped when a document they cite
changes. If the scope cannot be verified, callers bypass the cache (CLAUDE.md §4.8).
"""

from __future__ import annotations

import hashlib
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.auth.models import Scope


class AnswerCache(Protocol):
    """In memory (reference, one instance) or Redis (Memorystore, shared; ADR-0035)."""

    def get(self, canonical_query: str, scope: Scope | None) -> str | None: ...

    def put(
        self, canonical_query: str, scope: Scope | None, answer: str, cited_ids: frozenset[str]
    ) -> None: ...

    def invalidate_documents(self, canonical_ids: frozenset[str]) -> int: ...

    def stats(self) -> dict[str, Any]: ...


def normalise_query(canonical_query: str) -> str:
    return re.sub(r"\s+", " ", canonical_query.strip().lower())


def answer_cache_key(canonical_query: str, scope: Scope) -> str:
    blob = f"{normalise_query(canonical_query)}\x1f{scope.signature}".encode()
    return hashlib.sha256(blob).hexdigest()


@dataclass
class _Entry:
    answer: str
    cited_ids: frozenset[str]


@dataclass
class InMemoryAnswerCache:
    """Reference cache; Memorystore implements the same methods (cache only). Thread-safe and
    bounded (ADR-0039): past `max_entries` the least recently used answer is dropped."""

    _entries: OrderedDict[str, _Entry] = field(default_factory=OrderedDict)
    hits: int = 0
    misses: int = 0
    max_entries: int = 5000
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def get(self, canonical_query: str, scope: Scope | None) -> str | None:
        if scope is None:  # unverifiable scope → bypass
            return None
        key = answer_cache_key(canonical_query, scope)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return entry.answer

    def put(
        self, canonical_query: str, scope: Scope | None, answer: str, cited_ids: frozenset[str]
    ) -> None:
        if scope is None:
            return
        key = answer_cache_key(canonical_query, scope)
        with self._lock:
            self._entries[key] = _Entry(answer, cited_ids)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def invalidate_documents(self, canonical_ids: frozenset[str]) -> int:
        """New/changed/reclassified documents drop every answer that cites them (plan §7.4)."""
        with self._lock:
            stale = [k for k, e in self._entries.items() if e.cited_ids & canonical_ids]
            for k in stale:
                del self._entries[k]
        return len(stale)

    def __len__(self) -> int:
        return len(self._entries)

    def stats(self) -> dict[str, Any]:
        return {
            "backend": "memory (this instance only)",
            "serving": True,
            "hits": self.hits,
            "misses": self.misses,
            "answers": len(self._entries),
        }
