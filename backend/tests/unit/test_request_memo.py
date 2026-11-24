"""Cloud reads per request (19 Nov 2026 deploy check: one draft sent ≈ 400 BigQuery queries and
took > 5 minutes; on Cloud Run it failed closed). Each record is read once per request, many
records in one batched query, and nothing is reused across requests or scopes."""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.tools import visible_facts
from app.retrieval.bigquery_index import BigQueryScopedIndex, Param
from app.retrieval.cloud import CloudRungs
from app.retrieval.request_memo import queries, request_memo
from app.temporal.engine import Instrument, RelationKind, TemporalRelation
from tests.unit.test_sandbox_api import APP, _h

NAVEEN = "2894562"


class _Runner:
    """A BigQuery stand-in: counts queries; every G.O. key asked for exists as a public order."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, sql: str, params: Sequence[Param]) -> list[Mapping[str, Any]]:
        from app.retrieval.request_memo import count_query

        count_query("bigquery")
        keys = next((list(v) for n, _, v in params if n == "keys"), [])
        self.calls.append(keys)
        return [
            {
                "canonical_id": k,
                "base_id": k,
                "department": k.split("-")[1],
                "section": None,
                "classification": "UNCLASSIFIED",
                "file_no": None,
                "doc_type": "Government Order",
                "issue_date": None,
                "subject": "synthetic",
            }
            for k in keys
            if "-GOMS-" in k
        ]


class _NoGraph:
    def node(self, cid: str) -> None:
        return None

    def edges_from(self, cid: str) -> tuple[()]:
        return ()

    def edges_to(self, cid: str) -> tuple[()]:
        return ()


class _NoText:
    def text(self, cid: str, scope: Any) -> str:
        return ""


@pytest.fixture
def cloud() -> Iterator[tuple[Any, _Runner]]:
    with TestClient(APP) as c:
        run = APP.state.assist_runtime()
        runner = _Runner()
        run.cloud = CloudRungs(
            index=BigQueryScopedIndex(runner, "p.d.documents"),
            graph=_NoGraph(),
            l2=None,
            l2_min_score=None,
            passages=_NoText(),  # type: ignore[arg-type]
        )
        try:
            yield c, runner
        finally:
            run.cloud = None


def _many_cloud_orders(ctx: Any, n: int) -> Any:
    """The officer's context with `n` orders known only to the cloud index, chained by links."""
    ids = [f"AP-GAD01-GOMS-{900 + i}-2019" for i in range(n)]
    inst = {
        c: Instrument(canonical_id=c, hierarchy_level=2, effective_from=dt.date(2019, 1, 1))
        for c in ids
    }
    rels = tuple(
        TemporalRelation(source=a, kind=RelationKind.AMENDS, target=b)
        for a, b in zip(ids, ids[1:], strict=False)
    )
    return dataclasses.replace(
        ctx, instruments={**ctx.instruments, **inst}, relations=(*ctx.relations, *rels)
    ), ids


def test_many_cloud_records_are_checked_in_one_batched_query(cloud: tuple[Any, _Runner]) -> None:
    _, runner = cloud
    run = APP.state.assist_runtime()
    ctx, ids = _many_cloud_orders(
        run.tool_context("U01", run.store_for(APP.state.adapter.officer_context("U01"))), 60
    )
    # outside a request: one query per record (no memo is kept)
    plain, _ = visible_facts(ctx, set())
    unbatched = len(runner.calls)
    assert unbatched >= 60
    runner.calls.clear()
    with request_memo():
        inst, _ = visible_facts(ctx, set())
        visible_facts(ctx, set())  # the same request asking again reads nothing new
        visible_facts(ctx, {ids[0]})
        sent = queries()
    assert inst == plain and set(ids) <= set(inst)  # the same answer; every order visible
    assert len(runner.calls) == 1 and sent == {"bigquery": 1}
    assert len(runner.calls[0]) == 60  # one batch for all sixty


def test_nothing_is_reused_across_requests_or_scopes(cloud: tuple[Any, _Runner]) -> None:
    _, runner = cloud
    run = APP.state.assist_runtime()
    a, ids = _many_cloud_orders(
        run.tool_context("U01", run.store_for(APP.state.adapter.officer_context("U01"))), 5
    )
    with request_memo():
        visible_facts(a, set())
    with request_memo():  # a new request reads again: a permission change applies at once
        visible_facts(a, set())
    assert len(runner.calls) == 2
    b, _ = _many_cloud_orders(
        run.tool_context("U02", run.store_for(APP.state.adapter.officer_context("U02"))), 5
    )
    with request_memo():
        visible_facts(a, set())
        visible_facts(b, set())  # another officer's scope never shares an answer
    assert len(runner.calls) == 4


def test_a_draft_stays_within_a_query_budget(cloud: tuple[Any, _Runner]) -> None:
    c, runner = cloud
    body = {"computer_no": NAVEEN, "format_id": "note_proposal"}
    first = c.post("/assist/draft/prepare", json=body, headers=_h("U01"))
    assert first.status_code == 200, first.text
    n = len(runner.calls)
    assert n <= 8, n  # was one query per record checked (≈ 400 on the cloud corpus)
    again = c.post("/assist/draft/prepare", json=body, headers=_h("U01"))
    assert again.status_code == 200 and again.json()["draft"] == first.json()["draft"]
    assert len(runner.calls) == 2 * n  # each request reads for itself


def test_exact_many_answers_exactly_like_exact() -> None:
    from app.auth.models import Scope

    runner = _Runner()
    idx = BigQueryScopedIndex(runner, "p.d.documents")
    scope = Scope(
        user_id="U01",
        department="GAD01",
        sections=frozenset(),
        file_nos=frozenset(),
        department_wide=True,
        max_rank=0,
        public_rank=0,
        classification_ranks={"UNCLASSIFIED": 0},
        policy_version="t",
    )
    ids = ["AP-GAD01-GOMS-1-2019", "AP-GAD01-MEMO-2-2019", "not an id", "AP-FIN01-GOMS-3-2020"]
    many = idx.exact_many(ids, scope)
    assert set(many) == set(ids)
    for cid in ids:
        assert many[cid] == idx.exact(cid, scope), cid
