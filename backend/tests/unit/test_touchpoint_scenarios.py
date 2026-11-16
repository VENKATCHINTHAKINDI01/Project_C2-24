"""Touchpoint scenarios (plan §11.5, §13.2) are consistent with the corpus, access matrix and seed.

Evaluation-side test: it may read ground truth; application code never does.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.identifiers.canonical import parse_canonical_id
from tests.unit.mock_access import CORPUS, MATRIX, USER_IDS, rows

GT = CORPUS / "ground_truth"
DATA = json.loads((GT / "touchpoint_scenarios.json").read_text(encoding="utf-8"))
SCENARIOS: list[dict[str, Any]] = DATA["scenarios"]
SEED = json.loads((CORPUS / "eoffice" / "seed.json").read_text(encoding="utf-8"))
QUESTIONS = {q["id"]: q for q in json.loads((GT / "golden_questions.json").read_text("utf-8"))}
CONFLICTS = json.loads((GT / "conflicts.json").read_text(encoding="utf-8"))
DOC_IDS = {r["id"] for r in rows("documents_index.csv")}
FILE_OF = {
    d["id"]: d["file_no"] for d in json.loads((CORPUS / "manifest.json").read_text())["documents"]
}
FILES = {f["computer_no"]: f for f in SEED["files"]}
RECEIPTS = {r["computer_no"] for r in SEED["receipts"]}
NOTES = {n["note_id"] for n in SEED["notes"]}
CORE = {2, 3, 4, 6, 7, 8, 9, 10, 11, 13, 14, 15, 20}
EXTENDED = {1, 5, 12, 16, 17, 18, 19}  # added 15 Nov 2026 (ADR-0038)


def _docs_in_file(computer_no: str) -> set[str]:
    file_no = FILES[computer_no]["file_no"]
    return {d for d, f in FILE_OF.items() if f == file_no}


def _list(value: object) -> list[str]:
    return value if isinstance(value, list) else []


def test_every_touchpoint_has_a_scenario_and_ids_are_unique() -> None:
    assert {s["touchpoint"] for s in SCENARIOS} == CORE | EXTENDED == set(range(1, 21))
    ids = [s["id"] for s in SCENARIOS]
    assert len(ids) == len(set(ids))
    assert DATA["synthetic"] is True and "never read" in DATA["evaluation_only"]


@pytest.mark.parametrize("s", SCENARIOS, ids=lambda s: s["id"])
def test_scenario_references_exist(s: dict[str, Any]) -> None:
    assert s["user"] in USER_IDS
    assert set(s["related_questions"]) <= set(QUESTIONS)
    ctx = s["context"]
    if "computer_no" in ctx:
        assert ctx["computer_no"] in FILES
    if "receipt" in ctx:
        assert ctx["receipt"] in RECEIPTS
    exp = s["expected"]
    for key in ("docs", "forbidden_docs"):
        assert set(_list(exp.get(key))) <= DOC_IDS
    for key in ("files", "forbidden_files"):
        assert set(_list(exp.get(key))) <= set(FILES)
    for flag in _list(exp.get("flags")):
        assert flag["cited"] in DOC_IDS  # type: ignore[index]
    if cit := exp.get("citation"):
        assert cit["note_id"] in NOTES
    if clause := exp.get("clause"):
        assert parse_canonical_id(clause).clause
    assert set(s.get("setup", {}).get("holdback", [])) <= DOC_IDS


@pytest.mark.parametrize("s", SCENARIOS, ids=lambda s: s["id"])
def test_expected_and_forbidden_docs_agree_with_the_access_matrix(s: dict[str, Any]) -> None:
    uid, exp = s["user"], s["expected"]
    for did in _list(exp.get("docs")):
        assert MATRIX[(did, uid)], f"{s['id']}: {uid} cannot see expected {did}"
    for did in _list(exp.get("forbidden_docs")):
        assert not MATRIX[(did, uid)], f"{s['id']}: forbidden {did} is visible to {uid}"


@pytest.mark.parametrize("s", SCENARIOS, ids=lambda s: s["id"])
def test_expected_and_forbidden_files_agree_with_the_access_matrix(s: dict[str, Any]) -> None:
    uid, exp = s["user"], s["expected"]
    for cno in _list(exp.get("files")):
        assert any(MATRIX[(d, uid)] for d in _docs_in_file(cno)), f"{s['id']}: {cno}"
    for cno in _list(exp.get("forbidden_files")):
        assert not any(MATRIX[(d, uid)] for d in _docs_in_file(cno)), f"{s['id']}: {cno}"


def test_pre_send_scenarios_point_at_planted_conflicts() -> None:
    for s in (s for s in SCENARIOS if s["touchpoint"] == 11):
        doc = s["expected"]["flags"].split("in=")[1]
        assert any(c["in"] == doc for c in CONFLICTS), s["id"]
        assert QUESTIONS[s["related_questions"][0]]["expected_conflicts"]


def test_search_privilege_pairs_are_real_golden_questions() -> None:
    tp20 = next(s for s in SCENARIOS if s["touchpoint"] == 20)
    for group in tp20["expected"]["pairs"]:
        assert set(group) <= set(QUESTIONS)


def test_drafts_are_created_only_on_click() -> None:
    for s in SCENARIOS:
        if draft := s["expected"].get("draft"):
            assert draft["created_only_on_click"] is True and draft["status"] == "draft"


def test_replay_holds_back_the_new_order_and_everything_that_depends_on_it() -> None:
    """TP04: nothing left in the index may cite the held-back order (no anachronism)."""
    tp04 = next(s for s in SCENARIOS if s["touchpoint"] == 4)
    held = set(tp04["setup"]["holdback"])
    rel = rows("ground_truth/relations.csv")
    dependants = {r["from_id"] for r in rel if r["to_id"] in held}
    assert dependants <= held
