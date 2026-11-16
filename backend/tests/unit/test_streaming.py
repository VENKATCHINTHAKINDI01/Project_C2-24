"""Streamed answers (ADR-0033): progress first, then each statement only after it passed the
citation check, then `done` with exactly the one-piece answer. Never the model's unchecked
words, never anything from a record the officer may not see."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.llm import stream_json
from app.agents.streaming import StatementStream
from tests.unit.test_cited_answer import EV
from tests.unit.test_orchestrator import APP, _h

INVENTED = "the Government hereby sanction forty days of leave"


class StreamingFake:
    """Writes two supported statements around an invented one, a few characters at a time."""

    name = "stream-fake"

    def __init__(self) -> None:
        self.chunks = 0

    def _answer(self, user: str) -> dict[str, Any]:
        eid, _, text = EV.findall(user)[0]
        line = next(ln for ln in text.splitlines() if len(ln.strip()) > 20).strip()
        return {
            "statements": [
                {"text": "First {checked} point.", "evidence_ids": [eid], "quote": line},
                {"text": "An invented point.", "evidence_ids": [eid], "quote": INVENTED},
                {"text": 'Second "checked" point.', "evidence_ids": [eid], "quote": line},
            ]
        }

    def generate_json(self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]):
        if prompt_id.startswith("noting_draft"):
            return {"sections": []}
        return self._answer(user)

    def stream_json(
        self,
        *,
        prompt_id: str,
        system: str,
        user: str,
        schema: dict[str, Any],
        on_text: Callable[[str], None],
    ) -> dict[str, Any]:
        out = self.generate_json(prompt_id=prompt_id, system=system, user=user, schema=schema)
        text = json.dumps(out)
        for i in range(0, len(text), 7):
            self.chunks += 1
            on_text(text[i : i + 7])
        return out


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        APP.state.assist_runtime().llm = StreamingFake()
        try:
            yield c
        finally:
            APP.state.assist_runtime().llm = None


def _events(c: TestClient, uid: str, message: str) -> list[dict[str, Any]]:
    with c.stream("POST", "/assist/chat/stream", json={"message": message}, headers=_h(uid)) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    out = []
    for block in body.strip().split("\n\n"):
        name, data = block.split("\n", 1)
        e = json.loads(data.removeprefix("data: "))
        assert name == f"event: {e['type']}"
        out.append(e)
    return out


def test_statements_arrive_one_by_one_and_only_after_the_check(client: TestClient) -> None:
    # a question no other test asks (the scoped answer cache would answer it at once)
    ev = _events(client, "U01", "What does G.O.Ms.No.88/2022 lay down for streaming checks?")
    kinds = [e["type"] for e in ev]
    assert kinds[0] == "stage" and ev[0]["stage"] == "searching"
    assert kinds[-1] == "done"
    stages = [e["stage"] for e in ev if e["type"] == "stage"]
    assert stages[:2] == ["searching", "found"] and "writing" in stages and "checking" in stages
    streamed = [e["statement"]["text"] for e in ev if e["type"] == "statement"]
    assert "First {checked} point." in streamed and 'Second "checked" point.' in streamed
    assert "An invented point." not in streamed  # failed the check: never shown
    assert kinds.index("statement") < kinds.index("done")
    final = ev[-1]["answer"]
    assert {s["text"] for s in final["statements"]} >= set(streamed)  # the final answer covers it
    assert final["removed"] == 1 and final["session_id"]


def test_the_streamed_turn_is_the_same_turn_as_chat(client: TestClient) -> None:
    q = "What does G.O.Ms.No.88/2022 say about transfers?"
    done = _events(client, "U03", q)[-1]["answer"]
    plain = client.post("/assist/chat", json={"message": q}, headers=_h("U03")).json()
    same = ("status", "statements", "removed", "documents", "review_needed")
    assert {k: done[k] for k in same} == {k: plain[k] for k in same}


def test_signed_out_or_unknown_officer_never_opens_a_stream(client: TestClient) -> None:
    r = client.post("/assist/chat/stream", json={"message": "x"})
    assert r.status_code in (401, 403)
    r = client.post("/assist/chat/stream", json={"message": "x"}, headers=_h("NOBODY"))
    assert r.status_code in (401, 403)


def test_a_failure_inside_ends_with_the_neutral_message(client: TestClient) -> None:
    run = APP.state.assist_runtime()

    class Broken(StreamingFake):
        def stream_json(self, **kw: Any) -> dict[str, Any]:
            raise RuntimeError("secret detail from inside")

    run.llm = Broken()
    try:
        # a question not asked before (no saved answer in the scoped cache)
        ev = _events(client, "U02", "What does G.O.Ms.No.88/2022 say about transfers?")
    finally:
        run.llm = StreamingFake()
    assert ev[-1]["type"] == "error"
    assert "secret" not in json.dumps(ev)


# --- the incremental reader ---------------------------------------------------------------


def test_objects_are_found_however_the_text_is_cut() -> None:
    doc = {
        "statements": [
            {"text": 'a } b { "c"', "evidence_ids": ["EV-1"], "quote": "x\\y"},
            {"text": "two", "evidence_ids": [], "quote": None},
        ],
        "other": [{"text": "not a statement"}],
    }
    text = json.dumps(doc)
    for size in (1, 2, 5, 13, len(text)):
        s, got = StatementStream(), []
        for i in range(0, len(text), size):
            got += s.feed(text[i : i + size])
        assert got == doc["statements"], size


def test_without_a_listener_nothing_changes() -> None:
    class Plain:
        name = "plain"

        def generate_json(self, **kw: Any) -> dict[str, Any]:
            return {"statements": []}

    seen: list[str] = []
    assert stream_json(Plain(), prompt_id="p", system="s", user="u", schema={}) == {
        "statements": []
    }
    stream_json(Plain(), prompt_id="p", system="s", user="u", schema={}, on_text=seen.append)
    assert seen == ['{"statements": []}']  # a client that cannot stream hands over its answer
