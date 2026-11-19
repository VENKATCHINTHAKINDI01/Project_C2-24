"""Drafting from the file itself (ADR-0060): the request and verified facts quoted from the file's
notes with paragraph citations, numbering continued from the file, only substantive provisions
quoted, orders cited in earlier notes carried forward and checked, related files, order history
and people records beside the draft — all within the officer's access."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.first_cut import substantive
from app.config import get_settings
from app.noting.chain import NoteEntry
from app.noting.draft_studio import DraftInputs, compose, load_formats
from app.noting.file_facts import file_facts
from tests.unit.mock_access import MATRIX
from tests.unit.test_sandbox_api import APP, IDX, USERS, _h, _named_docs

FORMATS = load_formats(get_settings().draft_formats_path)
NAVEEN = "2894562"  # USD01-12/19/2026-ESTT.I, spouse-grounds request (synthetic); U01 opens it
NAVEEN_FILE = "USD01-12/19/2026-ESTT.I"
SRC = "AP-USD01-NOTE-TEST-1-2026"


def _note(no: int, paras: list[tuple[int, str]]) -> NoteEntry:
    return NoteEntry(
        note_no=no,
        paragraphs=(paras[0][0], paras[-1][0]) if paras else None,
        text="\n".join(t for _, t in paras),
        signer=None,
        post=None,
        signed_at=None,
        source=SRC,
        by_paragraph=tuple(paras),
    )


NOTES = [
    _note(
        1,
        [
            (
                1,
                "1. Sri A. Test, Senior Assistant, has requested transfer on spouse grounds"
                " (Flag A).",
            ),
            (2, "2. As per para 2(v) of G.O.Ms.No.31, spouse cases may be considered."),
            (3, "3. As verified, the station period of the individual is 3 years."),
        ],
    ),
    _note(2, [(4, "4. Put up."), (5, "5. It is verified that no disciplinary case is pending.")]),
]


# ---- file facts: deterministic, quoted, cited by paragraph ------------------------------------


def test_the_request_and_verified_facts_are_quoted_with_their_paragraphs() -> None:
    ff = file_facts(reversed(NOTES))  # order of the input does not matter
    assert [(p.note_no, p.paragraph) for p in ff.request] == [(1, 1)]
    assert [(p.note_no, p.paragraph) for p in ff.facts] == [(1, 3), (2, 5)]
    assert ff.request[0].ref == f"{SRC}#note-1-para-1"
    assert ff.last_paragraph == 5 and ff.next_paragraph == 6
    # a paragraph that only restates an order is not the request
    assert all("G.O.Ms" not in p.text for p in ff.request)
    assert file_facts([]).next_paragraph == 1 and file_facts([]).request == ()
    assert len(file_facts(NOTES, max_facts=1).facts) == 1


def test_compose_quotes_the_file_numbers_on_and_the_officers_words_win() -> None:
    fmt = FORMATS.get("note_proposal")
    assert fmt is not None
    ff = file_facts(NOTES)
    d = compose(
        fmt,
        DraftInputs(),
        department="Urban Services",
        read_list=(),
        label=lambda c, _: c,
        file_facts=ff,
    )
    req = next(p for p in d.parts if p.key == "request")
    assert req.origin == "record" and req.refs == (f"{SRC}#note-1-para-1",)
    assert (
        req.text.startswith('6. As recorded in Note #1, para 1: "') and "has requested" in req.text
    )
    facts = [p for p in d.parts if p.key == "facts"]
    assert facts and all(p.origin == "record" and p.refs for p in facts)
    nums = [
        int(m.group(1))
        for p in d.parts
        if (m := re.match(r"(\d+)\. ", p.text)) and p.key != "reference"
    ]
    assert nums[0] == 6 and nums == list(range(6, 6 + len(nums)))  # one unbroken run from the file
    own = compose(
        fmt,
        DraftInputs(request="The officer's own statement of the request."),
        department="Urban Services",
        read_list=(),
        label=lambda c, _: c,
        file_facts=ff,
    )
    req = next(p for p in own.parts if p.key == "request")
    assert req.origin == "officer" and "officer's own statement" in req.text
    # other formats start at 1: an order or memo has its own numbering
    go = FORMATS.get("go_ms")
    assert go is not None
    g = compose(
        go, DraftInputs(), department="Finance", read_list=(), label=lambda c, _: c, file_facts=ff
    )
    assert "As recorded in Note" not in g.text


def test_only_substantive_provisions_are_quoted() -> None:
    assert not substantive("1. Government have examined the matter and read the following.")
    assert not substantive("1. In the G.O. 1st read above, orders were issued on transfers.")
    assert substantive("(iii) No officer below the rank of Secretary shall order transfers.")
    assert substantive("(v) Spouse cases shall be considered on priority.")


def _doc_of(canonical_id: str) -> str:
    """The corpus document (D-number) of a note's canonical ID."""
    return str(IDX[canonical_id]["id"])


# ---- the endpoint ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        yield c


def _prepare(c: TestClient, uid: str, cno: str, fmt: str = "note_proposal") -> Any:
    return c.post(
        "/assist/draft/prepare", json={"computer_no": cno, "format_id": fmt}, headers=_h(uid)
    )


def test_a_note_on_an_open_file_is_drafted_from_the_file(client: TestClient) -> None:
    r = _prepare(client, "U01", NAVEEN)
    assert r.status_code == 200, r.text
    d = r.json()
    parts = d["draft"]["parts"]
    req = next(p for p in parts if p["key"] == "request")
    assert req["origin"] == "record" and "#note-1-para-1" in req["refs"][0]
    assert "Naveen Kumar" in req["text"] and req["text"].startswith("6. ")
    assert any(p["key"] == "facts" and "As verified" in p["text"] for p in parts)
    # relevance: operative clauses only, never a preamble ("Government have examined …", para 1).
    # G.O.19 is a held scan here: its clauses appear only after OCR review, which is correct.
    prov = [p["text"] for p in parts if p["key"] == "provision"]
    assert any("G.O.Ms.No.31" in t and "para 2(v)" in t for t in prov)
    assert not any(re.search(r"para 1 provides", t) for t in prov)
    assert not any("G.O.Ms.No.19" in t for t in prov)  # unreviewed scan: not trusted evidence
    # carried forward: G.O.88 cited earlier is replaced by G.O.31; G.O.104/2026 is not found
    carried = " ".join(p["text"] for p in parts if p["key"] == "carried")
    assert "G.O.Ms.No.88" in carried and "has since been replaced" in carried
    assert "104" in carried and "not found in the records available to you" in carried
    assert all(p["origin"] == "check" for p in parts if p["key"] == "carried")
    # related files: never the file itself, each one the officer can open
    rel = d["related_files"]
    assert rel and all(f["file_no"] != NAVEEN_FILE for f in rel)
    for f in rel:
        assert (
            client.get(f"/sandbox/files/{f['computer_no']}", headers=_h("U01")).status_code == 200
        )
    # order history of what is read; status only when covered
    hist = {h["order"]: h for h in d["context"]["histories"]}
    g31 = hist["AP-FIN01-GOMS-31-2025"]
    assert any("superseded G.O.Ms.No.88" in ln["text"] for ln in g31["lines"])
    assert g31["status_reportable"] or g31["in_force"] == []
    # people: persons only (no offices); records from this file are already quoted above
    for p in d["context"]["people"]:
        assert p["records"] and all(NAVEEN_FILE not in lbl for _, lbl in p["records"])
        assert not p["name"].startswith("Regional Office")


def test_drafting_from_the_file_names_nothing_outside_access(client: TestClient) -> None:
    """Every officer, every file they can open: file facts, carried checks, related files, order
    history and people name only records the officer may see; a hidden file is a 404."""
    leaks: list[tuple[str, str, str]] = []
    checked = 0
    for uid in USERS:
        files = client.get("/sandbox/files", headers=_h(uid)).json()["files"]
        for f in files[:6]:
            r = _prepare(client, uid, f["computer_no"])
            assert r.status_code == 200, (uid, f["computer_no"], r.text)
            checked += 1
            got = r.json()
            body = {
                k: got[k] for k in ("draft", "related_files", "context", "left_out", "file_facts")
            }
            # a note's own words, quoted verbatim, are the authorised document itself (as on the
            # file page; it may mention a file the officer cannot open): the quote must come from
            # a note the officer may read, and the rest of the response is checked without it
            ff = got["file_facts"] or {}
            quoted = [
                *ff.get("request", []),
                *ff.get("facts", []),
                *(x["paragraph"] for x in ff.get("review", [])),
            ]
            for q in quoted:
                assert MATRIX[(_doc_of(q["source"]), uid)], (uid, q["source"])
            flat = json.dumps(body, ensure_ascii=False)
            for q in quoted:
                for t in (q["text"], re.sub(r"^\s*\d{1,3}[.)]\s*", "", q["text"])):
                    flat = flat.replace(json.dumps(t, ensure_ascii=False)[1:-1], "")
            leaks += [(uid, f["computer_no"], x) for x in _named_docs(flat) if not MATRIX[(x, uid)]]
            for rf in r.json()["related_files"]:
                assert (
                    client.get(f"/sandbox/files/{rf['computer_no']}", headers=_h(uid)).status_code
                    == 200
                )
    assert checked > 15 and leaks == []
    hidden = next(
        u for u in USERS if client.get(f"/sandbox/files/{NAVEEN}", headers=_h(u)).status_code == 404
    )
    assert _prepare(client, hidden, NAVEEN).status_code == 404


# ---- suggested wording: the file's paragraphs as sources, checked, with cost controls ---------


class _Recorder:
    """A model stand-in: records each call and answers with fixed lines."""

    name = "gemini@asia-south1"

    def __init__(self, lines: list[dict[str, Any]]) -> None:
        self.lines, self.calls = lines, []  # type: list[dict[str, Any]], list[str]

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls.append(prompt_id)
        self.user = user
        return {"sections": [{"heading": "Background", "lines": self.lines}]}


def _file_source(user: str, words: str) -> str:
    """The source id the prompt gives the file paragraph containing `words`."""
    m = re.search(r'<source id="(S\d+)" kind="file">\n[^<]*' + re.escape(words), user)
    assert m, user[:400]
    return m.group(1)


def test_wording_from_the_file_cites_its_paragraphs_and_drops_invented_facts() -> None:
    from app.agents.first_cut import CitedPoint, FirstCut
    from app.noting.drafter import PROMPT_ID, PROMPT_ID_FILE, draft_note

    point = CitedPoint.model_construct(
        topic="Spouse cases",
        clause_id="AP-X-GOMS-1-2025#para-2",
        text="Spouse cases shall be considered.",
    )
    cut = FirstCut.model_construct(
        file_no="F/1/2026",
        draft_note=None,
        ground=None,
        orders=(),
        left_out=(),
        points=(point,),
        precedents=(),
        flags=(),
        body="",
        citations=(),
    )
    ff = file_facts(NOTES)
    probe = _Recorder([])
    draft_note(cut, "Transfer request", probe, [*ff.request, *ff.facts])
    req = _file_source(probe.user, "has requested transfer")
    ver = _file_source(probe.user, "station period")
    llm = _Recorder(
        [
            {
                "text": "Sri A. Test, Senior Assistant, has requested transfer on spouse grounds.",
                "sources": [req],
            },
            {
                "text": "As verified, the station period of the individual is 3 years.",
                "sources": [ver],
            },
            {
                "text": "As verified, the station period of the individual is 5 years.",
                "sources": [ver],
            },
            {"text": "No disciplinary case is pending against the individual.", "sources": [req]},
        ]
    )
    note = draft_note(cut, "Transfer request", llm, [*ff.request, *ff.facts])
    assert llm.calls == [PROMPT_ID_FILE]
    kept = [ln for s in note.sections for ln in s.lines]
    assert [ln.text for ln in kept][:2] == [
        "Sri A. Test, Senior Assistant, has requested transfer on spouse grounds.",
        "As verified, the station period of the individual is 3 years.",
    ]
    assert kept[0].refs == (f"{SRC}#note-1-para-1",)
    assert note.removed == 2  # a number not in the file; a fact the cited paragraph does not state
    # without file paragraphs the request is exactly the v2 one (recorded answers stay valid)
    plain = _Recorder([])
    draft_note(cut, "Transfer request", plain)
    assert plain.calls == [PROMPT_ID] and 'kind="file"' not in plain.user


def test_the_daily_quota_counts_per_officer_and_resets_each_day() -> None:
    import datetime as dt

    from app.tracking.model_usage import IST, InMemoryModelUsage, ModelQuota

    now = [dt.datetime(2026, 11, 19, 23, 50, tzinfo=IST)]
    q = ModelQuota(InMemoryModelUsage(), 2, now=lambda: now[0])
    assert q.take("U01") == 1 and q.take("U01") == 2 and q.take("U01") is None
    assert q.take("U02") == 1  # another officer has their own count
    now[0] += dt.timedelta(minutes=20)  # past midnight IST
    assert q.take("U01") == 1 and q.used("U01") == 1
    assert ModelQuota(InMemoryModelUsage(), 0).take("U01") is None  # 0: wording is off


def test_a_live_call_is_bounded_in_output_and_time() -> None:
    from app.agents.llm import GeminiVertexClient, llm_from_settings

    captured: dict[str, Any] = {}

    class _Models:
        def generate_content(self, *, model: str, contents: str, config: Any) -> Any:
            captured["config"] = config
            return type("R", (), {"text": "{}"})()

    sdk = type("C", (), {"models": _Models()})()
    pytest.importorskip("google.genai")
    c = GeminiVertexClient(
        "p", "asia-south1", "gemini-x", client=sdk, timeout_s=20, max_output_tokens=1024
    )
    c.generate_json(prompt_id="x", system="s", user="u", schema={"type": "object"})
    assert captured["config"].max_output_tokens == 1024 and c.timeout_s == 20
    s = get_settings().model_copy(
        update={
            "llm_provider": "vertex",
            "gcp_project_id": "p",
            "gcp_region": "asia-south1",
            "llm_timeout_s": 25.0,
            "llm_max_output_tokens": 2048,
        }
    )
    live = llm_from_settings(s)
    inner = getattr(live, "live", None) or getattr(live, "_live", None)
    assert inner is not None and inner.max_output_tokens == 2048 and inner.timeout_s == 25.0


def test_past_the_daily_limit_the_draft_is_prepared_without_wording() -> None:
    import datetime as dt

    from app.main import create_app

    app = create_app(
        get_settings().model_copy(update={"sandbox": True, "draft_wording_per_day": 1})
    )
    with TestClient(app) as c:
        llm = _Recorder([])
        app.state.assist_runtime().llm = llm
        try:
            body = {"computer_no": NAVEEN, "format_id": "note_proposal", "suggest": True}
            first = c.post("/assist/draft/prepare", json=body, headers=_h("U01")).json()
            second = c.post("/assist/draft/prepare", json=body, headers=_h("U01")).json()
            other = c.post("/assist/draft/prepare", json=body, headers=_h("U02"))
        finally:
            app.state.assist_runtime().llm = None
    assert first["suggested"]["reason"] != "daily_limit" and len(llm.calls) >= 1
    assert "noting_draft.v3" in llm.calls  # the file's own paragraphs went with the request
    assert second["suggested"]["reason"] == "daily_limit" and second["draft"]["parts"]
    assert first["suggested"]["usage"] == {"used": 1, "limit": 1}
    log = app.state.model_usage.entries(dt.datetime(2000, 1, 1, tzinfo=dt.UTC))
    mine = [e for e in log if e.user_id == "U01"]
    assert [e.outcome for e in mine][-1] == "daily_limit" and mine[0].outcome != "daily_limit"
    assert mine[0].prompt_id == "noting_draft.v3" and mine[0].target == NAVEEN
    assert mine[0].used_today == 1 and mine[-1].engine is None  # no call past the limit
    assert other.status_code in (200, 404)  # another officer's count is their own
    if other.status_code == 200:
        assert other.json()["suggested"]["reason"] != "daily_limit"


def test_a_replay_only_engine_keeps_the_recorded_request() -> None:
    from app.main import create_app

    app = create_app(get_settings().model_copy(update={"sandbox": True}))
    with TestClient(app) as c:
        llm = _Recorder([])
        llm.replays_only = True  # type: ignore[attr-defined]
        app.state.assist_runtime().llm = llm
        try:
            body = {"computer_no": NAVEEN, "format_id": "note_proposal", "suggest": True}
            assert c.post("/assist/draft/prepare", json=body, headers=_h("U01")).status_code == 200
        finally:
            app.state.assist_runtime().llm = None
    assert "noting_draft.v2" in llm.calls and "noting_draft.v3" not in llm.calls
