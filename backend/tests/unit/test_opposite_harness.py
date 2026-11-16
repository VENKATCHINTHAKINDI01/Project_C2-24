"""The opposite-scenario checks must be able to fail: each kind of expectation is shown failing on
a response that breaks it (evaluation harness self-test, CLAUDE.md §9)."""

from __future__ import annotations

from typing import Any

import pytest
from evaluation.harness.opposites import _check, _cid, _path


def _sc(expect: dict[str, Any]) -> dict[str, Any]:
    return {"user": "U01", "call": ["POST", "/x", {}], "expect": expect}


@pytest.mark.parametrize(
    ("expect", "body"),
    [
        ({"never_docs": ["D20"]}, {"x": _cid()["D20"]}),
        ({"must_docs": ["D17"]}, {"x": "nothing"}),
        ({"flag_types": []}, {"flags": [{"type": "A", "certain": True}]}),
        ({"certain_flags": []}, {"flags": [{"type": "E", "certain": True}]}),
        ({"empty": ["suggestions"]}, {"suggestions": [1]}),
        ({"equals": {"by": None}}, {"by": "AP-X"}),
        ({"not_equals": {"flags.*.type": "A"}}, {"flags": [{"type": "A"}]}),
        ({"no_in_place_of": True}, {"read_list": [{"in_place_of": ["AP-X"]}]}),
    ],
)
def test_each_expectation_kind_can_fail(expect: dict[str, Any], body: Any) -> None:
    assert _check(None, _sc(expect), 200, body)  # type: ignore[arg-type]


def test_passing_bodies_pass_and_errors_fail() -> None:
    assert _check(None, _sc({"flag_types": [], "certain_flags": []}), 200, {"flags": []}) == []  # type: ignore[arg-type]
    assert _check(None, _sc({"empty": ["x"]}), 500, {"detail": "boom"})  # type: ignore[arg-type]


def test_dotted_paths() -> None:
    body = {"flags": [{"type": "A"}, {"type": "C"}], "c": {"id": 1}}
    assert _path(body, "flags.*.type") == ["A", "C"]
    assert _path(body, "c.id") == [1] and _path(body, "c.missing") == [None]
