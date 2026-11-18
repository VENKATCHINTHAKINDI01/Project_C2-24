"""Counts of decided matters (ADR-0051; golden Q11; plan §13.3 "counts"): computed only over the
records the officer may see, by fixed rules, never by the model; nothing hints at a record left
out. Checked for every officer against the access oracle (mock_v1 access_matrix.csv)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
from app.precedent.counts import Outcome, count_ask, final_order
from tests.unit.mock_access import MATRIX
from tests.unit.test_sandbox_api import USERS, _doc_id, _h

APP = create_app(get_settings().model_copy(update={"sandbox": True}))
# the decided spouse-ground transfer files of mock_v1 (synthetic): final order and its year
DECIDED = {"D17": ("approved", 2022), "D18": ("rejected", 2023), "D19": ("approved", 2025),
           "D20": ("rejected", 2025)}  # fmt: skip


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        yield c


def _count(c: TestClient, uid: str, q: str) -> dict[str, Any]:
    r = c.post("/assist/ask", json={"question": q}, headers=_h(uid))
    assert r.status_code == 200, r.text
    out = r.json()
    facts = [s for s in out["statements"] if s["source"] == "file records"]
    assert out["status"] == "answered" and len(facts) == 1, out
    return dict(facts[0])


def test_the_question_is_read_by_fixed_rules() -> None:
    a = count_ask("How many spouse-ground transfer requests were rejected in 2025?")
    assert a is not None
    assert (a.outcome, a.year, a.topic) == (
        Outcome.REJECTED,
        2025,
        ("spouse", "ground", "transfer"),
    )
    b = count_ask("How many transfers were approved?")
    assert b is not None and (b.outcome, b.year, b.topic) == (Outcome.APPROVED, None, ("transfer",))
    assert count_ask("What was decided on spouse-ground transfers?") is None


@pytest.mark.parametrize(
    ("last", "want"),
    [
        ("8. Approved.", Outcome.APPROVED),
        ("9. Approved. Issue orders.", Outcome.APPROVED),
        ("8. Not agreed at present, as the ban on transfers is in force.", Outcome.REJECTED),
        ("8. Not considered in view of the pending enquiry.", Outcome.REJECTED),
        ("8. Not approved.", Outcome.REJECTED),
        ("8. Submitted for orders.", None),  # undecided: never counted, never guessed
    ],
)
def test_the_final_order_is_the_last_paragraph_of_the_last_note(last: str, want: Any) -> None:
    text = (
        "Note # 1\n1. Request received.\nA / Assistant / 01/05/2025 10:00 AM\n"
        f"Note # 2\n{last}\nB / Secretary to Government / 27/05/2025 07:00 PM\n"
    )
    got = final_order(text, "X")
    assert (got[0] if got else None) is want
    if got:
        assert got[1] == dt.date(2025, 5, 27)


def test_every_officer_counts_only_what_they_may_see(client: TestClient) -> None:
    """The count equals the oracle count over the officer's ALLOWED records; every cited record
    is allowed; a hidden record changes nothing they are shown (no hint, no 'others exist')."""
    for uid in USERS:
        seen = {d: v for d, v in DECIDED.items() if MATRIX[(d, uid)]}
        for q, outcome, year in (
            ("How many spouse-ground transfer requests were rejected in 2025?", "rejected", 2025),
            ("How many spouse ground transfers were approved?", "approved", None),
        ):
            f = _count(client, uid, q)
            want = sorted(d for d, (o, y) in seen.items() if o == outcome and year in (None, y))
            decided = [d for d, (_, y) in seen.items() if year in (None, y)]
            assert f["text"].startswith(f"Among the records you may see, {len(want)} "), (uid, f)
            assert f"(of {len(decided)} decided" in f["text"], (uid, f)
            cited = sorted(d for c in f["citations"] if (d := _doc_id(c["canonical_id"])))
            assert cited == (want or sorted(decided)), (uid, cited)
            assert all(MATRIX[(d, uid)] for d in cited)
            for word in ("restricted", "not available", "other", "hidden", "access"):
                assert word not in f["text"].lower(), (uid, f["text"])


def test_golden_q11_officer_a_hears_zero_without_a_hint(client: TestClient) -> None:
    f = _count(client, "U01", "How many spouse-ground transfer requests were rejected in 2025?")
    assert f["text"] == (
        "Among the records you may see, 0 spouse ground transfer matters were rejected in 2025 "
        "(of 1 decided in 2025)."
    )
    assert not MATRIX[("D20", "U01")] and "D20" not in str(f)
