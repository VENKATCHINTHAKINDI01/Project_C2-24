"""Evaluation harness (plan §13; CLAUDE.md §9): metric definitions, and the whole-corpus run as a
regression gate — zero disclosures across every path. Retrieval and conflict numbers are a
measured baseline, not thresholds; they are reported, never asserted to a target here."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from evaluation.harness import metrics as m
from evaluation.run_eval import free_name, run_all, to_markdown


def test_metric_definitions() -> None:
    ranked = ["a", "x", "b", "y", "z", "c"]
    rel = {"a", "b", "c"}
    assert m.recall_at(ranked, rel, 5) == pytest.approx(2 / 3)
    assert m.recall_at(ranked, rel, 10) == 1.0
    assert m.precision_at(ranked, rel, 5) == pytest.approx(2 / 5)
    assert m.reciprocal_rank(["x", "a"], rel) == 0.5
    assert m.reciprocal_rank(["x"], rel) == 0.0
    assert m.ndcg_at(["a", "b", "c"], rel, 10) == pytest.approx(1.0)
    assert m.ndcg_at(["x", "a"], {"a"}, 10) == pytest.approx(1 / 1.584962500721156)
    assert m.prf(2, 0, 1) == {"precision": 1.0, "recall": pytest.approx(2 / 3), "f1": 0.8}
    assert m.prf(0, 0, 2)["precision"] is None  # nothing predicted: undefined, not 0 or 1


@pytest.fixture(scope="module")
def report() -> dict[str, Any]:
    return run_all()


def test_zero_disclosures_on_every_path(report: dict[str, Any]) -> None:
    lk = report["leakage"]
    assert lk["disclosures"] == []
    assert lk["summary"]["pass"] and lk["summary"]["checks"] > 1000
    for path in (
        "question → retrieved set",
        "question → evidence package",
        "exact ID + graph",
        "keyword (L2) by subject",
        "count / list-all (L1)",
        "reference lookup (existence)",
        "pre-send report",
        "file check → pre-send evidence",
    ):
        assert lk["paths"][path]["checks"] > 0, path


def test_every_golden_question_and_conflict_type_is_reported(report: dict[str, Any]) -> None:
    assert len(report["retrieval"]["questions"]) == 24
    assert set(report["conflict"]["per_type"]) == set("ABCDEFG")
    for t in "BDG":  # not built yet: reported as such, never silently dropped
        assert not report["conflict"]["per_type"][t]["implemented"]
    assert report["touchpoints"]["summary"]["scenarios"] == 24  # 17 core + 7 extended (ADR-0038)


def test_no_false_flags_on_clean_controls_and_never_clear_on_mock_rules(
    report: dict[str, Any],
) -> None:
    c = report["conflict"]
    assert c["summary"]["clean_control_false_flags"] == 0
    assert c["summary"]["clean_controls_reported_clear"] == 0  # mock rules → review_needed


def test_stand_ins_are_declared(report: dict[str, Any]) -> None:
    st = report["meta"]["stack"]
    assert report["meta"]["corpus"].endswith("(SYNTHETIC)")
    assert set(st["indexed_from_transcription"]) <= set(st["held_files"])
    assert st["rules"] == "mock"
    assert "Baseline on the reference stack, not on GCP" in to_markdown(report)


def test_reports_are_never_overwritten(tmp_path: Path) -> None:
    assert free_name(tmp_path, "2026-11-04-baseline") == "2026-11-04-baseline"
    (tmp_path / "2026-11-04-baseline.md").write_text("x")
    (tmp_path / "2026-11-04-baseline.json").write_text("{}")
    assert free_name(tmp_path, "2026-11-04-baseline") == "2026-11-04-baseline-2"
    (tmp_path / "2026-11-04-baseline-2.md").write_text("x")
    assert free_name(tmp_path, "2026-11-04-baseline") == "2026-11-04-baseline-3"
