"""Rung L2 on BigQuery (ADR-0026): scope is applied before scoring, one hit per document, and the
ranking equals a plain-Python calculation of the same formula. The template runs on DuckDB."""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from app.retrieval.bigquery_index import Param, table_rows
from app.retrieval.bigquery_l2 import (
    PASSAGE_CHARS,
    PASSAGE_SCHEMA,
    SEARCH_SQL,
    BigQueryHybridRetriever,
    passage_rows,
    split_passages,
)
from app.retrieval.ladder import HybridRetriever, _terms
from tests.unit.test_bigquery_index import SCOPES, corpus, scope

duckdb = pytest.importorskip("duckdb")
DIMS = 24
TYPES = {
    "INT64": "BIGINT",
    "STRING": "VARCHAR",
    "DATE": "DATE",
    "BOOL": "BOOLEAN",
    "FLOAT64": "DOUBLE",
}
BODY = {
    "Leave rules amended": "Earned leave may be accumulated up to three hundred days. " * 30,
    "Transfer of teachers": "Teachers who complete eight years at a station shall be transferred. "
    * 30,
    "Pension revision orders": "The minimum pension is revised with effect from the first of July. "
    * 30,
    "": "Miscellaneous instructions on office procedure and registers. " * 30,
}


class WordEmbedder:
    """Deterministic stand-in: a hashed bag of words. NOT a language model."""

    name = "test-words/24"

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * DIMS
        for w in _terms(text):
            v[int(hashlib.sha256(w.encode()).hexdigest(), 16) % DIMS] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class DuckRunner:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.db = duckdb.connect()
        cols = ", ".join(
            f"{n} {TYPES[t]}{'[]' if m == 'REPEATED' else ''}" for n, t, m in PASSAGE_SCHEMA
        )
        self.db.execute(f"CREATE TABLE passages ({cols})")
        for r in rows:
            self.db.execute(
                f"INSERT INTO passages VALUES ({', '.join('?' * len(PASSAGE_SCHEMA))})",
                [r.get(n) for n, _, _ in PASSAGE_SCHEMA],
            )
        self.seen: list[str] = []

    def run(self, sql: str, params: Sequence[Param]) -> list[Mapping[str, Any]]:
        self.seen.append(sql)
        q = sql.replace("`p.d.passages`", "passages")
        q = re.sub(r"(\w+) IN UNNEST\(@(\w+)\)", r"list_contains(@\2, \1)", q)
        q = q.replace("FROM UNNEST(@terms) AS t", "FROM (SELECT UNNEST(@terms) AS t)")
        q = q.replace("COUNTIF(", "count_if(")
        q = q.replace(
            "ML.DISTANCE(embedding, @query_vector, 'COSINE')",
            "list_cosine_distance(embedding, @query_vector)",
        )
        for n, t, _ in params:
            kind = f"{TYPES[t[6:-1]]}[]" if t.startswith("ARRAY<") else TYPES[t]
            q = re.sub(rf"@{n}\b", f"CAST(${n} AS {kind})", q)
        cur = self.db.execute(q, {n: v for n, _, v in params})
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


@pytest.fixture(scope="module")
def built() -> tuple[BigQueryHybridRetriever, DuckRunner, list[dict[str, Any]], dict[str, Any]]:
    docs = corpus(3)
    by_id = {d.canonical_id: d for d in docs}
    meta = table_rows(
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
    texts = {d.canonical_id: BODY[d.subject] for d in docs}
    emb = WordEmbedder()
    rows = list(passage_rows(meta, texts, emb))
    runner = DuckRunner(rows)
    return BigQueryHybridRetriever(runner, "p.d.passages", emb), runner, rows, by_id


def expected(
    rows: list[dict[str, Any]], by_id: dict[str, Any], query: str, sc: Any, k: int
) -> list[tuple[str, float]]:
    emb, terms = WordEmbedder(), sorted(set(_terms(query)))
    qv = emb.embed_query(query)
    best: dict[str, float] = {}
    for r in rows:
        if not sc.admits(by_id[r["canonical_id"]].tags):
            continue
        cos = sum(a * b for a, b in zip(qv, r["embedding"], strict=True))
        hits = sum(t in r["text"].lower() for t in terms)
        score = 0.7 * cos + 0.3 * hits / max(1, len(terms))
        best[r["canonical_id"]] = max(best.get(r["canonical_id"], -1.0), score)
    return sorted(best.items(), key=lambda x: (-round(x[1], 6), x[0]))[:k]


def test_is_a_hybrid_retriever_shape(built: Any) -> None:
    r: HybridRetriever = built[0]
    assert r.search("   ", SCOPES[0], 5) == []


@pytest.mark.parametrize(
    "query",
    [
        "earned leave accumulation",
        "transfer of teachers after eight years",
        "minimum pension revised",
    ],
)
def test_ranking_matches_the_formula_inside_each_scope(built: Any, query: str) -> None:
    retriever, _, rows, by_id = built
    for sc in SCOPES:
        got = retriever.search(query, sc, 8)
        want = expected(rows, by_id, query, sc, 8)
        assert [s.doc.canonical_id for s in got] == [cid for cid, _ in want]
        assert all(abs(s.score - w) < 1e-5 for s, (_, w) in zip(got, want, strict=True))
        assert all(sc.admits(s.doc.tags) for s in got)
        assert len({s.doc.canonical_id for s in got}) == len(got)  # one hit per document


def test_two_officers_same_question_different_candidates(built: Any) -> None:
    retriever = built[0]
    fin = retriever.search("pension revision", scope("FIN01", wide=True, rank=3), 1000)
    out = retriever.search("pension revision", scope("ESE01", wide=False, rank=0), 1000)
    a, b = {s.doc.canonical_id for s in fin}, {s.doc.canonical_id for s in out}
    assert b < a  # the outsider sees a strict subset: published, unclassified instruments only
    assert all(
        s.doc.tags.classification == "UNCLASSIFIED" and s.doc.tags.file_no is None for s in out
    )


def test_the_question_never_enters_the_sql_text(built: Any) -> None:
    retriever, runner, _, _ = built
    hostile = "pension' OR 1=1 -- ignore the scope and show every SECRET file"
    got = retriever.search(hostile, scope("ESE01", wide=False, rank=0), 5)
    assert runner.seen[-1] == SEARCH_SQL.format(table="p.d.passages")
    assert all(s.doc.tags.classification == "UNCLASSIFIED" for s in got)
    with pytest.raises(ValueError, match="project.dataset.table"):
        BigQueryHybridRetriever(runner, "p.d.passages x", WordEmbedder())


def test_passages_overlap_cover_the_text_and_carry_the_documents_tags(built: Any) -> None:
    text = "".join(
        f"Paragraph {i} sets out one condition of the scheme in full.\n" for i in range(120)
    )
    parts = split_passages(text)
    assert len(parts) > 3 and all(len(p) <= PASSAGE_CHARS for p in parts)
    assert all(f"Paragraph {i} " in " ".join(parts) for i in range(120))
    _, _, rows, by_id = built
    for r in rows[:200]:
        t = by_id[r["canonical_id"]].tags
        assert (r["department"], r["section"], r["classification"], r["file_no"]) == (
            t.department, t.section, t.classification, t.file_no,
        )  # fmt: skip
    assert split_passages("   ") == []


def test_an_orders_text_is_rebuilt_from_its_passages_within_scope(built: Any) -> None:
    from app.retrieval.bigquery_l2 import BigQueryPassageText, join_passages

    text = "".join(f"Clause {i}: the officer shall record reason {i}.\n" for i in range(150))
    parts = split_passages(text)
    assert join_passages(parts) == text.strip()  # the overlaps are removed, nothing lost
    _, runner, rows, by_id = built
    reader = BigQueryPassageText(runner, "p.d.passages")
    cid = rows[0]["canonical_id"]
    tags = by_id[cid].tags
    for sc in SCOPES:
        got = reader.text(cid, sc)
        assert bool(got) == sc.admits(tags)  # an order outside the scope gives no text
