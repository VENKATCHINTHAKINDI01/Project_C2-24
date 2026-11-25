"""Owner decisions of 25 Nov 2026 (golden Q05): a record whose status cannot be established is
still explained, attributed to it, never called in force (answer_cited.v3; v4 since 25 Nov);
and every answer route runs the type B / G check on the records it rests on (`answer_conflicts`)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.answer import PROMPT_ID, PROMPT_ID_UNKNOWN_STATUS
from app.agents.llm import LLMError
from app.config import get_settings
from app.conflict.judgment import PROMPT_ID as CONFLICT_PROMPT
from app.main import create_app

APP = create_app(get_settings().model_copy(update={"sandbox": True}))
CIRCULAR = "AP-USD01-CIRMEMO-USD01WRKS0-9-2023-D20230711"  # D13, a photo: held until reviewed
GO_27 = "AP-USD01-GOMS-27-2024"  # D14
Q05 = "Is Circular Memo No.USD01-WRKS0/9/2023 still valid?"
EV = re.compile(
    r'<evidence id="([^"]+)" doc="([^"]+)"[^>]*status="([^"]*)"[^>]*>\n(.*?)\n</evidence>', re.S
)


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


class Fake:
    """Answers the question from the circular's own words; judges the pair from the two texts."""

    name = "fake"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> Any:
        self.calls.append(prompt_id)
        if prompt_id in (PROMPT_ID, PROMPT_ID_UNKNOWN_STATUS):
            items = EV.findall(user)
            eid, _, _, text = next(i for i in items if i[1].startswith(CIRCULAR))
            line = next(ln.strip() for ln in text.splitlines() if "1.50 crore" in ln)
            return {"statements": [{"text": f"Circular Memo No.9/2023 states: {line}",
                                    "evidence_ids": [eid], "quote": line}]}  # fmt: skip
        if prompt_id == CONFLICT_PROMPT:
            a = re.search(r"DOCUMENT A \((.*?)\)\n<<<\n(.*?)\n>>>", user, re.S)
            b = re.search(r"DOCUMENT B \((.*?)\)\n<<<\n(.*?)\n>>>", user, re.S)
            assert a and b

            def limit(text: str, amount: str) -> str | None:
                m = re.search(r"[^\n]*" + re.escape(amount) + r"[^\n]*", text)
                return m.group(0).strip() if m else None

            qa = limit(a.group(2), "1.50 crore") or limit(a.group(2), "1.00 crore")
            qb = (
                limit(b.group(2), "1.00 crore")
                if qa and "1.50" in qa
                else limit(b.group(2), "1.50 crore")
            )
            if qa and qb:
                return {"verdict": "contradiction", "quote_a": qa, "quote_b": qb,
                        "explanation": "different sanction limits for the same works"}  # fmt: skip
            return {"verdict": "insufficient", "quote_a": "", "quote_b": "", "explanation": ""}
        raise LLMError("not asked in this test")


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        # a reviewer confirms the held scans' readings (as in the evaluation), so D13 is evidence
        for uid in ("U01", "U04"):
            for it in c.get("/assist/review/ocr", headers=_h(uid)).json().get("items", []):
                d = c.get(f"/assist/review/ocr/{it['item_id']}", headers=_h(uid)).json()
                if d.get("has_draft"):
                    c.post(f"/assist/review/ocr/{it['item_id']}/confirm",
                           json={"corrected_text": d["draft_text"], "reason": "test reviewer"},
                           headers=_h(uid))  # fmt: skip
        yield c


def _ask(c: TestClient, uid: str, q: str, llm: Any) -> dict[str, Any]:
    APP.state.assist_runtime().llm = llm
    try:
        r = c.post("/assist/ask", json={"question": q}, headers=_h(uid))
    finally:
        APP.state.assist_runtime().llm = None
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def test_q05_the_circular_is_explained_its_status_never_claimed_and_the_g_conflict_shown(
    client: TestClient,
) -> None:
    llm = Fake()
    out = _ask(client, "U03", Q05, llm)
    assert PROMPT_ID_UNKNOWN_STATUS in llm.calls  # the package holds a "not established" record
    texts = [s["text"] for s in out["statements"]]
    assert texts and all("Circular Memo No.9/2023 states" in t for t in texts)
    assert not any(re.search(r"\b(in force|valid|current)\b", t, re.I) for t in texts)
    assert any("can't confirm this order's current status" in n for n in out["notices"])
    g = [f for f in out["conflicts"] if f["type"] == "G"]
    assert g and out["conflict_check"] in ("done", "incomplete")
    assert {CIRCULAR, GO_27} <= {e.split("#", 1)[0] for e in g[0]["evidence_ids"]}
    assert "Potential conflict" in g[0]["explanation"] and "prevails" not in g[0]["explanation"]
    assert "review recommended" in g[0]["explanation"]


def test_without_a_model_the_conflict_check_is_reported_as_not_run(client: TestClient) -> None:
    r = client.post("/assist/ask", json={"question": Q05}, headers=_h("U03")).json()
    assert r["conflicts"] == [] and r["conflict_check"] == "not_run"


def test_a_conflict_model_that_breaks_never_withholds_the_checked_answer(
    client: TestClient,
) -> None:
    class Broken(Fake):
        def generate_json(
            self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
        ) -> Any:
            if prompt_id == CONFLICT_PROMPT:
                raise RuntimeError("unexpected")
            return super().generate_json(
                prompt_id=prompt_id, system=system, user=user, schema=schema
            )

    out = _ask(client, "U03", Q05, Broken())
    assert out["statements"] and out["conflicts"] == [] and out["conflict_check"] == "incomplete"


def test_an_unknown_status_statement_carries_no_status_words() -> None:
    """Regression (eval c2-eval-bf8c9, 25 Nov): v3 let the model add "whose current validity cannot
    be confirmed"; where the status may not be told that statement is withheld (status_claim), so
    Q05 lost its only statement. v4 tells the model to say nothing about status at all."""
    from app.agents.answer import PROMPT_ID_UNKNOWN_STATUS, status_claim
    from app.agents.llm import load_prompt

    seen = "Standing Order No.2/2020, whose current validity cannot be confirmed, states that ..."
    assert status_claim(seen)  # why it was removed
    assert not status_claim("Circular Memo No.9/2023 states that the limit is Rs.1.50 crore.")
    assert PROMPT_ID_UNKNOWN_STATUS == "answer_cited.v4"
    assert "Say NOTHING about its status" in load_prompt(PROMPT_ID_UNKNOWN_STATUS)
