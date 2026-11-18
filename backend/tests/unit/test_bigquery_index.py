"""BigQuery rungs L0/L1: same answers as the in-memory reference, scope inside the SQL.

The two fixed templates run here on DuckDB through a small dialect shim (named parameters and
backticks, list membership), so the WHERE clause itself is executed, not just inspected. A run
against real BigQuery is `evaluation/cloud_ladder_check.py` (owner, needs the project).
"""

from __future__ import annotations

import datetime as dt
import random
import re
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from app.auth.models import DocumentAccessTags, Scope
from app.retrieval.bigquery_index import (
    EXACT_SQL,
    FILTER_SQL,
    SCHEMA,
    BigQueryScopedIndex,
    Param,
    table_rows,
)
from app.retrieval.scoped import IndexedDocument, InMemoryScopedIndex, L1Criteria

duckdb = pytest.importorskip("duckdb")

RANKS = {"UNCLASSIFIED": 0, "RESTRICTED": 1, "CONFIDENTIAL": 2, "SECRET": 3}
TYPES = {"INT64": "BIGINT", "STRING": "VARCHAR", "DATE": "DATE", "BOOL": "BOOLEAN"}


class DuckRunner:
    """Runs the BigQuery templates on DuckDB. Only syntax is translated; the logic is untouched."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.db = duckdb.connect()
        cols = ", ".join(f"{n} {TYPES[t]}" for n, t, _ in SCHEMA)
        self.db.execute(f"CREATE TABLE documents ({cols})")
        for r in rows:
            self.db.execute(
                f"INSERT INTO documents VALUES ({', '.join('?' * len(SCHEMA))})",
                [r.get(n) for n, _, _ in SCHEMA],
            )
        self.seen: list[tuple[str, dict[str, Any]]] = []

    def run(self, sql: str, params: Sequence[Param]) -> list[Mapping[str, Any]]:
        self.seen.append((sql, {n: v for n, _, v in params}))
        q = sql.replace("`p.d.documents`", "documents")
        # DuckDB has no `x IN UNNEST(list)`: same meaning, different spelling
        q = re.sub(r"(\w+) IN UNNEST\(@(\w+)\)", r"list_contains(@\2, \1)", q)
        q = q.replace(
            "FROM UNNEST(@subject_terms) AS t", "FROM (SELECT UNNEST(@subject_terms) AS t)"
        )
        for n, t, _ in params:  # typed, so a NULL or an empty list keeps its type
            kind = f"{TYPES[t[6:-1]]}[]" if t.startswith("ARRAY<") else TYPES[t]
            q = re.sub(rf"@{n}\b", f"CAST(${n} AS {kind})", q)
        cur = self.db.execute(q, {n: v for n, _, v in params})
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def scope(
    dept: str, *, wide: bool, rank: int, sections: tuple[str, ...] = (), files: tuple[str, ...] = ()
) -> Scope:
    return Scope(
        user_id="u",
        policy_version="t",
        classification_ranks=RANKS,
        public_rank=0,
        department=dept,
        max_rank=rank,
        department_wide=wide,
        sections=frozenset(sections),
        file_nos=frozenset(files),
    )


def corpus(seed: int) -> list[IndexedDocument]:
    rng = random.Random(seed)  # noqa: S311 — test data
    docs = []
    for i in range(120):
        dept = rng.choice(["FIN01", "GAD01", "ESE01"])
        kind = rng.choice(["GOMS", "GORT", "MEMO"])
        day = rng.choice([None, dt.date(2015 + i % 10, 1 + i % 12, 1 + i % 28)])
        dated = rng.random() < 0.3 and day is not None
        cid = f"AP-{dept}-{kind}-{1 + i // 3}-{2015 + i % 10}" + (
            f"-D{day:%Y%m%d}" if dated else ""
        )
        docs.append(
            IndexedDocument(
                canonical_id=cid,
                tags=DocumentAccessTags(
                    doc_id=cid,
                    department=dept,
                    section=rng.choice([None, "A", "B"]),
                    classification=rng.choice([*RANKS, "UNCLASSIFIED", "ODD-MARK"]),
                    file_no=rng.choice([None, None, "F-1", "F-2"]),
                ),
                doc_type=rng.choice(["Government Order", "Memo", "Circular"]),
                issue_date=day,
                subject=rng.choice(
                    ["Leave rules amended", "Transfer of teachers", "Pension revision orders", ""]
                ),
            )
        )
    return list({d.canonical_id: d for d in docs}.values())


def both(
    seed: int,
) -> tuple[BigQueryScopedIndex, InMemoryScopedIndex, DuckRunner, list[IndexedDocument]]:
    docs = corpus(seed)
    rows = table_rows(
        {
            "id": d.canonical_id,
            "department": d.tags.department,
            "section": d.tags.section,
            "classification": d.tags.classification,
            "file_no": d.tags.file_no,
            "doc_type": d.doc_type,
            "issue_date": d.issue_date,
            "subject": d.subject,
        }
        for d in docs
    )
    runner = DuckRunner(rows)
    return BigQueryScopedIndex(runner, "p.d.documents"), InMemoryScopedIndex(docs), runner, docs


SCOPES = [
    scope("FIN01", wide=True, rank=1),
    scope("FIN01", wide=False, rank=3, sections=("A",)),
    scope("GAD01", wide=False, rank=2, files=("F-1",)),
    scope("ESE01", wide=False, rank=0),
    scope("GAD01", wide=True, rank=3),
]


@pytest.mark.parametrize("seed", range(4))
def test_filter_matches_the_reference(seed: int) -> None:
    bq, ref, _, _ = both(seed)
    rng = random.Random(seed)  # noqa: S311
    for sc in SCOPES:
        for _ in range(15):
            c = L1Criteria(
                department=rng.choice([None, "FIN01", "GAD01"]),
                doc_types=frozenset(
                    rng.sample(["Government Order", "Memo", "Circular"], rng.randint(0, 2))
                ),
                issued_from=rng.choice([None, dt.date(2018, 1, 1)]),
                issued_to=rng.choice([None, dt.date(2022, 6, 30)]),
                subject_terms=rng.choice([(), ("leave",), ("Transfer", "teachers"), ("zzz",)]),
            )
            got = bq.filter(c, sc)
            assert got == ref.filter(c, sc)
            assert all(sc.admits(d.tags) for d in got)


@pytest.mark.parametrize("seed", range(4))
def test_exact_matches_the_reference(seed: int) -> None:
    bq, ref, _, docs = both(seed)
    asked = [d.canonical_id for d in docs] + [d.canonical_id.split("-D")[0] for d in docs]
    for sc in SCOPES:
        for cid in [*asked, "AP-FIN01-GOMS-999-2020", "not an id"]:
            got, want = bq.exact(cid, sc), ref.exact(cid, sc)
            assert sorted(got, key=lambda d: d.canonical_id) == sorted(
                want, key=lambda d: d.canonical_id
            )


def test_scope_is_in_the_sql_and_out_of_scope_rows_are_never_read_back() -> None:
    bq, _, runner, docs = both(1)
    sc = scope("ESE01", wide=False, rank=0)  # sees published, unclassified instruments only
    got = bq.filter(L1Criteria(), sc)
    assert got and all(
        d.tags.classification == "UNCLASSIFIED" and d.tags.file_no is None for d in got
    )
    sql, params = runner.seen[-1]
    assert "@scope_department" in sql and params["cleared_marks"] == ["UNCLASSIFIED"]
    assert "ODD-MARK" not in params["cleared_marks"] + params["public_marks"]  # unknown → outside
    raw = runner.db.execute("SELECT count(*) FROM documents").fetchone()[0]
    assert len(got) < raw == len(docs)


def test_templates_are_fixed_text_with_bound_parameters_only() -> None:
    bq, _, runner, _ = both(2)
    hostile = "x' OR 1=1 --"
    assert bq.filter(L1Criteria(subject_terms=(hostile,), department=hostile), SCOPES[0]) == []
    sql, _ = runner.seen[-1]
    assert hostile not in sql
    assert sql == FILTER_SQL.format(
        columns=sql.split("SELECT ")[1].split(" FROM")[0], table="p.d.documents"
    )
    assert "{" not in EXACT_SQL.replace("{columns}", "").replace("{table}", "")
    with pytest.raises(ValueError, match="project.dataset.table"):
        BigQueryScopedIndex(runner, "p.d.documents; DROP TABLE x")
