"""Conflict types B / G by grounded judgment (plan §6.5): the deterministic frame around the model.
No GCP calls: a fake model answers; the cache and replay engines are tested on disk."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.agents.llm import (
    CachingLLM,
    FailoverLLM,
    GeminiVertexClient,
    LLMError,
    OllamaClient,
    RecordedLLM,
    llm_from_settings,
)
from app.config import Settings
from app.conflict.deterministic import ConflictType
from app.conflict.judgment import Evidence, contradiction_flags, excerpt, settled_pairs
from app.temporal.engine import RelationKind, TemporalRelation

GO = Evidence(
    canonical_id="AP-ESE01-GOMS-54-2020",
    level=4,
    text="ORDER: For the purpose of transfers more than half the Academic year would be considered "
    "as a complete full year.",
)
CIR1 = Evidence(
    canonical_id="AP-ESE01-CIRMEMO-SYNESE01GEN-41-2020-D20201020",
    level=7,
    text="Only completed academic years shall be counted; part of a year shall be ignored.",
)
CIR2 = Evidence(
    canonical_id="AP-ESE01-CIRMEMO-SYNESE01GEN-44-2020-D20201027",
    level=7,
    text="More than half of an academic year shall be counted as a full year.",
)
GO2 = Evidence(canonical_id="AP-ESE01-GOMS-55-2020", level=4, text="Another order.")


class Fake:
    """Says 'contradiction' with the given quotes, or raises; records what it was asked."""

    name = "fake"

    def __init__(self, answers: dict[str, dict[str, Any]] | None = None, fail: bool = False):
        self.answers, self.fail = answers or {}, fail
        self.users: list[str] = []

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        self.users.append(user)
        if self.fail:
            raise LLMError("unavailable")
        for key, ans in self.answers.items():
            if key in user:
                return ans
        return {"verdict": "consistent", "quote_a": "", "quote_b": "", "explanation": ""}


def test_lower_instrument_against_a_go_is_type_g_with_both_quotes() -> None:
    fake = Fake(
        {
            CIR1.canonical_id: {
                "verdict": "contradiction",
                "quote_a": "more than half the Academic year would be considered as a complete "
                "full year",
                "quote_b": "Only completed academic years shall be counted",
                "explanation": "How a part year counts.",
            }
        }
    )
    res = contradiction_flags([GO, CIR1], fake)
    assert res.asked == 1 and res.failed == 0
    assert [f.type for f in res.flags] == [ConflictType.G]
    f = res.flags[0]
    assert not f.certain and set(f.evidence_ids) == {GO.canonical_id, CIR1.canonical_id}
    assert f.explanation.index(CIR1.canonical_id) < f.explanation.index(
        GO.canonical_id
    )  # lower first


def test_two_instruments_of_the_same_level_are_type_b() -> None:
    fake = Fake(
        {
            CIR2.canonical_id: {
                "verdict": "contradiction",
                "quote_a": "Only completed academic years shall be counted",
                "quote_b": "More than half of an academic year shall be counted as a full year",
                "explanation": "x",
            }
        }
    )
    res = contradiction_flags([CIR1, CIR2], fake)
    assert [f.type for f in res.flags] == [ConflictType.B]


def test_a_quote_not_in_the_text_is_dropped() -> None:
    fake = Fake(
        {
            CIR1.canonical_id: {
                "verdict": "contradiction",
                "quote_a": "a sentence the order never contains at all",
                "quote_b": "Only completed academic years shall be counted",
                "explanation": "x",
            }
        }
    )
    assert contradiction_flags([GO, CIR1], fake).flags == ()


def test_a_quote_differing_only_in_spaces_around_a_hyphen_still_counts() -> None:
    """OCR breaks "self-declaration" as "self -\ndeclaration"; the model writes "self -declaration"
    (FIN 139/2024, prompt v2 run). Only spacing is forgiven, never a word."""
    go = Evidence(
        canonical_id="AP-GAZ-GAZETTE-EI-3880-2024",
        level=3,
        text="b. above 8% and up to 15% of basic pay, on self -\ndeclaration and compulsory "
        "medical examination.",
    )
    cir = Evidence(
        canonical_id="AP-FIN01-CIRMEMO-X-14-2024",
        level=7,
        text="Enhancement up to 15% of basic pay may be allowed on self-declaration.",
    )
    ans = {
        "verdict": "contradiction",
        "quote_a": "above 8% and up to 15% of basic pay, on self -declaration and compulsory "
        "medical examination.",
        "quote_b": "Enhancement up to 15% of basic pay may be allowed on self-declaration.",
        "explanation": "x",
    }
    assert [f.type for f in contradiction_flags([go, cir], Fake({go.canonical_id: ans})).flags] == [
        ConflictType.G
    ]
    bad = {**ans, "quote_a": "above 8% and up to 20% of basic pay, on self-declaration"}
    assert contradiction_flags([go, cir], Fake({go.canonical_id: bad})).flags == ()


def test_pairs_not_asked_two_orders_or_linked() -> None:
    fake = Fake()
    assert contradiction_flags([GO, GO2], fake).asked == 0
    linked = [frozenset((GO.canonical_id, CIR1.canonical_id))]
    assert contradiction_flags([GO, CIR1], fake, linked).asked == 0
    assert fake.users == []


def test_only_an_inferred_supersession_leaves_a_pair_open() -> None:
    """FIN 106/2019: two same-subject circulars got an unconfirmed supersession inferred from the
    subject alone (§7.3); that must not hide the contradiction between them."""
    a, b, c, d = "AP-X-1", "AP-X-2", "AP-X-3", "AP-X-4"
    rels = [
        TemporalRelation(source=b, kind=RelationKind.SUPERSEDES, target=a, confirmed=False),
        TemporalRelation(source=d, kind=RelationKind.AMENDS, target=c, confirmed=False),
        TemporalRelation(source=c, kind=RelationKind.SUPERSEDES, target=a, confirmed=True),
    ]
    assert settled_pairs(rels) == [frozenset((c, d)), frozenset((a, c))]


def test_model_failure_marks_the_check_incomplete() -> None:
    res = contradiction_flags([GO, CIR1], Fake(fail=True))
    assert res.flags == () and res.failed == 1


def test_document_text_is_sent_as_delimited_data_only_for_the_pair() -> None:
    fake = Fake()
    contradiction_flags([GO, CIR1], fake)
    (user,) = fake.users
    assert "<<<" in user and ">>>" in user and GO2.text not in user


def test_long_orders_are_cut_to_the_passages_that_matter() -> None:
    long = "HEADER\n" + "\n\n".join(f"Paragraph {i} about pension rules." for i in range(400))
    long += "\n\nThe academic year counting rule is here."
    out = excerpt(long, "academic year counting")
    assert len(out) <= 6000 and "academic year counting rule" in out


def test_an_ocr_text_without_paragraph_breaks_still_yields_the_clause() -> None:
    """OCR'd rules come as one long run of lines; the old paragraph split skipped them whole."""
    lines = [
        f"Rule {i}. The officer shall maintain register number {i} in the office."
        for i in range(300)
    ]
    lines.insert(250, "Rule 250A. More than half the academic year shall count as a complete year.")
    out = excerpt("\n".join(lines), "how a part of the academic year counts")
    assert len(out) <= 6000 and "More than half the academic year" in out
    assert out.startswith("Rule 0.")  # the head (number, date, subject) is always kept


def test_rare_words_outrank_boilerplate() -> None:
    boiler = "\n".join("Government of Andhra Pradesh order department" for _ in range(400))
    text = boiler + "\nPension commutation is restored after fifteen years.\n" + boiler
    out = excerpt(text, "Government Andhra Pradesh order department commutation restored")
    assert "commutation is restored after fifteen years" in out


def test_the_note_steers_the_excerpt_but_is_never_sent() -> None:
    long = "HEAD\n" + "\n".join(f"Clause {i} on leave travel." for i in range(600))
    long += "\nClause X: the seniority list is drawn up every January.\n"
    go = Evidence(canonical_id="AP-ESE01-GOMS-9-2020", level=4, text=long)
    cir = Evidence(canonical_id="AP-ESE01-CIRMEMO-X-1-2020", level=7, text="Short circular.")
    fake = Fake()
    note = "Proposal on the SENIORITY list prepared in January, private remark 4711."
    contradiction_flags([go, cir], fake, context=note)
    (user,) = fake.users
    assert "seniority list is drawn up every January" in user and "4711" not in user


class FakeLive(GeminiVertexClient):
    def __init__(self) -> None:
        super().__init__("p", "asia-south1", "gemini-3.5-flash", client=object())
        self.calls = 0

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls += 1
        return {"verdict": "consistent"}


def test_cache_pays_once_and_replay_needs_no_calls(tmp_path: Path) -> None:
    live = FakeLive()
    cached = CachingLLM(live, tmp_path)
    kw: dict[str, Any] = {"prompt_id": "p.v1", "system": "s", "user": "u", "schema": {}}
    assert cached.generate_json(**kw) == cached.generate_json(**kw) == {"verdict": "consistent"}
    assert live.calls == 1
    assert RecordedLLM(tmp_path, "gemini-3.5-flash").generate_json(**kw) == {
        "verdict": "consistent"
    }
    with pytest.raises(LLMError):
        RecordedLLM(tmp_path, "gemini-3.5-flash").generate_json(**{**kw, "user": "other"})


def test_settings_pick_the_engine() -> None:
    assert llm_from_settings(Settings()) is None
    rec = llm_from_settings(Settings(llm_provider="recorded"))
    assert isinstance(rec, RecordedLLM)
    with pytest.raises(LLMError):
        llm_from_settings(Settings(llm_provider="vertex", gcp_project_id=None, gcp_region=None))


class Eng:
    """A model that answers with its own name, or is down."""

    def __init__(self, name: str, down: bool = False) -> None:
        self.name, self.down, self.calls = name, down, 0

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls += 1
        if self.down:
            raise LLMError("down")
        return {"by": self.name}


KW: dict[str, Any] = {"prompt_id": "p.v1", "system": "s", "user": "u", "schema": {}}


def test_failover_answers_locally_then_returns_to_the_primary() -> None:
    now = [0.0]
    gem, local = Eng("gemini", down=True), Eng("local")
    llm = FailoverLLM(gem, local, threshold=2, cooldown_s=60, clock=lambda: now[0])
    assert llm.generate_json(**KW) == {"by": "local"} and not llm.on_fallback  # 1st failure
    assert llm.generate_json(**KW) == {"by": "local"} and llm.on_fallback  # 2nd: breaker opens
    assert gem.calls == 2
    llm.generate_json(**KW)
    assert gem.calls == 2 and llm.last_used == "local"  # open: the primary is not even tried
    now[0] = 61  # wait over, primary still down: one trial, then a longer wait (120 s)
    assert llm.generate_json(**KW) == {"by": "local"} and gem.calls == 3
    now[0] = 61 + 119
    llm.generate_json(**KW)
    assert gem.calls == 3
    gem.down, now[0] = False, 61 + 121  # primary is back: the trial succeeds
    assert llm.generate_json(**KW) == {"by": "gemini"} and not llm.on_fallback
    assert llm.generate_json(**KW) == {"by": "gemini"} and llm.last_used == "gemini"
    assert local.calls == 5


def test_failover_with_both_down_fails_closed() -> None:
    llm = FailoverLLM(Eng("gemini", down=True), Eng("local", down=True))
    with pytest.raises(LLMError):
        llm.generate_json(**KW)


def test_a_saved_answer_does_not_close_the_breaker(tmp_path: Path) -> None:
    now = [0.0]
    live = FakeLive()
    cached = CachingLLM(live, tmp_path)
    cached.generate_json(**KW)  # saved while the model was up
    other = {**KW, "user": "new question"}
    live.generate_json = Eng("gemini", down=True).generate_json  # type: ignore[method-assign]
    llm = FailoverLLM(cached, Eng("local"), threshold=1, cooldown_s=60, clock=lambda: now[0])
    assert llm.generate_json(**other) == {"by": "local"} and llm.on_fallback
    now[0] = 61
    assert llm.generate_json(**KW) == {"verdict": "consistent"}  # trial served from the cache
    assert llm.generate_json(**other) == {"by": "local"}  # still treated as down


def test_ollama_must_be_on_this_machine() -> None:
    assert OllamaClient("http://localhost:11434", "some-model").name == "some-model@ollama-local"
    for url in ("http://10.0.0.5:11434", "https://api.groq.com", "http://example.com:11434"):
        with pytest.raises(LLMError):
            OllamaClient(url, "some-model")
    with pytest.raises(LLMError):
        OllamaClient("http://localhost:11434", "")


def test_settings_build_the_failover_chain() -> None:
    s = Settings(
        llm_provider="vertex",
        gcp_project_id="p",
        gcp_region="asia-south1",
        llm_fallback="ollama",
        ollama_model="some-model",
    )
    llm = llm_from_settings(s)
    assert isinstance(llm, FailoverLLM) and "ollama-local" in llm.name
    with pytest.raises(LLMError):  # fallback asked for, no model named
        llm_from_settings(s.model_copy(update={"ollama_model": None}))


# --- time bounds (ADR-0039; 24 Nov 2026 cloud profile: 90 % of a 317 s draft waited here) -------


class Slow(Fake):
    """A fake model that takes `delay` seconds per pair."""

    def __init__(self, delay: float, **kw: Any) -> None:
        super().__init__(**kw)
        self.delay = delay

    def generate_json(self, **kw: Any) -> dict[str, Any]:
        import time

        time.sleep(self.delay)
        return super().generate_json(**kw)


LOWER = [
    Evidence(canonical_id=f"AP-ESE01-CIRMEMO-X-{i}-2020", level=7, text=f"Rule {i} applies.")
    for i in range(3)
]


def test_pairs_are_asked_side_by_side_not_one_after_another() -> None:
    import time

    docs = [GO, *LOWER]  # 6 pairs, every one asked (each has an instrument below a G.O.)
    t = time.monotonic()
    res = contradiction_flags(docs, Slow(0.3), workers=6, budget_s=5.0)
    took = time.monotonic() - t
    assert res.asked == 6 and res.failed == 0
    assert took < 1.2  # one after another would take ≥ 1.8 s


def test_pairs_left_when_the_budget_runs_out_count_as_failed_and_return_on_time() -> None:
    import time

    docs = [GO, *LOWER]
    t = time.monotonic()
    res = contradiction_flags(docs, Slow(2.0), workers=2, budget_s=0.3)
    took = time.monotonic() - t
    assert res.flags == () and res.asked == 6 and res.failed == 6  # incomplete, never guessed
    assert took < 1.0


def test_answers_keep_the_pair_order_whatever_order_they_arrive_in() -> None:
    ans = {
        "AP-ESE01-CIRMEMO-SYNESE01GEN-41-2020-D20201020": {
            "verdict": "contradiction",
            "quote_a": "more than half the Academic year would be considered",
            "quote_b": "Only completed academic years shall be counted",
            "explanation": "",
        }
    }
    serial = contradiction_flags([GO, CIR1, CIR2], Fake(ans), workers=1)
    parallel = contradiction_flags([GO, CIR1, CIR2], Slow(0.05, answers=ans), workers=3)
    assert [f.model_dump() for f in serial.flags] == [f.model_dump() for f in parallel.flags]


def test_a_gemini_call_past_its_time_limit_ends_closed_on_time() -> None:
    import time

    pytest.importorskip("google.genai")  # the `gcp` extra builds the request config

    class Stuck:
        class models:  # noqa: N801 — mirrors the SDK's attribute
            @staticmethod
            def generate_content(**kw: Any) -> Any:
                time.sleep(3)
                raise AssertionError("should have been abandoned")

    g = GeminiVertexClient("p", "asia-south1", "m", client=Stuck(), timeout_s=0.2)
    t = time.monotonic()
    with pytest.raises(LLMError, match="timeout"):
        g.generate_json(prompt_id="x", system="s", user="u", schema={"type": "object"})
    assert time.monotonic() - t < 1.0


def test_quota_and_passing_server_errors_are_retried_within_the_time_limit() -> None:
    from app.agents.llm import RETRY

    types = pytest.importorskip("google.genai.types")
    assert 429 in RETRY["http_status_codes"] and RETRY["attempts"] >= 2
    assert 400 not in RETRY["http_status_codes"]  # a bad request is never repeated
    types.HttpRetryOptions(**RETRY)  # the SDK accepts it as given


def test_an_api_error_is_named_by_code_and_status_never_by_its_message() -> None:
    from app.agents.llm import _kind

    class ClientError(Exception):
        code, status = 429, "RESOURCE_EXHAUSTED"

    assert _kind(ClientError("echo of the request text")) == "ClientError(429 RESOURCE_EXHAUSTED)"
    assert _kind(ValueError("x")) == "ValueError"


def test_a_reply_that_is_not_json_says_why_the_model_stopped_not_what_it_wrote() -> None:
    pytest.importorskip("google.genai")

    class Cut:
        text = '{"sections": [{"heading": "Background", "lines": [{"text": "secret wor'
        candidates = [type("C", (), {"finish_reason": type("F", (), {"name": "MAX_TOKENS"})()})()]

    class Client:
        class models:  # noqa: N801 — mirrors the SDK's attribute
            @staticmethod
            def generate_content(**kw: Any) -> Any:
                return Cut()

    g = GeminiVertexClient("p", "asia-south1", "m", client=Client(), timeout_s=5)
    with pytest.raises(LLMError) as err:
        g.generate_json(prompt_id="x", system="s", user="u", schema={"type": "object"})
    assert "finish MAX_TOKENS" in str(err.value) and "secret" not in str(err.value)
