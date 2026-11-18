"""Reworded repeats served from the scoped answer cache (plan §10.3, §10.2, CLAUDE.md §4.8;
ADR-0053). A reworded repeat shares an answer only within the same scope, with the same anchors
and the same content words; every other combination is a miss — and a miss is always safe."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.cache.semantic import SemanticIndex, anchors, content, is_reask, same_question
from app.config import REPO_ROOT, get_settings
from app.main import create_app
from tests.unit.test_orchestrator import AnswersOnly, _chat

DAY = dt.date(2026, 11, 18)
APP = create_app(get_settings().model_copy(update={"sandbox": True}))


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        APP.state.assist_runtime().llm = AnswersOnly()
        try:
            yield c
        finally:
            APP.state.assist_runtime().llm = None


def test_anchors_keep_apart_what_words_cannot() -> None:
    a = anchors("Is G.O.Ms.No.88/2022 in force?", ["AP-X-GOMS-88-2022"], "status", DAY)
    assert a != anchors("Is G.O.Ms.No.89/2022 in force?", ["AP-X-GOMS-89-2022"], "status", DAY)
    assert a != anchors(
        "Is G.O.Ms.No.88/2022 in force?", ["AP-X-GOMS-88-2022"], "status", DAY.replace(day=17)
    )
    plain = anchors("Was the spouse transfer approved?", [], "history", DAY)
    assert plain != anchors("Was the spouse transfer rejected?", [], "history", DAY)
    assert plain != anchors("Was the spouse transfer not approved?", [], "history", DAY)
    assert plain != anchors("Was the spouse transfer approved in 2024?", [], "history", DAY)


def test_one_different_meaningful_word_is_a_different_question() -> None:
    assert same_question(
        "Show the orders on the ban on transfers.", "Show the orders on the transfer ban."
    )
    assert same_question("What does para 2(v) say?", "What does paragraph 2(v) say?")
    assert not same_question(
        "Has a spouse-grounds transfer been decided?",
        "Has a medical-grounds transfer been decided?",
    )
    assert not same_question(
        "Which rules govern recruitment of Typists?", "Which rules govern promotion of Typists?"
    )
    assert not content("Is it?")  # nothing to match on: never matched
    # owner review (18 Nov): "my" / "all" are meaningful; relation questions keep their direction
    assert not same_question(
        "Which orders apply to my section?", "Which orders apply to all sections?"
    )
    assert not same_question("Which order replaced GO 88?", "Which order did GO 88 replace?")
    assert same_question("Which order replaced GO 88?", "Which order replaced GO 88 now?")


def test_the_labelled_pairs_never_share_a_wrong_answer() -> None:
    """The regression set (SYNTHETIC; evaluation/data/semantic_cache_pairs.json), with anchors as
    the app computes them: 0 'different' pairs matched, and most rewordings caught."""
    from evaluation.semantic_cache_calibrate import main

    assert main() == 0
    report = (REPO_ROOT / "evaluation" / "reports").glob("*-reworded-pairs.md")
    text = max(report).read_text("utf-8")
    assert "served the other's answer: **0**" in text


def test_the_index_matches_only_within_scope_and_anchors() -> None:
    ix = SemanticIndex(enabled=True)
    ix.remember("S1", "A1", "Which orders on transfers are in force now?", "k1")
    assert ix.find("S1", "A1", "Which transfer orders are in force?") == "k1"
    assert ix.find("S2", "A1", "Which transfer orders are in force?") is None  # other scope
    assert ix.find("S1", "A2", "Which transfer orders are in force?") is None  # other anchors
    assert ix.find("S1", "A1", "Which promotion orders are in force?") is None
    off = SemanticIndex(enabled=False)
    off.remember("S1", "A1", "Which orders on transfers are in force now?", "k1")
    assert off.find("S1", "A1", "Which orders on transfers are in force now?") is None
    assert is_reask(
        [("A1", "Which orders on transfers are in force now?")],
        "A1",
        "Which transfer orders are in force?",
    )
    assert not is_reask(
        [("A1", "Which orders on promotions are in force now?")],
        "A1",
        "Which transfer orders are in force?",
    )


Q1 = "Which orders govern the outsourced data entry operators now?"
Q2 = "Which orders govern outsourced data entry operators?"  # the same question, reworded


def test_a_reworded_repeat_is_served_from_the_scoped_cache(client: TestClient) -> None:
    first = _chat(client, "U01", Q1)
    assert first["status"] == "answered", first
    again = _chat(client, "U01", Q2)
    assert again["from_cache"] and again["statements"] == first["statements"]
    other = _chat(client, "U03", Q2)  # different permissions: never shared, reworded or not
    assert not other["from_cache"]
    near = _chat(client, "U01", "Which orders govern the outsourced driver posts?")
    assert not near["from_cache"]  # one different meaningful word


def test_a_reworded_repeat_misses_once_its_answer_is_invalidated(client: TestClient) -> None:
    q1, q2 = (
        "Which orders govern the outsourced security guards now?",
        "Which orders govern outsourced security guards?",
    )
    first = _chat(client, "U02", q1)
    if first["status"] != "answered":
        pytest.skip("no answer to cache for this officer")
    cited = {c["canonical_id"] for s in first["statements"] for c in s["citations"]}
    run = APP.state.assist_runtime()
    assert run.stores.cache.invalidate_documents(frozenset(cited)) >= 1
    assert not _chat(client, "U02", q2)["from_cache"]  # the index points at a dropped answer


def test_asking_again_in_other_words_is_recorded_as_a_reask(client: TestClient) -> None:
    """A signal for query analytics only (plan §10.4): the answer is unchanged."""
    from app.agents.orchestrator import TurnServices, run_turn
    from app.memory.session import SessionMemory
    from app.tracking.query_log import InMemoryQueryLog

    run = APP.state.assist_runtime()
    officer = APP.state.adapter.officer_context("U01")
    memory, log = SessionMemory(), InMemoryQueryLog()
    svc = TurnServices(
        officer=officer,
        ctx=run.tool_context("U01", run.store_for(officer)),
        memory=memory,
        cache=run.stores.cache,
        query_log=log,
        texts=run.texts,
        llm=AnswersOnly(),
        departments=run.departments,
        file_papers=lambda f: [],
        tags_of=run.tags,
        reworded=run.stores.reworded,
    )
    for i, q in enumerate(
        (
            "Who can sanction leave for a Senior Assistant?",
            "Who can sanction the leave of a Senior Assistant?",  # asked again, other words
            "Who can sanction tour for a Senior Assistant?",  # a different question
        )
    ):
        run_turn(svc, session_id="r" * 16, message=q, request_id=f"RQ{i}")
    assert [("reask" in r.flags) for r in log.records] == [False, True, False]
    stats: dict[str, Any] = run.stores.reworded.stats()
    assert stats["reworded_repeats"] == "on" and stats["reasks"] >= 1
