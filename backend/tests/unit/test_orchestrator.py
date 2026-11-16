"""The conversational assistant (ADR-0029): one LangGraph run per turn over AgentState; follow-ups
re-checked against the officer's access NOW; sessions never shared; scoped answer cache; query log
with IDs only."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.intents import Intent
from app.agents.orchestrator import TurnServices, classify, run_turn
from app.agents.state import AgentState
from app.config import get_settings
from app.main import create_app
from app.memory.session import SessionMemory
from app.tracking.query_log import InMemoryQueryLog, QueryRecord
from tests.unit.test_cited_answer import FakeLLM
from tests.unit.test_sandbox_api import MATRIX, USERS, _doc_id, _h

LOG = InMemoryQueryLog()
APP = create_app(get_settings().model_copy(update={"sandbox": True}))
FILE = "USD01-12/19/2026-ESTT.I"
NOTE = "AP-USD01-NOTE-USD0112-19-2026"


class AnswersOnly(FakeLLM):
    """The cited-answer fake; writes no note (the noting agent has its own tests)."""

    def generate_json(self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]):
        if prompt_id.startswith("noting_draft"):
            return {"sections": []}
        return super().generate_json(prompt_id=prompt_id, system=system, user=user, schema=schema)


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        APP.state.assist_runtime().llm = AnswersOnly()
        try:
            yield c
        finally:
            APP.state.assist_runtime().llm = None


def _chat(c: TestClient, uid: str, message: str, sid: str | None = None) -> dict[str, Any]:
    body = {"message": message} | ({"session_id": sid} if sid else {})
    r = c.post("/assist/chat", json=body, headers=_h(uid))
    assert r.status_code == 200, r.text
    return dict(r.json())


def test_intent_rules() -> None:
    assert classify(f"Check file {FILE}", [], [FILE]) is Intent.CONFLICT_CHECK
    assert classify("Is it still valid?", ["X"], []) is Intent.DOCUMENT_STATUS
    assert classify("What does para 2 say?", ["X"], []) is Intent.CLAUSE_LOOKUP
    assert classify("What replaced it?", ["X"], []) is Intent.SUPERSESSION_CHAIN
    assert classify("Has this been decided before?", [], []) is Intent.DECISION_HISTORY
    assert classify("leave encashment precedent", [], []) is Intent.PRECEDENT_LOOKUP


def test_a_follow_up_uses_the_earlier_turn(client: TestClient) -> None:
    one = _chat(client, "U01", "What does G.O.Ms.No.88/2022 say about transfers?")
    two = _chat(client, "U01", "Is that order still in force?", one["session_id"])
    assert (one["turn"], two["turn"]) == (1, 2) and two["used_earlier_turn"]
    facts = [s for s in two["statements"] if s["source"] == "order records"]
    assert facts and "AP-FIN01-GOMS-88-2022" in facts[0]["text"]  # resolved from turn 1


def test_a_session_is_never_shared(client: TestClient) -> None:
    one = _chat(client, "U01", f"Check file {FILE} against the current orders.")
    other = _chat(client, "U04", "What did that file propose?", one["session_id"])
    assert other["session_id"] != one["session_id"] and other["turn"] == 1
    assert not other["used_earlier_turn"]


def test_every_officer_follow_up_stays_inside_their_access(client: TestClient) -> None:
    for uid in USERS:
        one = _chat(client, uid, f"Check file {FILE} against the current orders.")
        two = _chat(client, uid, "Summarise what that file proposed.", one["session_id"])
        for out in (one, two):
            named = {d for c in out.get("documents", []) if (d := _doc_id(c))}
            assert all(MATRIX[(d, uid)] for d in named), (uid, named)


def test_a_permission_change_mid_session_applies_on_the_next_turn(client: TestClient) -> None:
    """Turn 1 finds a file paper; before turn 2 the officer loses access to that file
    (here: a narrower e-Office context). The follow-up must not bring it back."""
    run = APP.state.assist_runtime()
    adapter = APP.state.adapter
    full = adapter.officer_context("U01")
    memory, log = SessionMemory(), InMemoryQueryLog()

    def svc(ctx: Any, llm: Any) -> TurnServices:
        store = run.store_for(ctx)
        return TurnServices(
            officer=ctx,
            ctx=run.tool_context(ctx.user_id, store),
            memory=memory,
            cache=run.stores.cache,
            query_log=log,
            texts=run.texts,
            llm=llm,
            departments=run.departments,
            file_papers=lambda f: [
                d.canonical_id for d in run.stores.index._docs if d.tags.file_no == f
            ],
            tags_of=run.tags,
        )

    one = run_turn(svc(full, FakeLLM()), session_id="a" * 16, message=f"Check file {FILE} now.",
                   request_id="R1")  # fmt: skip
    assert NOTE in one.entities or NOTE in one.authorized_candidates
    narrow = full.model_copy(
        update={"assigned_files": frozenset(), "handled_files": frozenset(), "section": "NONE"}
    )
    llm = FakeLLM()
    two = run_turn(svc(narrow, llm), session_id="a" * 16, message="What did that file propose?",
                   request_id="R2")  # fmt: skip
    may_now = run.tool_context("U01", run.store_for(narrow))
    from app.agents.tools import visible_document

    assert visible_document(may_now, NOTE) is None  # the narrowing really removed access
    assert NOTE not in two.recalled and NOTE not in two.authorized_candidates
    assert all(NOTE not in p for p in llm.prompts)


def test_the_answer_cache_is_scoped(client: TestClient) -> None:
    q = "What does G.O.Ms.No.88/2022 provide on the transfer ceiling?"
    first = _chat(client, "U01", q)
    again = _chat(client, "U01", q)
    other = _chat(client, "U03", q)
    if first["status"] == "answered":
        assert again["from_cache"]
    assert not other["from_cache"]  # different permissions never share an answer


def test_the_query_log_holds_ids_not_text(client: TestClient) -> None:
    from app.agents.orchestrator import TurnServices as _  # noqa: F401 — import check

    q = "Which orders govern the outsourced data entry operators?"
    run = APP.state.assist_runtime()
    log = InMemoryQueryLog()
    state = run_turn(
        TurnServices(
            officer=APP.state.adapter.officer_context("U01"),
            ctx=run.tool_context("U01", run.store_for(APP.state.adapter.officer_context("U01"))),
            memory=SessionMemory(),
            cache=run.stores.cache,
            query_log=log,
            texts=run.texts,
            llm=FakeLLM(),
            departments=run.departments,
            file_papers=lambda f: [],
            tags_of=run.tags,
        ),
        session_id="b" * 16,
        message=q,
        request_id="R3",
    )
    assert isinstance(state, AgentState) and len(log.records) == 1
    rec: QueryRecord = log.records[0]
    blob = json.dumps(rec.model_dump(mode="json"))
    assert "outsourced" not in blob and "data entry" not in blob.lower()
    assert rec.user_id == "U01" and rec.answer_status == state.outcome and rec.turn == 1
    assert set(rec.retrieved_ids) == set(state.authorized_candidates)


def test_golden_path_draft_the_noting_using_that_precedent(client: TestClient) -> None:
    """Plan §10.1: "draft the noting" must know which precedent. Turn 1 finds precedents; turn 2,
    with the file open, gets the first-cut points with them — never anything outside access."""
    one = _chat(client, "U01", "Has a spouse-ground transfer request been decided before?")
    r = client.post(
        "/assist/chat",
        json={
            "message": "Draft the noting using that precedent.",
            "session_id": one["session_id"],
            "computer_no": "2894562",
        },
        headers=_h("U01"),
    )
    two = r.json()
    assert r.status_code == 200 and two["turn"] == 2 and two["first_cut"] is not None
    assert two["used_earlier_turn"]
    cut = two["first_cut"]
    assert cut["computer_no"] == "2894562" and cut["note_text"].startswith("not drafted")
    named = {d for m in re.findall(r"AP-[A-Z0-9-]+", json.dumps(two)) if (d := _doc_id(m))}
    assert named and all(MATRIX[(d, "U01")] for d in named)
    assert not named & {"D20", "D21", "D22", "D23"}
    other = client.post(  # a file the officer cannot reach: the same neutral 404 as /first-cut
        "/assist/chat",
        json={"message": "Draft the noting.", "computer_no": "9999999"},
        headers=_h("U01"),
    )
    assert other.status_code == 404
