"""Config loading and validation (plan §4.5, §14.2; ADR-0002)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import (
    REPO_ROOT,
    Environment,
    Settings,
    load_classification,
    load_hierarchy,
    load_runtime_config,
)

ONTOLOGY = REPO_ROOT / "data" / "ontology"


def test_hierarchy_matches_plan_draft() -> None:
    h = load_hierarchy(ONTOLOGY / "hierarchy.yaml")
    assert [lv.level for lv in h.levels] == list(range(1, 11))  # ADR-0027: Proceedings added
    assert h.levels[3].instrument == "GO_MS"
    assert h.levels[6].instrument == "PROCEEDINGS"
    assert h.levels[-1].instrument == "DECISION_NOTING"
    assert h.status == "mock"  # never "confirmed" without the department (CLAUDE.md §5.9)
    assert all(lv.basis for lv in h.levels)  # every placing names its source or says assumption


def test_classification_follows_csmop_order() -> None:
    c = load_classification(ONTOLOGY / "classification.yaml")
    assert [lv.name for lv in c.levels] == ["UNCLASSIFIED", "RESTRICTED", "CONFIDENTIAL", "SECRET"]


def test_runtime_thresholds_start_uncalibrated() -> None:
    rt = load_runtime_config(REPO_ROOT / "backend" / "config" / "runtime.yaml")
    assert rt.retrieval.l2_top_k is None
    assert rt.ingestion.extraction_confidence_min is None


def test_hierarchy_rejects_gaps(tmp_path: Path) -> None:
    bad = tmp_path / "h.yaml"
    bad.write_text(
        "version: x\nstatus: draft\nlevels:\n"
        "  - {level: 1, instrument: A, label: a}\n"
        "  - {level: 3, instrument: B, label: b}\n"
    )
    with pytest.raises(ValidationError):
        load_hierarchy(bad)


def test_classification_rejects_duplicates(tmp_path: Path) -> None:
    bad = tmp_path / "c.yaml"
    bad.write_text(
        "version: x\nstatus: draft\nlevels:\n  - {rank: 0, name: A}\n  - {rank: 1, name: A}\n"
    )
    with pytest.raises(ValidationError):
        load_classification(bad)


def test_runtime_rejects_unknown_keys(tmp_path: Path) -> None:
    bad = tmp_path / "r.yaml"
    bad.write_text("version: x\ningestion: {}\nretrieval: {top_k_typo: 5}\ncache: {}\n")
    with pytest.raises(ValidationError):
        load_runtime_config(bad)


def test_gcp_env_requires_project_and_region(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("C2_GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("C2_GCP_REGION", raising=False)
    with pytest.raises(ValidationError):
        Settings(env=Environment.GCP, _env_file=None)


def test_the_spanner_graph_needs_its_instance_and_cloud_sql_stays_the_default() -> None:
    """ADR-0048: Cloud SQL is the graph store unless Spanner is chosen, and choosing it without
    an instance stops the service at start (fail closed)."""
    import pydantic

    from app.config import Settings

    assert Settings().graph_backend == "postgres"
    with pytest.raises(pydantic.ValidationError, match="C2_SPANNER_INSTANCE"):
        Settings(graph_backend="spanner", gcp_project_id="p")
    s = Settings(graph_backend="spanner", gcp_project_id="p", spanner_instance="c2-spanner")
    assert (s.spanner_instance, s.spanner_database) == ("c2-spanner", "c2graph")
