"""Sanity checks on the synthetic mock corpus v1 (plan §12.2); metadata only."""

from __future__ import annotations

import csv
from pathlib import Path

from app.config import REPO_ROOT, load_classification, load_hierarchy

CORPUS = REPO_ROOT / "data" / "synthetic" / "mock_v1"


def _rows(name: str) -> list[dict[str, str]]:
    with (CORPUS / name).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_every_indexed_document_file_exists() -> None:
    docs = _rows("documents_index.csv")
    assert len(docs) == 29
    missing = [d["file"] for d in docs if not (CORPUS / d["file"]).is_file()]
    assert missing == []


def test_access_matrix_covers_every_document_and_user() -> None:
    doc_ids = {d["id"] for d in _rows("documents_index.csv")}
    user_ids = {u["user_id"] for u in _rows("users.csv")}
    matrix = _rows("access_matrix.csv")
    assert {r["doc_id"] for r in matrix} == doc_ids
    for row in matrix:
        assert {row[u] for u in user_ids} <= {"ALLOW", "DENY"}


def test_corpus_values_fit_ontology() -> None:
    ontology = REPO_ROOT / "data" / "ontology"
    classes = {lv.name for lv in load_classification(ontology / "classification.yaml").levels}
    levels = {lv.level for lv in load_hierarchy(ontology / "hierarchy.yaml").levels}
    for d in _rows("documents_index.csv"):
        assert d["classification"] in classes, d["id"]
        assert int(d["hierarchy_level"]) in levels, d["id"]
    for u in _rows("users.csv"):
        assert u["clearance"] in classes, u["user_id"]


def test_corpus_contains_no_dotenv_or_keys() -> None:
    suspicious = [p for p in Path(CORPUS).rglob("*") if p.suffix in {".env", ".pem", ".key"}]
    assert suspicious == []
