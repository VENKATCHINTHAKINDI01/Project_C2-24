"""Confidence of answer statements (Tier 2; ADR-0054): from facts the system holds, never the
model's self-report; the weakest factor sets the band; a later order the officer may not see
never changes it (or the reason shown)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.citation.confidence import Band, Cited, assess, default_confidence_config
from app.config import get_settings
from app.main import create_app
from app.temporal.engine import Instrument, RelationKind, TemporalRelation
from tests.unit.test_orchestrator import AnswersOnly

CFG = default_confidence_config()
DAY = dt.date(2026, 10, 2)
GO = Instrument(canonical_id="GO1", hierarchy_level=4, effective_from=dt.date(2020, 1, 1))
NEW = Instrument(canonical_id="GO2", hierarchy_level=4, effective_from=dt.date(2024, 1, 1))


def rate(text: str = "Spouse cases get preference.", cited: list[Cited] | None = None,
         **kw: Any) -> Any:  # fmt: skip
    args: dict[str, Any] = {
        "verified": True, "from_records": False, "as_of": DAY,
        "instruments": {"GO1": GO, "GO2": NEW}, "relations": [], "may_see": lambda c: True,
        "graph_down": False, "cfg": CFG,
    } | kw  # fmt: skip
    default = [Cited(canonical_id="GO1", rung="L0", hierarchy_level=4)]
    return assess(text, default if cited is None else cited, **args)


def test_an_in_force_go_found_by_reference_and_quoted_is_high() -> None:
    c = rate()
    assert c.band is Band.HIGH and c.score == 1.0
    assert {f.name for f in c.factors} == {
        "retrieval", "authority", "support", "validity", "consistency", "graph",
    }  # fmt: skip


@pytest.mark.parametrize(
    ("kw", "band", "weakest"),
    [
        ({"verified": False}, Band.LOW, "support"),
        ({"graph_down": True}, Band.MEDIUM, "graph"),
        ({"cited": [Cited(canonical_id="GO1", rung="L2", hierarchy_level=4)]}, Band.MEDIUM,
         "retrieval"),
        ({"cited": [Cited(canonical_id="N1", rung="L0", hierarchy_level=10)]}, Band.MEDIUM,
         "authority"),
        ({"cited": [Cited(canonical_id="GO1", rung="L0", hierarchy_level=4, ocr=True)]},
         Band.MEDIUM, "support"),
    ],
)  # fmt: skip
def test_the_weakest_factor_sets_the_band(kw: dict[str, Any], band: Band, weakest: str) -> None:
    c = rate(**kw)
    assert c.band is band and c.weakest.name == weakest


SUPERSEDED = [TemporalRelation(source="GO2", kind=RelationKind.SUPERSEDES, target="GO1",
                               confirmed=True)]  # fmt: skip


def test_relying_on_an_outdated_order_without_saying_so_is_low() -> None:
    c = rate(relations=SUPERSEDED)
    assert c.band is Band.LOW and c.weakest.name == "validity"
    assert "superseded" in c.weakest.reason
    said = rate("GO1 was superseded by GO2 in 2024.", relations=SUPERSEDED)
    assert said.band is not Band.LOW  # history stated as history is fine


def test_a_later_amendment_the_officer_may_see_but_the_answer_ignores_lowers_it() -> None:
    amended = [TemporalRelation(source="GO2", kind=RelationKind.AMENDS, target="GO1",
                                confirmed=True)]  # fmt: skip
    c = rate(relations=amended)
    assert c.band is Band.MEDIUM and c.weakest.name == "consistency" and "GO2" in c.weakest.reason
    cites_both = rate(cited=[Cited(canonical_id="GO1", rung="L0", hierarchy_level=4),
                             Cited(canonical_id="GO2", rung="L0", hierarchy_level=4)],
                      relations=amended)  # fmt: skip
    assert cites_both.band is Band.HIGH


def test_a_later_order_the_officer_may_not_see_changes_nothing() -> None:
    amended = [TemporalRelation(source="GO2", kind=RelationKind.AMENDS, target="GO1",
                                confirmed=True)]  # fmt: skip
    c = rate(relations=amended, may_see=lambda cid: cid != "GO2")
    assert c.band is Band.HIGH
    assert all("GO2" not in f.reason for f in c.factors)


def test_facts_from_the_records_are_rated_as_records() -> None:
    c = rate(cited=[], from_records=True)
    assert c.band is Band.HIGH and {f.name for f in c.factors} == {"retrieval", "support"}


APP = create_app(get_settings().model_copy(update={"sandbox": True}))


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        APP.state.assist_runtime().llm = AnswersOnly()
        try:
            yield c
        finally:
            APP.state.assist_runtime().llm = None


def test_every_shown_statement_and_the_answer_carry_a_confidence(client: TestClient) -> None:
    r = client.post(
        "/assist/ask",
        json={"question": "Which orders govern the outsourced data entry operators?"},
        headers={"X-Sandbox-User": "U01"},
    ).json()
    assert r["status"] == "answered" and r["statements"]
    bands = [s["confidence"]["band"] for s in r["statements"]]
    assert all(b in {"high", "medium", "low"} for b in bands)
    assert all(f["reason"] for s in r["statements"] for f in s["confidence"]["factors"])
    order = {"low": 0, "medium": 1, "high": 2}
    assert r["confidence"]["band"] == min(bands, key=order.__getitem__)  # the weakest statement
