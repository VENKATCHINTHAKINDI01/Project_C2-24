"""Draft workspace (ADR-0044): formats, preparing a draft, close matches by the ladder and the
graph, checked model wording through the same client and circuit breaker, and zero disclosure."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from app.agents.dfa import ReadItem
from app.agents.llm import FailoverLLM, LLMError
from app.config import get_settings
from app.noting.draft_studio import (
    DraftInputs,
    compose,
    load_formats,
    suggest_wording,
)
from tests.unit.mock_access import MATRIX
from tests.unit.test_sandbox_api import APP, IDX, USERS, _h, _named_docs

FORMATS = load_formats(get_settings().draft_formats_path)
FILE = "1771342"  # spouse-grounds transfer request (synthetic); U01 can open it
FACTS = "Sri K. Ramesh, Senior Assistant, has requested transfer on spouse grounds."
PROPOSAL = "Government hereby permit the transfer of the individual to Regional Office, Vijayawada."


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        yield c


def _prepare(c: TestClient, uid: str, cno: str, fmt: str, **extra: Any) -> Any:
    body = {
        "computer_no": cno,
        "format_id": fmt,
        "inputs": {"facts": FACTS, "proposal": PROPOSAL, "signatory": "SECRETARY TO GOVERNMENT"},
        **extra,
    }
    return c.post("/assist/draft/prepare", json=body, headers=_h(uid))


# ---- formats ----------------------------------------------------------------------------------


def test_formats_are_listed_marked_mock_and_validated(client: TestClient, tmp_path: Path) -> None:
    r = client.get("/assist/draft/formats", headers=_h("U01"))
    assert r.status_code == 200 and r.json()["status"] == "mock"
    ids = {f["id"] for f in r.json()["formats"]}
    assert {"note_proposal", "note_dfa", "note_reference", "go_ms", "go_rt", "memo"} <= ids
    assert all(f["basis"] for f in r.json()["formats"])  # every structure says where it is from
    assert client.get("/assist/draft/formats").status_code == 401

    raw = yaml.safe_load(get_settings().draft_formats_path.read_text("utf-8"))
    bad = tmp_path / "f.yaml"
    raw["formats"][0]["saves_as"] = "dfa_draft"  # a note must save as a Yellow Note
    bad.write_text(yaml.safe_dump(raw), "utf-8")
    with pytest.raises(ValueError, match="Yellow Notes"):
        load_formats(bad)


# ---- composing: the officer's words verbatim, gaps as placeholders, nothing invented -----------


def _read(cid: str, subject: str) -> ReadItem:
    return ReadItem(
        canonical_id=cid,
        doc_type="Government Order",
        subject=subject,
        issue_date=None,
        cited_in_note=False,
        status_confirmed=True,
    )


def test_compose_keeps_the_officers_words_and_marks_every_gap() -> None:
    go = FORMATS.get("go_ms")
    assert go is not None
    empty = compose(go, DraftInputs(), department="Finance", read_list=(), label=lambda c, _: c)
    assert empty.placeholders >= 5 and "[What Government now order.]" in empty.text
    assert "G.O.Ms.No.____" in empty.text  # numbered on issue, never by the assistant
    full = compose(
        go,
        DraftInputs(
            subject="Transfers – Reg.", facts=FACTS, proposal=PROPOSAL, signatory="SECRETARY"
        ),
        department="Finance",
        read_list=(_read("AP-FIN01-GOMS-31-2025", "General Transfers 2025 – Guidelines"),),
        label=lambda c, _: f"<{c}>",
    )
    assert FACTS in full.text and PROPOSAL in full.text
    assert "Transfers – Orders – Issued." in full.text and "FINANCE DEPARTMENT" in full.text
    assert "1. <AP-FIN01-GOMS-31-2025>." in full.text
    assert "In the reference read above, orders were issued on General Transfers 2025" in full.text
    assert full.citations == ("AP-FIN01-GOMS-31-2025",)
    officer = [p.text for p in full.parts if p.origin == "officer"]
    assert any(FACTS in t for t in officer) and any(PROPOSAL in t for t in officer)
    assert full.text.splitlines()[0].startswith("DRAFT")  # watermarked


# ---- the endpoint ------------------------------------------------------------------------------


def test_a_go_reads_the_latest_order_and_flags_the_superseded_one(client: TestClient) -> None:
    r = _prepare(client, "U01", FILE, "go_ms", add_references=["AP-FIN01-GOMS-88-2022"])
    assert r.status_code == 200, r.text
    d = r.json()
    text = d["draft"]["text"]
    assert (
        FACTS in text and PROPOSAL in text and "(BY ORDER AND IN THE NAME OF THE GOVERNOR" in text
    )
    read = {i["canonical_id"]: i for i in d["read_list"]}
    assert "AP-FIN01-GOMS-31-2025" in read and "AP-FIN01-GOMS-88-2022" not in read
    assert "AP-FIN01-GOMS-88-2022" in read["AP-FIN01-GOMS-31-2025"]["in_place_of"]
    assert "(in place of G.O.Ms.No.88, Finance Department, dated 03-06-2022)" in text
    # a memo is cited by its own number, so the pre-send check can resolve it (no false type E)
    assert "Memo No.FIN01-HRPLG0(TRF)/3/2025-2" in text
    assert not [f for f in d["checks"]["flags"] if f["type"] == "E"]
    m = {x["canonical_id"]: x for x in d["matches"]["documents"]}
    old = m.get("AP-FIN01-GOMS-88-2022")
    assert old and old["standing"] == "superseded" and old["use_instead"] == "AP-FIN01-GOMS-31-2025"
    assert any(x["kind"] == "SUPERSEDES" and x["direction"] == "in" for x in old["relations"])
    assert "L2" in d["matches"]["ladder"] or "L1" in d["matches"]["ladder"]
    assert d["suggested"] is None  # wording only on request


def test_a_note_carries_provisions_and_earlier_decisions_as_quotes(client: TestClient) -> None:
    d = _prepare(client, "U01", FILE, "note_proposal").json()
    parts = d["draft"]["parts"]
    assert d["format"]["saves_as"] == "yellow_note"
    assert any(p["key"] == "precedent" and p["refs"] for p in parts)
    assert all(p["refs"] for p in parts if p["origin"] == "record")
    assert parts[0]["text"].startswith("DRAFT NOTE")


def test_unknown_format_hidden_file_and_no_identity_look_the_same(client: TestClient) -> None:
    assert _prepare(client, "U01", FILE, "go_xx").status_code == 404
    assert _prepare(client, "U01", "9999999", "go_ms").status_code == 404
    hidden = next(
        u for u in USERS if client.get(f"/sandbox/files/{FILE}", headers=_h(u)).status_code == 404
    )
    assert _prepare(client, hidden, FILE, "go_ms").status_code == 404
    r = client.post("/assist/draft/prepare", json={"computer_no": FILE, "format_id": "go_ms"})
    assert r.status_code == 401


def test_nothing_outside_the_officers_access_is_ever_named(client: TestClient) -> None:
    """Leakage, across every officer, every file they can open and every kind of format:
    read list, close matches, their relations, checks and citations."""
    leaks: list[tuple[str, str, str, str]] = []
    checked = 0
    for uid in USERS:
        files = client.get("/sandbox/files", headers=_h(uid)).json()["files"]
        for f in files[:4]:
            for fmt in ("note_proposal", "go_ms", "memo"):
                r = _prepare(
                    client,
                    uid,
                    f["computer_no"],
                    fmt,
                    add_references=["AP-FIN01-GOMS-88-2022", "AP-FIN01-GORT-1184-2025"],
                )
                assert r.status_code == 200, (uid, f["computer_no"], fmt, r.text)
                checked += 1
                leaks += [
                    (uid, f["computer_no"], fmt, d)
                    for d in _named_docs(r.json())
                    if not MATRIX[(d, uid)]
                ]
    assert checked > 20 and leaks == []


def test_an_added_reference_the_officer_cannot_see_is_just_not_found(client: TestClient) -> None:
    by_id = {
        row["id"]: key for key, row in IDX.items() if key.startswith("AP-") and "-NOTE-" not in key
    }
    hidden = next(
        (by_id[did], u)
        for (did, u), ok in MATRIX.items()
        if not ok
        and did in by_id
        and u in USERS
        and client.get("/sandbox/files", headers=_h(u)).json()["files"]
    )
    cid, uid = hidden
    cno = client.get("/sandbox/files", headers=_h(uid)).json()["files"][0]["computer_no"]
    d = _prepare(client, uid, cno, "memo", add_references=[cid]).json()
    fake = "AP-FIN01-GOMS-999-2030"  # does not exist anywhere
    e = _prepare(client, uid, cno, "memo", add_references=[fake]).json()
    assert {"cited": cid, "reason": "not found in the records available to you"} in d["left_out"]
    assert {"cited": fake, "reason": "not found in the records available to you"} in e["left_out"]
    assert d["draft"]["text"].replace(cid, fake) == e["draft"]["text"]  # hidden ≡ non-existent
    assert all(i["canonical_id"] != cid for i in d["read_list"])


def test_the_audit_keeps_ids_never_the_officers_text(client: TestClient) -> None:
    _prepare(client, "U01", FILE, "letter")
    ev = [e for e in client.app.state.audit.events() if e.action == "assist.draft.prepare"]  # type: ignore[attr-defined]
    assert ev and ev[-1].detail == "letter"
    assert all("Ramesh" not in " ".join(e.ids) + (e.detail or "") for e in ev)


# ---- a new matter: no file yet; the officer's own words are read for orders and the action

NEW_SUBJECT = "Establishment – Junior Assistant – Request for transfer on spouse grounds – Reg."
TYPED = "The individual cites G.O.Ms.No.88, Finance (HR.I-Plg. & Policy) Department, Dt.03-06-2022."


def _new(c: TestClient, uid: str, fmt: str, **inputs: str) -> Any:
    body = {"format_id": fmt, "inputs": {"subject": NEW_SUBJECT, "facts": TYPED, **inputs}}
    return c.post("/assist/draft/prepare", json=body, headers=_h(uid))


def test_a_new_matter_needs_no_file_and_reads_the_orders_the_officer_typed(
    client: TestClient,
) -> None:
    r = _new(client, "U01", "go_ms")
    assert r.status_code == 200, r.text
    d = r.json()
    read = {i["canonical_id"]: i for i in d["read_list"]}
    # the typed G.O.Ms.No.88 is read as the order now in force, and shown as replaced
    assert "AP-FIN01-GOMS-31-2025" in read and "AP-FIN01-GOMS-88-2022" not in read
    assert "AP-FIN01-GOMS-88-2022" in read["AP-FIN01-GOMS-31-2025"]["in_place_of"]
    assert TYPED in d["draft"]["text"] and NEW_SUBJECT.removesuffix(" – Reg.") in d["draft"]["text"]
    # earlier files on the same subject, only ones the officer can open, to tick as references
    rel = d["related_files"]
    assert rel and all(
        client.get(f"/sandbox/files/{f['computer_no']}", headers=_h("U01")).status_code == 200
        for f in rel
    )
    # a quoted earlier decision naming an approver is evidence, not this proposal: no type C
    note = _new(client, "U01", "note_proposal").json()
    assert any(p["key"] == "precedent" for p in note["draft"]["parts"])
    assert not [f for f in note["checks"]["flags"] if f["type"] == "C"]


def test_a_new_matter_needs_a_subject_and_an_officer(client: TestClient) -> None:
    short = {"format_id": "go_ms", "inputs": {"subject": "Transfer"}}
    assert client.post("/assist/draft/prepare", json=short, headers=_h("U01")).status_code == 422
    assert client.post("/assist/draft/prepare", json=short).status_code == 401


def test_a_new_matter_names_nothing_outside_the_officers_access(client: TestClient) -> None:
    leaks: list[tuple[str, str, str]] = []
    for uid in USERS:
        for fmt in ("note_proposal", "go_ms", "memo"):
            r = _new(client, uid, fmt)
            assert r.status_code == 200, (uid, fmt, r.text)
            d = r.json()
            leaks += [(uid, fmt, x) for x in _named_docs(d) if not MATRIX[(x, uid)]]
            for f in d["related_files"]:
                ok = client.get(f"/sandbox/files/{f['computer_no']}", headers=_h(uid))
                if ok.status_code != 200:
                    leaks.append((uid, fmt, f["computer_no"]))
    assert leaks == []


# ---- suggested wording: Gemini through the same client and circuit breaker ---------------------


class _Fake:
    def __init__(self, name: str, lines: list[dict[str, Any]] | None, fail: bool = False) -> None:
        self.name, self.lines, self.fail, self.calls = name, lines, fail, 0

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls += 1
        assert prompt_id == "draft_order.v1" and 'untrusted="true"' in user
        if self.fail:
            raise LLMError("down")
        return {"lines": self.lines}


INPUTS = DraftInputs(
    subject="Transfers", facts=FACTS, proposal="Government hereby permit the transfer for 2 years."
)
READ = (_read("AP-FIN01-GOMS-31-2025", "General Transfers 2025 – Guidelines"),)


def test_wording_keeps_only_lines_resting_on_their_sources() -> None:
    llm = _Fake(
        "gemini@asia-south1",
        [
            {"text": "Government hereby permit the transfer for 2 years.", "sources": ["S2"]},
            {
                "text": "Government hereby permit the transfer for 5 years.",
                "sources": ["S2"],
            },  # number not in source
            {
                "text": "The transfer is sanctioned on spouse grounds.",
                "sources": ["S9"],
            },  # no such source
            {
                "text": "Something else entirely about pensions and gratuity.",
                "sources": [],
            },  # uncited
        ],
    )
    got = suggest_wording(INPUTS, READ, lambda _c: "", llm)
    assert [t for t, _ in got.lines] == ["Government hereby permit the transfer for 2 years."]
    assert got.removed == 3 and got.engine == "gemini@asia-south1" and not got.fallback
    assert got.lines[0][1] == ("your proposal",)


def test_wording_needs_the_officers_own_inputs_and_an_engine() -> None:
    assert (
        suggest_wording(DraftInputs(subject="x"), READ, lambda _c: "", _Fake("g", [])).reason
        == "no_sources"
    )
    assert suggest_wording(INPUTS, READ, lambda _c: "", None).reason == "engine_off"
    assert (
        suggest_wording(INPUTS, READ, lambda _c: "", _Fake("g", None, fail=True)).reason
        == "engine_down"
    )


def test_wording_goes_through_the_circuit_breaker_and_says_when_the_fallback_wrote_it() -> None:
    line = [{"text": "Government hereby permit the transfer for 2 years.", "sources": ["S2"]}]
    primary, local = _Fake("gemini@asia-south1", line, fail=True), _Fake("local@ollama-local", line)
    breaker = FailoverLLM(primary, local, threshold=2, cooldown_s=60)
    got = suggest_wording(INPUTS, READ, lambda _c: "", breaker)
    assert got.lines and got.fallback and got.engine == "local@ollama-local"
    suggest_wording(INPUTS, READ, lambda _c: "", breaker)  # second failure: the breaker opens
    calls = primary.calls
    suggest_wording(INPUTS, READ, lambda _c: "", breaker)
    assert primary.calls == calls  # open: the primary is not tried again until the cool-down
