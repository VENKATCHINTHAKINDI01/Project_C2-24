"""The file of a cloud-only public order (ADR-0028 addendum): scope in the SQL, path kept inside
the corpus, bytes proven by the recorded hash. The template runs on DuckDB."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from app.retrieval.bigquery_index import table_rows
from app.retrieval.cloud_sources import SOURCE_SQL, CloudSourceFiles
from tests.unit.test_bigquery_index import DuckRunner, scope

pytest.importorskip("duckdb")
PDF = b"%PDF-1.7\n% a public order\n"
SHA = hashlib.sha256(PDF).hexdigest()


def _node(
    cid: str, dept: str, path: str | None, sha: str | None, cls: str = "UNCLASSIFIED"
) -> dict[str, Any]:
    return {
        "id": cid,
        "department": dept,
        "section": "CABINET-II",
        "classification": cls,
        "file_no": None,
        "doc_type": "Government Order",
        "issue_date": None,
        "subject": "s",
        "source_path": path,
        "source_sha256": sha,
    }


@pytest.fixture
def files(tmp_path: Path) -> CloudSourceFiles:
    root = tmp_path / "staging"
    (root / "rule-library/goir/GAD01/2018/AP-GAD01-GOMS-31-2018").mkdir(parents=True)
    (root / "rule-library/goir/GAD01/2018/AP-GAD01-GOMS-31-2018/order.pdf").write_bytes(PDF)
    (tmp_path / "outside.pdf").write_bytes(PDF)
    good = "rule-library/goir/GAD01/2018/AP-GAD01-GOMS-31-2018/order.pdf"
    rows = table_rows(
        [
            _node("AP-GAD01-GOMS-31-2018", "GAD01", good, SHA),
            _node("AP-GAD01-GOMS-32-2018", "GAD01", good, "0" * 64),  # bytes changed since
            _node("AP-GAD01-GOMS-33-2018", "GAD01", "../outside.pdf", SHA),  # escapes the root
            _node("AP-GAD01-GOMS-34-2018", "GAD01", None, None),  # no file recorded
            _node("AP-GAD01-GOMS-35-2018", "GAD01", good, SHA, cls="SECRET"),  # beyond clearance
        ]
    )
    return CloudSourceFiles(DuckRunner(rows), "p.d.documents", root)


def test_a_visible_cloud_order_is_served_from_the_corpus_with_its_hash(
    files: CloudSourceFiles,
) -> None:
    got = files.get("AP-GAD01-GOMS-31-2018", scope("GAD01", wide=True, rank=1))
    assert got is not None and got.data == PDF and got.media_type == "application/pdf"
    assert got.version == f"src-{SHA[:16]}"
    # public orders (no file number) are open to any officer, as in the index
    assert files.get("AP-GAD01-GOMS-31-2018", scope("FIN01", wide=False, rank=0)) is not None


@pytest.mark.parametrize(
    "cid",
    [
        "AP-GAD01-GOMS-32-2018",  # hash differs
        "AP-GAD01-GOMS-33-2018",  # outside the corpus
        "AP-GAD01-GOMS-34-2018",  # no recorded file
        "AP-GAD01-GOMS-35-2018",  # classification above the officer's clearance
        "AP-GAD01-GOMS-99-2018",  # unknown
    ],
)
def test_anything_else_gives_nothing(files: CloudSourceFiles, cid: str) -> None:
    assert files.get(cid, scope("GAD01", wide=True, rank=1)) is None


def test_the_template_is_fixed_and_carries_the_scope() -> None:
    assert "@cid" in SOURCE_SQL and "@department_wide" in SOURCE_SQL
    with pytest.raises(ValueError):
        CloudSourceFiles(DuckRunner([]), "p.d.documents`; DROP", Path("."))
