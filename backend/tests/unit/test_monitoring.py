"""The monitoring officer's pad and the Redis caches (ADR-0035)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import fakeredis
import pytest
from fastapi.testclient import TestClient

from app.auth.models import Scope
from app.cache.redis_cache import CachedEmbedder, RedisAnswerCache
from app.config import get_settings
from app.hitl.feedback import Action, HumanAction, TargetKind
from app.main import create_app
from app.tracking.monitor import build_monitor
from app.tracking.query_log import QueryRecord

APP = create_app(get_settings().model_copy(update={"sandbox": True}))


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        yield c


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


def _rec(
    qid: str, user: str, q: str, rank: int, status: str = "answered", ms: int = 900
) -> QueryRecord:
    return QueryRecord(
        query_id=qid,
        ts=dt.datetime(2026, 11, 15, 9, int(qid[1:]) % 60, tzinfo=dt.UTC),
        session_id="s",
        turn=1,
        user_id=user,
        department="USD01",
        section="ESTT.I",
        role="Section Officer",
        query_hash=" ".join(q.lower().split()),
        intent="precedent_lookup",
        ladder_level="L2",
        scope_signature="sig",
        latency_ms=ms,
        answer_status=status,
        question=q,
        clearance_rank=rank,
    )


def test_questions_are_shown_only_to_a_monitor_cleared_as_high_as_the_asker() -> None:
    recs = [
        _rec("q1", "U01", "Has a spouse transfer been decided before?", 1),
        _rec("q2", "U02", "Has a spouse transfer been decided before?", 1),
        _rec("q3", "U04", "Vigilance enquiry against the Superintendent?", 3, "no_answer", 4000),
    ]
    acts = [
        HumanAction(
            action_id="a",
            ts=dt.datetime(2026, 11, 15, 10, tzinfo=dt.UTC),
            user_id="U01",
            query_id="q1",
            target_kind=TargetKind.ANSWER,
            action=Action.THUMBS_DOWN,
        )
    ]
    low = build_monitor(recs, acts, dt.date(2026, 11, 1), viewer_rank=2)
    by_id = {a.query_id: a for a in low.activity}
    assert by_id["q1"].question and not by_id["q1"].withheld
    assert by_id["q3"].question is None and by_id["q3"].withheld  # asked under SECRET
    assert "Vigilance" not in low.model_dump_json()
    top = low.frequent[0]
    assert (top.question, top.times, top.officers) == (
        "Has a spouse transfer been decided before?",
        2,
        2,
    )
    assert low.gaps[0].withheld and low.gaps[0].times == 1
    assert low.slowest[0].query_id == "q3" and by_id["q1"].feedback == "thumbs_down"
    officers = {o.user_id: o for o in low.officers}
    assert officers["U01"].thumbs_down == 1 and officers["U04"].no_answer == 1
    high = build_monitor(recs, acts, dt.date(2026, 11, 1), viewer_rank=3)
    assert "Vigilance enquiry" in high.model_dump_json()


def test_the_pad_is_only_for_monitoring_officers(client: TestClient) -> None:
    q = "Has a spouse-ground transfer been decided before?"
    client.post("/assist/chat", json={"message": q}, headers=_h("U01"))
    ok = client.get("/assist/monitor", headers=_h("M01"))
    assert ok.status_code == 200
    j = ok.json()
    assert j["overview"]["questions"] >= 1 and j["cache"]["backend"].startswith("memory")
    assert any(a["question"] == q and a["user_id"] == "U01" for a in j["activity"])
    assert client.get("/assist/me/roles", headers=_h("M01")).json() == {"monitoring": True}
    assert client.get("/assist/me/roles", headers=_h("U01")).json() == {"monitoring": False}
    for uid in ("U01", "U05"):
        r = client.get("/assist/monitor", headers=_h(uid))
        none = client.get("/assist/nothing-here", headers=_h(uid))
        assert r.status_code == none.status_code == 404 and r.json() == none.json()


# --- Redis -----------------------------------------------------------------------------------


def _scope(sig: str) -> Any:
    class S:
        signature = sig

    return S()


def test_redis_answers_are_scoped_shared_and_dropped_when_a_cited_record_changes() -> None:
    r = fakeredis.FakeRedis()
    c = RedisAnswerCache(r, ttl_s=600)
    a, b = _scope("officer-A"), _scope("officer-B")
    c.put("q", a, '{"x": 1}', frozenset({"AP-FIN01-GOMS-31-2025"}))
    assert c.get("q", a) == '{"x": 1}'
    assert c.get("q", b) is None  # different permissions never share
    assert c.get("q", None) is None  # unverifiable scope: bypass
    other = RedisAnswerCache(r)  # another instance sees the same entry
    assert other.get("q", a) == '{"x": 1}'
    assert 0 < r.ttl(next(iter(r.scan_iter("c2:ans:*")))) <= 600
    assert c.invalidate_documents(frozenset({"AP-FIN01-GOMS-31-2025"})) == 1
    assert other.get("q", a) is None
    s = c.stats()
    assert s["backend"] == "redis" and s["hits"] == 1 and s["reachable"] is True


def test_a_redis_failure_never_breaks_an_answer_and_a_failed_invalidation_stops_serving() -> None:
    class Down:
        def __getattr__(self, name: str) -> Any:
            def fail(*a: Any, **k: Any) -> Any:
                raise ConnectionError("down")

            return fail

    c = RedisAnswerCache(Down())
    assert c.get("q", _scope("A")) is None  # miss, no exception
    c.put("q", _scope("A"), "x", frozenset({"X"}))  # dropped, no exception
    c.invalidate_documents(frozenset({"X"}))
    assert c.stats()["serving"] is False and c.stats()["reachable"] is False

    r = fakeredis.FakeRedis()
    ok = RedisAnswerCache(r)
    ok.put("q", _scope("A"), "x", frozenset({"X"}))
    ok._r = Down()  # noqa: SLF001 — the server goes away during an invalidation
    ok.invalidate_documents(frozenset({"X"}))
    ok._r = r  # noqa: SLF001 — and comes back: this instance still refuses to serve
    assert ok.get("q", _scope("A")) is None


def test_a_repeated_question_skips_the_embedding_call() -> None:
    class Emb:
        name = "m@asia-south1/4"
        calls = 0

        def embed_query(self, text: str) -> list[float]:
            Emb.calls += 1
            return [0.1, 0.2, 0.3, 0.4]

        def embed_documents(self, texts: Any) -> list[list[float]]:
            return [[0.0] * 4 for _ in texts]

    e = CachedEmbedder(Emb(), fakeredis.FakeRedis(), ttl_s=60)
    assert (
        e.embed_query("transfer rules") == e.embed_query("transfer rules") == [0.1, 0.2, 0.3, 0.4]
    )
    assert Emb.calls == 1 and (e.hits, e.misses) == (1, 1)
    e.embed_query("another question")
    assert Emb.calls == 2


def test_scope_type_is_what_the_cache_reads() -> None:
    assert "signature" in Scope.model_fields or hasattr(Scope, "signature")
