"""Chat history (ADR-0066): each officer's conversations, kept by the server, re-checked on read."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.memory.history import (
    ALL,
    MAX_CONVERSATIONS,
    MAX_TURNS,
    HistTurn,
    InMemoryChatHistory,
    cited_ids,
)


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


def _t(asked: str, cited: tuple[str, ...] = ()) -> HistTurn:
    return HistTurn(
        at=dt.datetime.now(dt.UTC), asked=asked, kind="chat", answer={"statements": []}, cited=cited
    )


def test_the_store_is_per_officer_and_bounded() -> None:
    h = InMemoryChatHistory()
    h.add("U01", "a" * 32, ALL, _t("first question"))
    h.add("U01", "a" * 32, ALL, _t("follow-up"))
    h.add("U02", "a" * 32, ALL, _t("someone else writing into U01's id"))  # ignored
    got = h.get("U01", "a" * 32)
    assert got is not None and [t.asked for t in got.turns] == ["first question", "follow-up"]
    assert got.title == "first question"
    assert h.get("U02", "a" * 32) is None and h.list("U02", None) == []
    for i in range(MAX_TURNS + 5):
        h.add("U01", "b" * 32, "1311050", _t(f"q{i}"))
    b = h.get("U01", "b" * 32)
    assert b is not None and len(b.turns) == MAX_TURNS and b.turns[-1].asked == f"q{MAX_TURNS + 4}"
    assert [c.conversation_id for c in h.list("U01", "1311050")] == ["b" * 32]
    for i in range(MAX_CONVERSATIONS + 3):
        h.add("U01", f"{i:032x}", ALL, _t("x"))
    assert len(h.list("U01", None)) == MAX_CONVERSATIONS
    assert h.delete("U01", f"{MAX_CONVERSATIONS + 2:032x}") and not h.delete("U02", "b" * 32)


def test_cited_ids_reads_statements_and_review() -> None:
    ans = {
        "statements": [{"citations": [{"canonical_id": "A"}, {"canonical_id": "B"}]}],
        "review_needed": [{"citations": [{"canonical_id": "A"}, {"canonical_id": "C"}]}],
    }
    assert cited_ids(ans) == ("A", "B", "C")


@pytest.fixture(scope="module")
def c() -> Iterator[TestClient]:
    app = create_app(get_settings().model_copy(update={"sandbox": True}))
    with TestClient(app) as client:
        client.get("/assist/notices", headers=_h("U01"))  # builds the runtime
        yield client


def test_a_chat_is_kept_and_continues_only_for_its_officer(c: TestClient) -> None:
    r = c.post("/assist/chat", json={"message": "transfer of teachers"}, headers=_h("U01")).json()
    sid = r["session_id"]
    c.post(
        "/assist/chat",
        json={"message": "is that still in force?", "session_id": sid},
        headers=_h("U01"),
    )
    listed = c.get("/assist/chat/history", headers=_h("U01")).json()["conversations"]
    assert listed[0]["conversation_id"] == sid and listed[0]["title"] == "transfer of teachers"
    got = c.get(f"/assist/chat/history/{sid}", headers=_h("U01")).json()
    assert [t["asked"] for t in got["turns"]] == ["transfer of teachers", "is that still in force?"]
    assert got["turns"][0]["kind"] == "chat" and got["turns"][0]["answer"]["session_id"] == sid
    # another officer: nothing listed, the id is "not available" like one that does not exist
    assert sid not in {
        x["conversation_id"]
        for x in c.get("/assist/chat/history", headers=_h("U02")).json()["conversations"]
    }
    assert c.get(f"/assist/chat/history/{sid}", headers=_h("U02")).status_code == 404
    delete = f"/assist/chat/history/{sid}/delete"
    assert c.post(delete, headers=_h("U02")).json()["deleted"] is False
    assert c.post(delete, headers=_h("U01")).json()["deleted"] is True
    assert c.get(f"/assist/chat/history/{sid}", headers=_h("U01")).status_code == 404


def test_an_answer_citing_a_record_no_longer_visible_is_withheld(c: TestClient) -> None:
    store: InMemoryChatHistory = c.app.state.chat_history  # type: ignore[attr-defined]
    sid = "c" * 32
    store.add("U01", sid, ALL, _t("about an order", cited=("AP-ZZZ01-GOMS-999-1999",)))
    got = c.get(f"/assist/chat/history/{sid}", headers=_h("U01")).json()
    assert got["turns"][0]["withheld"] is True and got["turns"][0]["answer"] is None
    assert got["turns"][0]["asked"] == "about an order"  # the officer's own words stay


def test_a_file_conversation_follows_the_file_access(c: TestClient) -> None:
    f = c.post(
        "/sandbox/files",
        json={"subject": "Chat history check", "previous_references": []},
        headers=_h("U01"),
    ).json()["file"]
    cno = f["computer_no"]
    r = c.post(
        "/assist/chat/history/tool",
        json={"computer_no": cno, "asked": "Movements", "tool": "movements"},
        headers=_h("U01"),
    )
    sid = r.json()["conversation_id"]
    got = c.get(f"/assist/chat/history/{sid}", headers=_h("U01")).json()
    assert got["place"] == cno and got["turns"][0] == {
        "at": got["turns"][0]["at"], "asked": "Movements", "kind": "tool", "tool": "movements",
        "answer": None, "withheld": False,
    }  # fmt: skip
    listed = c.get("/assist/chat/history", params={"place": cno}, headers=_h("U01")).json()
    assert [x["conversation_id"] for x in listed["conversations"]] == [sid]
    # an officer who cannot open the file: the same 404 as every file route
    assert (
        c.get("/assist/chat/history", params={"place": cno}, headers=_h("U03")).status_code == 404
    )
    assert (
        c.post(
            "/assist/chat/history/tool",
            json={"computer_no": cno, "asked": "Movements", "tool": "movements"},
            headers=_h("U03"),
        ).status_code
        == 404
    )


def test_settings_clear_removes_only_this_officers_chats(c: TestClient) -> None:
    store: InMemoryChatHistory = c.app.state.chat_history  # type: ignore[attr-defined]
    store.add("U01", "d" * 32, ALL, _t("mine"))
    store.add("U02", "e" * 32, ALL, _t("theirs"))
    n = c.post("/assist/chat/history/clear", headers=_h("U01")).json()["cleared"]
    assert n >= 1 and store.list("U01", None) == []
    assert [x.conversation_id for x in store.list("U02", None)] == ["e" * 32]


def test_intent_without_a_model_says_use_the_rules(c: TestClient) -> None:
    ask = {"message": "prepare a draft note for approval", "tools": ["dfa"]}
    r = c.post("/assist/intent", json=ask, headers=_h("U01")).json()
    assert r["tool"] is None and r["by"] == "rules"
    other = {"message": "movements", "computer_no": "999999", "tools": ["movements"]}
    assert c.post("/assist/intent", json=other, headers=_h("U01")).status_code == 404


def test_draft_autofill_without_a_model_leaves_the_inputs_to_the_officer(c: TestClient) -> None:
    f = c.post(
        "/sandbox/files",
        json={"subject": "Autofill check", "previous_references": []},
        headers=_h("U01"),
    ).json()["file"]
    body = {"computer_no": f["computer_no"], "format_id": "go_rt"}
    r = c.post("/assist/draft/autofill", json=body, headers=_h("U01")).json()
    assert r["inputs"] == {} and r["reason"] == "model not configured"
    assert c.post("/assist/draft/autofill", json=body, headers=_h("U03")).status_code == 404
    other = {"computer_no": f["computer_no"], "format_id": "no_such_format"}
    assert c.post("/assist/draft/autofill", json=other, headers=_h("U01")).status_code == 404
