"""Knowledge-graph build job (plan §4, §3.6): orders → normal pipeline → nodes / edges files.
SYNTHETIC orders written here; no corpus, no GCP."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.graph.build import main

HEAD = "GOVERNMENT OF ANDHRA PRADESH\nABSTRACT\n\nSYNTHETIC – Transfers – "
DEPT = "\n\nFINANCE (HR.I) DEPARTMENT\n\n"
OLD = (
    HEAD + "Guidelines – Orders – Issued." + DEPT + "G.O.MS.No. 11          Dated: 05-01-2020.\n\n"
    "ORDER:\n\nThe following guidelines are issued for transfers of employees.\n"
)
NEW = (
    HEAD + "Guidelines – Orders – Issued." + DEPT + "G.O.MS.No. 27          Dated: 09-03-2021.\n"
    "                                                     Read:\n\n"
    "G.O.Ms.No.11, Finance (HR.I) Department, dated 05-01-2020.\n\nORDER:\n\n"
    "In supersession of the orders issued in the G.O. read above, the following guidelines "
    "are issued.\n"
)


def _order(root: Path, cid: str, date: str, text: str, marking: str = "UNCLASSIFIED") -> None:
    d = root / "staging" / "rule-library" / "goir" / "FIN01" / date[:4] / cid
    d.mkdir(parents=True)
    (d / "order.txt").write_text(text, "utf-8")
    meta = {
        "canonical_id": cid,
        "department_code": "FIN01",
        "section": "HR.I",
        "classification": marking,
        "date": date,
        "files": {"original": "order.txt"},
    }
    (d / "meta.json").write_text(json.dumps(meta), "utf-8")


def _rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def test_orders_become_nodes_and_stated_links_become_edges(tmp_path: Path) -> None:
    _order(tmp_path, "AP-FIN01-GOMS-27-2021", "2021-03-09", NEW)
    _order(tmp_path, "AP-FIN01-GOMS-11-2020", "2020-01-05", OLD)
    _order(tmp_path, "AP-FIN01-GOMS-99-2021", "2021-05-01", OLD, marking="SECRET")
    out = tmp_path / "graph"
    assert main(["--public-dir", str(tmp_path), "--out", str(out)]) == 0
    nodes = {n["id"]: n for n in _rows(out / "nodes.jsonl")}
    assert set(nodes) == {"AP-FIN01-GOMS-11-2020", "AP-FIN01-GOMS-27-2021"}  # SECRET: never read
    assert nodes["AP-FIN01-GOMS-27-2021"]["issue_date"] == "2021-03-09"  # read from the text
    edges = {
        (e["from"], e["relation"], e["to"], e["confirmed"]) for e in _rows(out / "edges.jsonl")
    }
    assert ("AP-FIN01-GOMS-27-2021", "SUPERSEDES", "AP-FIN01-GOMS-11-2020", True) in edges
    assert _rows(out / "held.jsonl") == []
    report = (out / "report.md").read_text("utf-8")
    assert (
        "Indexed (graph nodes): **2**" in report
        and "same ID as the collection metadata: **2**" in report
    )


def test_the_job_loads_spanner_and_fails_loudly_without_its_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-0048: --load-spanner writes the built graph to Spanner Graph (a stand-in port here);
    without the instance setting the run exits non-zero and says why."""
    import app.graph.spanner as sp
    from app.config import get_settings
    from tests.unit.test_graph_spanner import SqlitePort

    _order(tmp_path, "AP-FIN01-GOMS-27-2021", "2021-03-09", NEW)
    _order(tmp_path, "AP-FIN01-GOMS-11-2020", "2020-01-05", OLD)
    port = SqlitePort()
    monkeypatch.setattr(sp, "CloudSpannerPort", lambda project, instance, db: port)
    monkeypatch.setenv("C2_GCP_PROJECT_ID", "test-project")
    get_settings.cache_clear()
    try:
        args = ["--public-dir", str(tmp_path), "--out", str(tmp_path / "graph"), "--load-spanner"]
        assert main(args) == 1  # no C2_SPANNER_INSTANCE: refused, reported, non-zero
        monkeypatch.setenv("C2_SPANNER_INSTANCE", "c2-spanner")
        get_settings.cache_clear()
        assert main(args) == 0
        repo = sp.SpannerGraphRepository(port)
        assert repo.counts() == (2, 1)
        assert [e.kind.value for e in repo.edges()] == ["SUPERSEDES"]
    finally:
        get_settings.cache_clear()
