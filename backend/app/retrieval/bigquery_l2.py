"""Ladder rung L2 on BigQuery in asia-south1: meaning + keywords over passages (plan §3.2;
ADR-0026 — an approved substitution for Vertex AI Search, which has no India location).

One table of passages. Each row carries the passage text, its embedding and the SAME access tags
as its document, so the officer's scope is the WHERE clause of the search itself: a passage
outside the scope is never scored, ranked or returned (CLAUDE.md §4.2, §4.5). Rows are checked
again with `scope.admits` in code. One fixed template; the question reaches BigQuery only as a
bound vector and bound lower-cased words. Nothing here is written by a model.

Score (0 to 1) = `vector_weight` × cosine similarity of the best passage
               + (1 − `vector_weight`) × share of the question's words found in that passage.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.auth.models import Scope
from app.retrieval.bigquery_index import SCOPE_SQL, Param, QueryRunner, _doc, scope_params
from app.retrieval.ladder import ScoredDocument, _terms

log = logging.getLogger(__name__)

PASSAGE_CHARS = 1200
PASSAGE_OVERLAP = 200
DOC_COLUMNS = (
    "canonical_id, department, section, classification, file_no, doc_type, issue_date, subject"
)
# {table} is validated in the constructor; everything else that varies is a bound parameter.
SEARCH_SQL = (
    "SELECT * FROM (SELECT " + DOC_COLUMNS + ", passage_no, "  # noqa: S608
    "@vector_weight * (1 - ML.DISTANCE(embedding, @query_vector, 'COSINE')) "
    "+ (1 - @vector_weight) * (SELECT COUNTIF(STRPOS(LOWER(text), t) > 0) "
    "FROM UNNEST(@terms) AS t) / @term_count AS score "
    "FROM `{table}` WHERE " + SCOPE_SQL + ") "
    "QUALIFY ROW_NUMBER() OVER (PARTITION BY canonical_id ORDER BY score DESC, passage_no) = 1 "
    "ORDER BY score DESC, canonical_id LIMIT @top_k"
)


# {table} is validated in the constructor; every other value is bound
TEXT_SQL = (
    "SELECT passage_no, text FROM `{table}` WHERE canonical_id = @cid AND "  # noqa: S608
    + SCOPE_SQL
    + " ORDER BY passage_no"
)


def join_passages(pieces: Sequence[str]) -> str:
    """Undo the overlap of consecutive passages (each repeats up to PASSAGE_OVERLAP characters
    of the one before), so a quote across a boundary is found once."""
    out = ""
    for p in pieces:
        cut = 0
        for k in range(min(len(out), len(p), PASSAGE_OVERLAP + 50), 10, -1):
            if out.endswith(p[:k]):
                cut = k
                break
        out = f"{out}{p[cut:]}" if cut else (f"{out}\n{p}" if out else p)
    return out


class BigQueryPassageText:
    """The text of one public order, rebuilt from its passages, for the evidence package.
    The scope is in the WHERE clause, as for search: an order outside it returns no text."""

    def __init__(self, runner: QueryRunner, table: str) -> None:
        if not all(p.replace("-", "").replace("_", "").isalnum() for p in table.split(".")):
            raise ValueError("table must be project.dataset.table")
        self._runner, self._table = runner, table

    def text(self, canonical_id: str, scope: Scope) -> str:
        rows = self._runner.run(
            TEXT_SQL.format(table=self._table),
            [*scope_params(scope), ("cid", "STRING", canonical_id)],
        )
        return join_passages([str(r["text"]) for r in rows])


class Embedder(Protocol):
    name: str

    def embed_query(self, text: str) -> list[float]: ...

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...


class EmbeddingError(Exception):
    """The embedding model could not be reached or answered badly. Callers fail closed."""


_TRANSIENT = {408, 429, 500, 502, 503, 504}  # quota / overload / timeouts: worth another try


def _status(exc: BaseException) -> int | None:
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    return code if isinstance(code, int) else None


class VertexEmbedder:
    """Vertex AI text embeddings in the project's region (never the global endpoint).

    Built for a long batch job: a quota or overload answer (429 / 5xx) is retried with a growing
    pause (`retries` times, then the job fails closed); a model that takes one text per call is
    found on the first refused batch and is then called one text at a time for the rest of the
    run, so a refused batch is not repeated for every passage."""

    def __init__(
        self,
        project: str,
        location: str,
        model: str,
        dimensions: int,
        batch: int = 16,
        retries: int = 6,
        pause: Callable[[float], None] = time.sleep,
        client: Any | None = None,
    ) -> None:
        if not (project and location and model):
            raise EmbeddingError("embeddings need project, location and model")
        from google.genai import types

        if client is None:
            from google import genai

            client = genai.Client(vertexai=True, project=project, location=location)
        self._types = types
        self._client = client
        self._model, self._dims, self._batch = model, dimensions, max(1, batch)
        self._retries, self._pause = max(0, retries), pause
        self.name = f"{model}@{location}/{dimensions}"
        self.calls = 0  # requests sent (for the job's log)

    def _embed(self, texts: Sequence[str], task: str) -> list[list[float]]:
        for attempt in range(self._retries + 1):
            try:
                self.calls += 1
                res = self._client.models.embed_content(
                    model=self._model,
                    contents=list(texts),
                    config=self._types.EmbedContentConfig(
                        task_type=task, output_dimensionality=self._dims
                    ),
                )
                vectors = [list(e.values or []) for e in (res.embeddings or [])]
                break
            except Exception as exc:  # the SDK raises many types; none may pass silently
                if _status(exc) in _TRANSIENT and attempt < self._retries:
                    self._pause(min(60.0, 2.0 ** (attempt + 1)))
                    continue
                raise EmbeddingError(
                    f"embedding call failed: {type(exc).__name__} {_status(exc) or ''}".strip()
                ) from exc
        if len(vectors) != len(texts) or any(len(v) != self._dims for v in vectors):
            raise EmbeddingError("embedding answer has the wrong shape")
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "RETRIEVAL_QUERY")[0]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        i = 0
        while i < len(texts):
            part = texts[i : i + self._batch]
            try:
                out += self._embed(part, "RETRIEVAL_DOCUMENT")
            except EmbeddingError:
                if len(part) == 1:
                    raise
                self._batch = 1  # one text per call from now on (or one bad text: found next)
                continue
            i += len(part)
        return out


class BigQueryHybridRetriever:
    """`HybridRetriever` over `<project>.<dataset>.passages`."""

    def __init__(
        self, runner: QueryRunner, table: str, embedder: Embedder, vector_weight: float = 0.7
    ) -> None:
        if not all(p.replace("-", "").replace("_", "").isalnum() for p in table.split(".")):
            raise ValueError("table must be project.dataset.table")
        if not 0.0 <= vector_weight <= 1.0:
            raise ValueError("vector_weight must be between 0 and 1")
        self._runner, self._table, self._embedder = runner, table, embedder
        self._weight = vector_weight

    def search(self, query: str, scope: Scope, top_k: int) -> list[ScoredDocument]:
        """Scope is applied in the WHERE clause, before any passage is scored."""
        if not query.strip():
            return []
        terms = sorted(set(_terms(query)))
        params: list[Param] = [
            *scope_params(scope),
            ("query_vector", "ARRAY<FLOAT64>", self._embedder.embed_query(query)),
            ("terms", "ARRAY<STRING>", terms),
            ("term_count", "FLOAT64", float(max(1, len(terms)))),
            ("vector_weight", "FLOAT64", self._weight),
            ("top_k", "INT64", top_k),
        ]
        rows = self._runner.run(SEARCH_SQL.format(table=self._table), params)
        out = [ScoredDocument(doc=_doc(r), score=round(float(r["score"]), 6)) for r in rows]
        kept = [s for s in out if scope.admits(s.doc.tags)]
        if len(kept) != len(out):  # the SQL predicate and the rule disagree: a defect
            log.error("bigquery L2 returned %d rows the scope refuses", len(out) - len(kept))
        return kept


# ---- building the table (the ingestion job) ---------------------------------------------------

PASSAGE_SCHEMA = (  # name, type, mode
    ("canonical_id", "STRING", "REQUIRED"),
    ("passage_no", "INT64", "REQUIRED"),
    ("department", "STRING", "REQUIRED"),
    ("section", "STRING", "NULLABLE"),
    ("classification", "STRING", "REQUIRED"),
    ("file_no", "STRING", "NULLABLE"),
    ("doc_type", "STRING", "REQUIRED"),
    ("issue_date", "DATE", "NULLABLE"),
    ("subject", "STRING", "REQUIRED"),
    ("text", "STRING", "REQUIRED"),
    ("embedding", "FLOAT64", "REPEATED"),
    ("embedding_model", "STRING", "REQUIRED"),
)


def split_passages(text: str) -> list[str]:
    """Overlapping windows that end on a line or sentence break where one is near."""
    text = text.strip()
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + PASSAGE_CHARS)
        if end < len(text):
            cut = max(
                text.rfind("\n", start + PASSAGE_CHARS // 2, end),
                text.rfind(". ", start + PASSAGE_CHARS // 2, end),
            )
            if cut > start:
                end = cut + 1
        piece = text[start:end].strip()
        if piece:
            out.append(piece)
        if end >= len(text):
            break
        start = max(end - PASSAGE_OVERLAP, start + 1)
    return out


def passage_rows(
    documents: Sequence[Mapping[str, Any]], texts: Mapping[str, str], embedder: Embedder
) -> Iterator[dict[str, Any]]:
    """Rows for the passages table, one document at a time (documents = rows of the documents
    table, so each passage carries exactly its document's access tags). The subject line is
    part of every passage's embedded text, so a passage is findable by what the order is about."""
    for d in documents:
        pieces = split_passages(texts.get(d["canonical_id"], ""))
        if not pieces:
            continue
        vectors = embedder.embed_documents([f"{d['subject']}\n{p}" for p in pieces])
        for n, (piece, vec) in enumerate(zip(pieces, vectors, strict=True), 1):
            yield {
                "canonical_id": d["canonical_id"],
                "passage_no": n,
                "department": d["department"],
                "section": d.get("section"),
                "classification": d["classification"],
                "file_no": d.get("file_no"),
                "doc_type": d["doc_type"],
                "issue_date": d.get("issue_date"),
                "subject": d["subject"],
                "text": piece,
                "embedding": vec,
                "embedding_model": embedder.name,
            }


def text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class PassageParts:
    parts: tuple[str, ...]  # part file names to load, in order
    passages: int
    reused_documents: int  # embedded by an earlier run, text unchanged: not sent again
    embedded_documents: int  # sent to the embedding model in this run


def write_passage_parts(
    documents: Sequence[Mapping[str, Any]],
    texts: Mapping[str, str],
    embedder: Embedder,
    out_dir: Path,
    docs_per_part: int = 25,
    progress: Callable[[str], None] = lambda _m: None,
) -> PassageParts:
    """Passages in part files of `docs_per_part` documents, each followed by a small manifest
    written only once its part is complete. A run that stops (quota, timeout) loses at most
    one part; the next run keeps every complete part made with the same model whose documents'
    text is unchanged, and embeds only the rest — so a retry is not billed twice. Parts that are
    not kept stay in the folder unused (nothing is deleted); only the returned parts are loaded."""
    out_dir.mkdir(parents=True, exist_ok=True)
    want = {
        str(d["canonical_id"]): text_sha(texts.get(str(d["canonical_id"]), ""))
        for d in documents
        if split_passages(texts.get(str(d["canonical_id"]), ""))
    }
    kept: list[str] = []
    done: set[str] = set()
    passages = 0
    numbers = [0]
    for man in sorted(out_dir.glob("part-*.done.json")):
        numbers.append(int(man.name[5:10]))
        m = json.loads(man.read_text("utf-8"))
        docs: dict[str, str] = m.get("documents", {})
        ok = (
            m.get("model") == embedder.name
            and docs
            and all(want.get(c) == h for c, h in docs.items())
            and not set(docs) & done
            and (out_dir / m["part"]).exists()
        )
        if ok:
            kept.append(m["part"])
            done |= set(docs)
            passages += int(m["passages"])
    numbers += [int(f.name[5:10]) for f in out_dir.glob("part-*.jsonl")]
    todo = [
        d for d in documents if str(d["canonical_id"]) in want and d["canonical_id"] not in done
    ]
    if done:
        progress(f"  passages: {len(done)} documents kept from earlier parts, {len(todo)} to embed")
    n = max(numbers) + 1
    for i in range(0, len(todo), docs_per_part):
        chunk = todo[i : i + docs_per_part]
        name = f"part-{n:05d}.jsonl"
        count = 0
        with (out_dir / name).open("w", encoding="utf-8") as fh:
            for row in passage_rows(chunk, texts, embedder):
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
                count += 1
        manifest = {
            "part": name,
            "model": embedder.name,
            "passages": count,
            "documents": {str(d["canonical_id"]): want[str(d["canonical_id"])] for d in chunk},
        }
        (out_dir / f"part-{n:05d}.done.json").write_text(json.dumps(manifest), "utf-8")
        kept.append(name)
        passages += count
        n += 1
        progress(f"  passages: {i + len(chunk)}/{len(todo)} documents embedded")
    return PassageParts(tuple(kept), passages, len(done), len(todo))


def load_passages_from_uri(
    project: str, location: str, table: str, uri: str | Sequence[str]
) -> int:
    """Replace the passages table from newline-delimited JSON in Cloud Storage (atomic): one
    file, or the list of part files `write_passage_parts` returned."""
    from google.cloud import bigquery

    client = bigquery.Client(project=project, location=location)
    cfg = bigquery.LoadJobConfig(
        schema=[bigquery.SchemaField(n, t, mode=m) for n, t, m in PASSAGE_SCHEMA],
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    client.load_table_from_uri(
        uri if isinstance(uri, str) else list(uri), table, job_config=cfg
    ).result()
    return int(client.get_table(table).num_rows)
