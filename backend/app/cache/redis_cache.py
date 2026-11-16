"""Memorystore (Redis/Valkey) caches — cache only, never the session store (plan §10.2;
CLAUDE.md §2.2, §4.8; ADR-0035).

- `RedisAnswerCache`: the scoped answer cache shared by all instances. Same key as the in-memory
  reference (hash of canonical query + scope signature): officers with identical permissions
  share, different permissions never. Each entry is listed under every record it cites, so a new
  or changed record drops them (plan §7.4); every entry also expires (TTL) as a backstop.
- `CachedEmbedder`: the vector of a question's text (user-agnostic, content-hash key), so a
  repeated question skips the embedding call.

Redis failing is never an answer failing: every error is logged by kind and the cache is
bypassed. If an invalidation fails, this instance stops serving cached answers until it restarts
(an answer citing a changed record must not be served).
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from typing import Any

from app.auth.models import Scope
from app.cache.answers import answer_cache_key

log = logging.getLogger(__name__)


class RedisAnswerCache:
    def __init__(self, client: Any, *, prefix: str = "c2", ttl_s: int = 6 * 3600) -> None:
        self._r, self._p, self._ttl = client, prefix, ttl_s
        self.hits = self.misses = self.errors = 0
        self._serving = True

    def _key(self, k: str) -> str:
        return f"{self._p}:ans:{k}"

    def _cid(self, cid: str) -> str:
        return f"{self._p}:cid:{cid}"

    def get(self, canonical_query: str, scope: Scope | None) -> str | None:
        if scope is None or not self._serving:  # unverifiable scope / unsafe cache → bypass
            return None
        try:
            raw = self._r.get(self._key(answer_cache_key(canonical_query, scope)))
        except Exception as exc:  # noqa: BLE001 — the cache is never the answer path
            self.errors += 1
            log.error("redis get failed: %s", type(exc).__name__)
            return None
        if raw is None:
            self.misses += 1
            return None
        self.hits += 1
        return str(json.loads(raw)["answer"])

    def put(
        self, canonical_query: str, scope: Scope | None, answer: str, cited_ids: frozenset[str]
    ) -> None:
        if scope is None or not self._serving:
            return
        key = self._key(answer_cache_key(canonical_query, scope))
        try:
            pipe = self._r.pipeline()
            pipe.set(key, json.dumps({"answer": answer, "cited": sorted(cited_ids)}), ex=self._ttl)
            for cid in cited_ids:
                pipe.sadd(self._cid(cid), key)
                pipe.expire(self._cid(cid), self._ttl)
            pipe.execute()
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            log.error("redis put failed: %s", type(exc).__name__)

    def invalidate_documents(self, canonical_ids: frozenset[str]) -> int:
        dropped = 0
        try:
            for cid in canonical_ids:
                keys = list(self._r.smembers(self._cid(cid)))
                if keys:
                    dropped += int(self._r.delete(*keys))
                self._r.delete(self._cid(cid))
        except Exception as exc:  # noqa: BLE001
            self.errors += 1
            self._serving = False  # stale answers might remain: stop serving them here
            log.error(
                "redis invalidation failed (%s): cache off on this instance", type(exc).__name__
            )
        return dropped

    def stats(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "backend": "redis",
            "serving": self._serving,
            "hits": self.hits,
            "misses": self.misses,
            "errors": self.errors,
            "ttl_s": self._ttl,
        }
        try:
            out["answers"] = sum(1 for _ in self._r.scan_iter(f"{self._p}:ans:*", count=500))
            out["embeddings"] = sum(1 for _ in self._r.scan_iter(f"{self._p}:emb:*", count=500))
            out["reachable"] = True
        except Exception as exc:  # noqa: BLE001
            out["reachable"] = False
            log.error("redis scan failed: %s", type(exc).__name__)
            return out
        try:
            info = self._r.info()
            out |= {
                "used_memory": info.get("used_memory_human"),
                "max_memory": info.get("maxmemory_human"),
                "evicted_keys": info.get("evicted_keys"),
                "connected_clients": info.get("connected_clients"),
                "server_hits": info.get("keyspace_hits"),
                "server_misses": info.get("keyspace_misses"),
                "version": info.get("redis_version"),
            }
        except Exception as exc:  # noqa: BLE001 — server figures are a nice-to-have
            log.warning("redis info unavailable: %s", type(exc).__name__)
        return out


class CachedEmbedder:
    """A question's vector, cached by the hash of model + text (no user, no scope: the vector of
    the same words is the same for everyone). Passages are embedded by the batch job, uncached."""

    def __init__(self, inner: Any, client: Any, *, prefix: str = "c2", ttl_s: int = 7 * 86400):
        self._inner, self._r, self._p, self._ttl = inner, client, prefix, ttl_s
        self.name = inner.name
        self.hits = self.misses = 0

    def _key(self, text: str) -> str:
        h = hashlib.sha256(f"{self.name}\x1f{text}".encode()).hexdigest()
        return f"{self._p}:emb:{h}"

    def embed_query(self, text: str) -> list[float]:
        key = self._key(text)
        try:
            raw = self._r.get(key)
        except Exception as exc:  # noqa: BLE001
            log.error("redis get failed: %s", type(exc).__name__)
            raw = None
        if raw is not None:
            self.hits += 1
            return [float(x) for x in json.loads(raw)]
        self.misses += 1
        vec = list(self._inner.embed_query(text))
        try:
            self._r.set(key, json.dumps(vec), ex=self._ttl)
        except Exception as exc:  # noqa: BLE001
            log.error("redis set failed: %s", type(exc).__name__)
        return vec

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        result: list[list[float]] = self._inner.embed_documents(texts)
        return result


def redis_client(url: str) -> Any:
    """Short timeouts: an unreachable cache must cost milliseconds, not the officer's answer."""
    import redis  # noqa: PLC0415 — optional `cache` extra

    return redis.Redis.from_url(
        url, socket_timeout=0.3, socket_connect_timeout=0.5, health_check_interval=30
    )
