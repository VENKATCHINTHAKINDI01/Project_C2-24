"""Plan §14.4 failure-impact notes, one test per component: if it fails, what the system does.

| Component | If it fails | Behaviour (asserted below) |
|---|---|---|
| Authorization service | no scope | fail closed: nothing returned, neutral message |
| Document AI / extraction | not readable | held for review; nothing partial indexed |
| Canonical ID resolver | references unmatched | raw text kept; flagged (type E), never guessed |
| L2 (BigQuery passages) | no search by meaning | L0/L1/L3 still answer; the answer says so |
| Graph store (L3) | no traversal | answer without the walk; "supersession status unverified" |
| Gemini | no drafting | evidence list + deterministic facts only |
| Citation verifier | claims uncheckable | answer withheld; never an unchecked claim |
| Memorystore | no cache | served uncached, same answer |
| Query log / feedback sink | not recorded | buffer + retry; CRITICAL line when the buffer fills |
| EOfficeConnector | no file context | 503 "unavailable"; sandbox keeps working; no partial write |
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents import answer as answer_mod
from app.agents.answer import DEGRADED, UNCHECKED
from app.auth.store import StoreError
from app.cache.redis_cache import RedisAnswerCache
from app.config import get_settings
from app.connectors.eoffice import UNAVAILABLE
from app.ingestion.metadata import cited_references
from app.ingestion.pipeline import IngestionStores, IngestStatus
from app.main import create_app
from app.retrieval.ladder import LadderRung
from app.tracking.query_log import BigQueryQueryLog, QueryRecord
from app.tracking.retry_buffer import FULL, RetryBuffer
from tests.unit.test_cited_answer import Q01, FakeLLM
from tests.unit.test_ingestion_pipeline import DEPTS
from tests.unit.test_ocr import FakeEngine
from tests.unit.test_ocr import _run as ocr_run
from tests.unit.test_sandbox_api import _h

APP = create_app(get_settings().model_copy(update={"sandbox": True}))


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        c.get("/assist/notices", headers=_h("U01"))
        yield c


def _run() -> Any:
    return APP.state.assist_runtime()


def _ask(c: TestClient, q: str = Q01["question"], uid: str = Q01["user"], llm: Any = None) -> Any:
    _run().llm = llm
    try:
        r = c.post("/assist/ask", json={"question": q}, headers=_h(uid))
    finally:
        _run().llm = None
    assert r.status_code == 200, r.text
    return r.json()


class _Down:
    def __call__(self, *a: Any, **k: Any) -> Any:
        raise ConnectionError("store unreachable")


# ---- authorization ----------------------------------------------------------------------------


def test_authorization_down_fails_closed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.auth.store import InMemoryAuthzStore

    assert _ask(client)["documents"]  # works while the grants can be read

    def broken(*_a: Any, **_k: Any) -> Any:
        raise StoreError("grants unreadable")

    monkeypatch.setattr(InMemoryAuthzStore, "principal", broken)
    out = _ask(client)
    assert out["documents"] == [] and out["statements"] == []  # nothing, and nothing unscoped
    assert out["status"] == "no_answer"


# ---- Document AI / extraction -----------------------------------------------------------------


def test_extraction_down_holds_the_file_and_indexes_nothing() -> None:
    stores = IngestionStores()
    res = ocr_run(stores, "D09", FakeEngine(fail=True))
    assert res.status is IngestStatus.HELD and res.canonical_id is None
    assert not stores.history and not stores.text_of  # nothing partial is indexed


# ---- canonical ID resolver --------------------------------------------------------------------


def test_an_unmatched_reference_keeps_its_raw_text_and_is_never_guessed() -> None:
    raw = "G.O.Ms.No.4242, Imaginary Affairs Department, Dt.01-01-2020"
    refs = cited_references(f"The proposal relies on {raw}.", DEPTS, "FIN01")
    assert refs and refs[0].canonical_id is None and "4242" in refs[0].raw


# ---- L2 and L3 --------------------------------------------------------------------------------


def test_search_by_meaning_down_the_other_rungs_still_answer_and_say_so(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_run().l2, "search", _Down())
    q = "Is G.O.Ms.No.31 of 2025 of the Finance Department still in force?"
    out = _ask(client, q, uid="U01")
    assert out["documents"]  # L0 found the named order
    assert DEGRADED["L2"] in out["notices"]


def test_graph_down_answers_without_the_walk_and_says_supersession_is_unverified(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(_run().stores.graph, "walk", _Down())
    q = "Is G.O.Ms.No.31 of 2025 of the Finance Department still in force?"
    out = _ask(client, q, uid="U01")
    assert out["documents"] and DEGRADED["L3"] in out["notices"]
    # the draft workspace says so too, and quotes no earlier decision as if its orders still held
    prep = client.post(
        "/assist/draft/prepare",
        json={
            "format_id": "note_proposal",
            "inputs": {"subject": "Establishment – Request for transfer on spouse grounds – Reg."},
        },
        headers=_h("U01"),
    ).json()
    assert "L3" in prep["matches"]["unavailable"]
    assert all(m["relations"] == [] for m in prep["matches"]["documents"])
    quoted = [p["text"] for p in prep["draft"]["parts"] if p["key"] == "precedent"]
    assert quoted and all("could not be checked just now" in t for t in quoted)
    assert not any("since superseded" in t for t in quoted)  # no verdict without the walk


def test_the_ladder_reports_the_failed_rung_and_returns_nothing_from_it(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.agents.tools import draft_matches

    run = _run()
    monkeypatch.setattr(run.l2, "search", _Down())
    store = run.store_for(APP.state.adapter.officer_context("U01"))
    res = draft_matches(run.tool_context("U01", store), "transfer on spouse grounds")
    assert LadderRung.L2 in res.unavailable
    assert any(t.rung is LadderRung.L2 and t.note.startswith("unavailable") for t in res.trace)


# ---- Gemini -----------------------------------------------------------------------------------


def test_model_down_lists_the_evidence_only(client: TestClient) -> None:
    out = _ask(client, llm=FakeLLM("down"))
    assert out["status"] == "not_run" and out["documents"] and out["statements"] == []


# ---- citation verifier ------------------------------------------------------------------------


def test_verifier_down_withholds_the_answer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(answer_mod, "verify", _Down())
    out = _ask(client, llm=FakeLLM())
    assert out["message"] == UNCHECKED and out["review_needed"] == []
    # nothing the model wrote is shown; only facts the temporal engine stated (if any) remain
    assert all(s["source"] == "order records" for s in out["statements"])
    assert out["documents"]


# ---- Memorystore ------------------------------------------------------------------------------


def test_cache_down_serves_uncached() -> None:
    class Dead:
        def __getattr__(self, _name: str) -> Any:
            return _Down()

    cache = RedisAnswerCache(Dead())
    from app.auth.models import Scope

    sc = Scope(
        user_id="u",
        policy_version="t",
        classification_ranks={"UNCLASSIFIED": 0},
        public_rank=0,
        department="FIN01",
        max_rank=0,
        department_wide=True,
        sections=frozenset(),
        file_nos=frozenset(),
    )
    cache.put("q", sc, "answer", frozenset({"A"}))  # no error
    assert cache.get("q", sc) is None  # a miss: the answer is computed, not failed


# ---- tracking sinks: buffer and retry ---------------------------------------------------------


class _Sink:
    def __init__(self) -> None:
        self.up = False
        self.rows: list[dict[str, Any]] = []
        self.reject: set[int] = set()

    def __call__(self, rows: list[dict[str, Any]]) -> list[Any]:
        if not self.up:
            raise ConnectionError("BigQuery unreachable")
        errs = [{"index": i, "errors": ["bad"]} for i in range(len(rows)) if i in self.reject]
        self.rows += [r for i, r in enumerate(rows) if i not in self.reject]
        self.reject = set()
        return errs


def test_tracking_rows_are_kept_and_sent_when_the_sink_returns() -> None:
    sink = _Sink()
    buf = RetryBuffer("query_log", sink, max_rows=10)
    for n in range(3):
        buf.write({"n": n})  # sink down: nothing lost, nothing raised
    assert buf.waiting == 3 and sink.rows == []
    sink.up = True
    buf.write({"n": 3})
    assert [r["n"] for r in sink.rows] == [0, 1, 2, 3] and buf.waiting == 0  # in order


def test_a_full_buffer_drops_the_oldest_and_raises_the_alert_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    sink = _Sink()
    buf = RetryBuffer("human_action", sink, max_rows=3)
    with caplog.at_level(logging.CRITICAL):
        for n in range(5):
            buf.write({"n": n})
    assert buf.dropped == 2 and buf.waiting == 3
    assert any(FULL in r.getMessage() and "human_action" in r.getMessage() for r in caplog.records)
    sink.up = True
    buf.flush()
    assert [r["n"] for r in sink.rows] == [2, 3, 4]


def test_a_rejected_row_is_tried_once_more_then_counted() -> None:
    sink = _Sink()
    sink.up, sink.reject = True, {0}
    buf = RetryBuffer("query_log", sink)
    buf.write({"n": "bad"})
    assert buf.waiting == 1  # kept for one more try
    sink.reject = {0}
    buf.flush()
    assert buf.waiting == 0 and buf.dropped == 1 and sink.rows == []


def test_the_bigquery_query_log_never_breaks_an_answer() -> None:
    class Client:
        def __init__(self) -> None:
            self.fail = True
            self.rows: list[Any] = []

        def insert_rows_json(self, _table: str, rows: list[Any]) -> list[Any]:
            if self.fail:
                raise ConnectionError("down")
            self.rows += rows
            return []

    cl = Client()
    log_ = BigQueryQueryLog("p", "p.c2_audit.query_log", client=cl)
    rec = QueryRecord.model_validate(
        {k: v for k, v in _record().items() if k in QueryRecord.model_fields}
    )
    log_.write(rec)  # no exception
    assert log_.buffer.waiting == 1
    cl.fail = False
    log_.write(rec)
    assert len(cl.rows) == 2 and log_.buffer.waiting == 0


def _record() -> dict[str, Any]:
    import datetime as dt

    fields = QueryRecord.model_fields
    out: dict[str, Any] = {}
    for name, f in fields.items():
        if not f.is_required():
            continue
        ann = str(f.annotation)
        if "datetime" in ann:
            out[name] = dt.datetime(2026, 11, 18, tzinfo=dt.UTC)
        elif "date" in ann:
            out[name] = dt.date(2026, 11, 18)
        elif "int" in ann:
            out[name] = 1
        elif "float" in ann:
            out[name] = 0.0
        elif "bool" in ann:
            out[name] = False
        elif "tuple" in ann:
            out[name] = ()
        else:
            out[name] = "x"
    return out


# ---- e-Office connector -----------------------------------------------------------------------


def test_connector_down_assistant_says_unavailable_sandbox_keeps_working_no_partial_write(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.eoffice_mock.adapter import MockEOfficeAdapter

    before = client.get("/sandbox/files/1771342", headers=_h("U01")).json()
    drafts_before = len(before.get("drafts", []))
    monkeypatch.setattr(MockEOfficeAdapter, "file_context", _Down())
    monkeypatch.setattr(MockEOfficeAdapter, "create_draft", _Down())
    r = client.get("/assist/files/1771342/records", headers=_h("U01"))
    assert r.status_code == 503 and r.json()["detail"] == UNAVAILABLE
    body = {
        "computer_no": "1771342",
        "kind": "yellow_note",
        "body": "1. Test.",
        "citations": [],
        "request_id": "t",
    }
    assert client.post("/assist/draft", json=body, headers=_h("U01")).status_code == 503
    # the sandbox itself (e-Office) still works, and nothing was half-written
    after = client.get("/sandbox/files/1771342", headers=_h("U01"))
    assert after.status_code == 200 and len(after.json().get("drafts", [])) == drafts_before
