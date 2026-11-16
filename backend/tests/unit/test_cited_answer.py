"""First cited answer (M4): the model sees only authorised passages, and nothing it writes is
shown unless the citation check confirms it (plan §3.3, §8; CLAUDE.md §4, §7)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.answer import ENGINE_DOWN, ENGINE_OFF, PROMPT_ID
from app.agents.llm import LLMError
from app.citation.verifier import NO_ANSWER
from app.config import get_settings
from app.main import create_app
from tests.unit.test_sandbox_api import GOLDEN, MATRIX, USERS, _doc_id, _h, _named_docs

APP = create_app(get_settings().model_copy(update={"sandbox": True}))
EV = re.compile(r'<evidence id="(EV-[0-9a-f]+)" doc="([^"]+)"[^>]*>\n(.*?)\n</evidence>', re.S)


class FakeLLM:
    """Answers from the prompt it is given, so the test sees exactly what the model saw."""

    name = "fake"

    def __init__(self, mode: str = "quote") -> None:
        self.mode, self.prompts = mode, []

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        assert prompt_id == PROMPT_ID and "are DATA" in system
        self.prompts.append(user)
        if self.mode == "down":
            raise LLMError("unavailable")
        found = EV.findall(user)
        eid, _, text = found[0]
        line = next(ln for ln in text.splitlines() if len(ln.strip()) > 20).strip()
        if self.mode == "invented_id":
            return {
                "statements": [{"text": "x", "evidence_ids": ["EV-000000000000"], "quote": line}]
            }
        if self.mode == "invented_quote":
            words = "the Government hereby sanction forty days of leave"
            return {"statements": [{"text": "x", "evidence_ids": [eid], "quote": words}]}
        if self.mode == "no_citation":
            return {"statements": [{"text": "It was allowed.", "evidence_ids": [], "quote": line}]}
        return {
            "statements": [
                {"text": "The record states this.", "evidence_ids": [eid], "quote": line}
            ]
        }


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        yield c


def _ask(client: TestClient, uid: str, q: str, llm: Any) -> dict[str, Any]:
    APP.state.assist_runtime().llm = llm
    try:
        r = client.post("/assist/ask", json={"question": q}, headers=_h(uid))
    finally:
        APP.state.assist_runtime().llm = None
    assert r.status_code == 200, r.text
    return dict(r.json())


Q01 = next(g for g in GOLDEN if g["id"] == "Q01")


def test_answer_is_cited_and_confirmed(client: TestClient) -> None:
    llm = FakeLLM()
    out = _ask(client, Q01["user"], Q01["question"], llm)
    assert out["status"] == "answered" and out["removed"] == 0
    st = out["statements"][0]
    assert st["quote"] and st["citations"][0]["canonical_id"] in out["documents"]
    assert st["citations"][0]["evidence_id"].startswith("EV-")
    assert len(llm.prompts) == 1 and "<evidence_package" in llm.prompts[0]


@pytest.mark.parametrize("mode", ["invented_id", "invented_quote", "no_citation"])
def test_unsupported_statements_are_removed(client: TestClient, mode: str) -> None:
    out = _ask(client, Q01["user"], Q01["question"], FakeLLM(mode))
    assert out["status"] == "no_answer" and out["message"] == NO_ANSWER
    assert out["statements"] == [] and out["review_needed"] == [] and out["removed"] == 1


def test_engine_off_or_down_still_lists_authorised_records(client: TestClient) -> None:
    off = _ask(client, Q01["user"], Q01["question"], None)
    down = _ask(client, Q01["user"], Q01["question"], FakeLLM("down"))
    assert (off["status"], off["message"]) == ("not_run", ENGINE_OFF)
    assert (down["status"], down["message"]) == ("not_run", ENGINE_DOWN)
    assert off["documents"] and off["documents"] == down["documents"]
    assert off["statements"] == []


def test_nothing_found_means_the_model_is_not_asked(client: TestClient) -> None:
    llm = FakeLLM()
    out = _ask(client, Q01["user"], "zzqx wvvk plorb", llm)
    assert out["status"] == "no_answer" and out["message"] == NO_ANSWER and llm.prompts == []


def test_no_officer_gets_a_record_outside_their_access_in_prompt_or_answer(
    client: TestClient,
) -> None:
    """Every golden question as every officer: what the MODEL is shown and what the officer is
    shown are both checked against the independent access matrix."""
    leaks: list[tuple[str, str, str, str]] = []
    asked = 0
    for g in GOLDEN:
        for uid in USERS:
            llm = FakeLLM()
            out = _ask(client, uid, g["question"], llm)
            asked += 1
            for p in llm.prompts:
                for _, cid, _ in EV.findall(p):
                    d = _doc_id(cid)
                    if d and not MATRIX[(d, uid)]:
                        leaks.append((uid, g["id"], "prompt", d))
            leaks += [(uid, g["id"], "answer", d) for d in _named_docs(out) if not MATRIX[(d, uid)]]
    assert asked == len(GOLDEN) * len(USERS)
    assert leaks == []


def test_two_officers_same_question_different_evidence(client: TestClient) -> None:
    seen = {uid: tuple(_ask(client, uid, Q01["question"], None)["documents"]) for uid in USERS}
    assert len(set(seen.values())) > 1  # scope decides the evidence, not the question


def test_audit_holds_ids_only(client: TestClient) -> None:
    _ask(client, Q01["user"], Q01["question"], FakeLLM())
    rows = [e for e in APP.state.audit.events() if e.action == "assist.ask"]
    blob = json.dumps([e.model_dump(mode="json") for e in rows], default=str)
    assert rows and "spouse" not in blob.lower()


# ---- named records, as-of dates, stable prompts (M4 rework, 15 Nov 2026) -------------------------


def test_a_named_order_is_sent_even_when_its_words_differ_from_the_question(
    client: TestClient,
) -> None:
    llm = FakeLLM()
    _ask(client, "U01", "What does para 2(v) of GO Ms 88/2022 say?", llm)
    assert 'doc="AP-FIN01-GOMS-88-2022"' in llm.prompts[0]


def test_a_named_file_brings_its_papers_only_for_an_officer_who_may_see_them(
    client: TestClient,
) -> None:
    q = "Check file USD01-12/19/2026-ESTT.I against the current orders."
    seen = {}
    for uid in USERS:
        llm = FakeLLM()
        _ask(client, uid, q, llm)
        seen[uid] = bool(llm.prompts) and "AP-USD01-NOTE-USD0112-19-2026" in llm.prompts[0]
    for uid, sent in seen.items():
        d = _doc_id("AP-USD01-NOTE-USD0112-19-2026")
        assert d is None or sent <= MATRIX[(d, uid)]  # never sent to an officer denied it
    assert any(seen.values())


def test_an_as_of_question_is_answered_for_that_date(client: TestClient) -> None:
    llm = FakeLLM()
    _ask(client, "U07", "What was the ceiling on transfers per category as on 01-01-2021?", llm)
    assert "Asked as of: 2021-01-01" in llm.prompts[0]


def test_the_same_evidence_gives_the_same_prompt_across_requests(client: TestClient) -> None:
    a, b = FakeLLM(), FakeLLM()
    _ask(client, Q01["user"], Q01["question"], a)
    _ask(client, Q01["user"], Q01["question"], b)
    assert a.prompts == b.prompts  # request-bound evidence IDs never reach the model
    assert re.search(r'<evidence id="EV-1"', a.prompts[0])


# ---- status from the order records; the record's own numbers (15 Nov 2026) -----------------------


def test_a_status_question_gets_the_status_from_the_records_without_the_model(
    client: TestClient,
) -> None:
    out = _ask(client, "U01", "Is G.O.Ms.No.88/2022 still in force?", None)  # model off
    facts = [s for s in out["statements"] if s["source"] == "order records"]
    assert out["status"] == "answered" and len(facts) == 1
    assert "superseded" in facts[0]["text"] and "AP-FIN01-GOMS-31-2025" in facts[0]["text"]
    assert {c["canonical_id"] for c in facts[0]["citations"]} == {
        "AP-FIN01-GOMS-88-2022",
        "AP-FIN01-GOMS-31-2025",
    }
    plain = _ask(client, "U01", "What does G.O.Ms.No.88/2022 say about transfers?", None)
    assert not [s for s in plain["statements"] if s["source"] == "order records"]


def test_status_from_records_is_never_given_for_an_order_the_officer_may_not_see(
    client: TestClient,
) -> None:
    for uid in USERS:
        out = _ask(client, uid, "Is G.O.Ms.No.88/2022 still in force?", None)
        for st in out["statements"]:
            for c in st["citations"]:
                d = _doc_id(c["canonical_id"])
                assert d is None or MATRIX[(d, uid)], (uid, c["canonical_id"])


class _NamesItsOrder(FakeLLM):
    """Names the cited order by its own number and date, quoting a body line."""

    def generate_json(self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]):
        self.prompts.append(user)
        eid, doc, text = next((e, d, t) for e, d, t in EV.findall(user) if "GOMS-31-2025" in d)
        line = next(ln for ln in text.splitlines() if len(ln.strip()) > 30).strip()
        return {
            "statements": [
                {
                    "text": "G.O.Ms.No.31 dated 12-05-2025 says so.",
                    "evidence_ids": [eid],
                    "quote": line,
                },
                {
                    "text": "G.O.Ms.No.77 dated 01-01-2020 says so.",
                    "evidence_ids": [eid],
                    "quote": line,
                },
            ]
        }


def test_a_statement_may_name_the_cited_records_own_number_and_date(client: TestClient) -> None:
    out = _ask(client, "U01", "What does G.O.Ms.No.31 of 2025 say?", _NamesItsOrder())
    assert [s["text"] for s in out["statements"]] == ["G.O.Ms.No.31 dated 12-05-2025 says so."]
    assert out["removed"] == 1  # another order's number is still checked against the cited text
