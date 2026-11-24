"""Within-request reuse of cloud reads (CLAUDE.md §4.8: "within-request retrieval/evidence reuse
never crosses requests or scopes"; 19 Nov 2026 deploy check).

One assistant request can ask the cloud stores about the same record many times: a draft checks
the visibility of every order in the temporal facts once per history, carry-forward and status
step, and each check was one BigQuery query (≈ 400 queries and > 5 minutes for one draft). The
answers cannot change within one request, so each is read once:

- the memo lives for ONE HTTP request (`request_memo()`, opened by a middleware) and is dropped
  with it — nothing is reused by a later request, so a permission change still applies at once;
- an L0 answer is keyed by the record AND the scope's signature, so two scopes never share one;
- graph reads (node, edges) are not scope-filtered at the store (the walk applies the scope to
  every node), so they are keyed by record alone;
- outside a request (start-up, jobs) nothing is kept: every call goes to the store.

`prefetch` asks the store for many records in one query (`BigQueryScopedIndex.exact_many`) and
keeps the answers, so a loop over many records costs one round trip.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterable, Iterator
from contextvars import ContextVar
from typing import Any

from app.auth.models import Scope
from app.graph.repository import GraphEdge, GraphNode
from app.retrieval.composite import GraphReader
from app.retrieval.scoped import IndexedDocument, L1Criteria, ScopedRetriever

log = logging.getLogger(__name__)
QUERIES = ("queries",)  # the memo key under which the request's store queries are counted

_MEMO: ContextVar[dict[tuple[Any, ...], Any] | None] = ContextVar("c2_request_memo", default=None)


@contextlib.contextmanager
def request_memo() -> Iterator[dict[tuple[Any, ...], Any]]:
    """A fresh memo for the code inside (one request); dropped on exit."""
    memo: dict[tuple[Any, ...], Any] = {}
    token = _MEMO.set(memo)
    try:
        yield memo
    finally:
        _MEMO.reset(token)


def _memo() -> dict[tuple[Any, ...], Any] | None:
    return _MEMO.get()


def count_query(store: str) -> None:
    """Called by a store for each query it sends (logged per request; a test bounds it)."""
    memo = _memo()
    if memo is not None:
        counts: dict[str, int] = memo.setdefault(QUERIES, {})
        counts[store] = counts.get(store, 0) + 1


def queries() -> dict[str, int]:
    """The queries sent so far in this request, by store."""
    memo = _memo()
    return dict(memo.get(QUERIES, {})) if memo is not None else {}


class MemoScopedIndex:
    """A `ScopedRetriever` whose L0 answers are kept for the rest of the request."""

    def __init__(self, inner: ScopedRetriever) -> None:
        self.inner = inner

    def exact(self, canonical_id: str, scope: Scope) -> list[IndexedDocument]:
        memo = _memo()
        if memo is None:
            return self.inner.exact(canonical_id, scope)
        key = ("exact", canonical_id, scope.signature, scope.user_id)
        if key not in memo:
            memo[key] = self.inner.exact(canonical_id, scope)
        return list(memo[key])

    def filter(self, criteria: L1Criteria, scope: Scope) -> list[IndexedDocument]:
        return self.inner.filter(criteria, scope)  # once per ladder run; not repeated

    def prefetch(self, canonical_ids: Iterable[str], scope: Scope) -> None:
        """Read the records not yet in the memo, in batched queries when the store can."""
        memo = _memo()
        if memo is None:
            return
        todo = [
            c
            for c in dict.fromkeys(canonical_ids)
            if ("exact", c, scope.signature, scope.user_id) not in memo
        ]
        if not todo:
            return
        many = getattr(self.inner, "exact_many", None)
        found = many(todo, scope) if many is not None else {}
        for c in todo:
            if c in found:
                memo[("exact", c, scope.signature, scope.user_id)] = found[c]


class MemoGraph:
    """A graph store whose node / edge reads are kept for the rest of the request."""

    def __init__(self, inner: GraphReader) -> None:
        self.inner = inner

    def _get(self, kind: str, cid: str, read: Any) -> Any:
        memo = _memo()
        if memo is None:
            return read(cid)
        key = (kind, cid, id(self.inner))
        if key not in memo:
            memo[key] = read(cid)
        return memo[key]

    def node(self, cid: str) -> GraphNode | None:
        node: GraphNode | None = self._get("node", cid, self.inner.node)
        return node

    def edges_from(self, cid: str) -> tuple[GraphEdge, ...]:
        edges: tuple[GraphEdge, ...] = self._get("from", cid, self.inner.edges_from)
        return edges

    def edges_to(self, cid: str) -> tuple[GraphEdge, ...]:
        edges: tuple[GraphEdge, ...] = self._get("to", cid, self.inner.edges_to)
        return edges


class RequestMemoMiddleware:
    """ASGI: one fresh memo per HTTP request, dropped when the response is sent."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        with request_memo() as memo:
            try:
                await self.app(scope, receive, send)
            finally:
                if sent := memo.get(QUERIES):  # IDs and counts only: never a query's values
                    log.info("cloud queries for %s: %s", scope.get("path", "?"), sent)


def memo_text(canonical_id: str, scope: Scope, read: Any) -> str:
    """A cloud-only order's passages, read once per request and scope."""
    memo = _memo()
    if memo is None:
        text: str = read(canonical_id, scope)
        return text
    key = ("text", canonical_id, scope.signature, scope.user_id)
    if key not in memo:
        memo[key] = read(canonical_id, scope)
    cached: str = memo[key]
    return cached
