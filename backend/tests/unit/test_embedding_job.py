"""The passage-embedding job must survive quota answers and be resumable without paying twice
(rung L2, ADR-0026). No cloud: the Vertex client and the embedder are stand-ins."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.retrieval.bigquery_l2 import (
    EmbeddingError,
    VertexEmbedder,
    write_passage_parts,
)

DIMS = 4


class ApiError(Exception):
    def __init__(self, code: int) -> None:
        super().__init__(f"status {code}")
        self.code = code


class FakeModels:
    """Answers like the SDK. `script` = what each call does: "ok", or an HTTP status to raise.
    `single_only` = the model refuses more than one text per call (400)."""

    def __init__(self, script: Sequence[Any] = (), single_only: bool = False) -> None:
        self.script = list(script)
        self.single_only = single_only
        self.sizes: list[int] = []

    def embed_content(self, *, model: str, contents: list[str], config: Any) -> Any:
        self.sizes.append(len(contents))
        step = self.script.pop(0) if self.script else "ok"
        if step != "ok":
            raise ApiError(int(step))
        if self.single_only and len(contents) > 1:
            raise ApiError(400)
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.5] * DIMS) for _ in contents])


def _embedder(models: FakeModels, pauses: list[float], retries: int = 6) -> VertexEmbedder:
    return VertexEmbedder(
        "p",
        "asia-south1",
        "m",
        DIMS,
        batch=4,
        retries=retries,
        pause=pauses.append,
        client=SimpleNamespace(models=models),
    )


def test_quota_answers_are_waited_out_with_growing_pauses() -> None:
    models, pauses = FakeModels(script=[429, 503, "ok"]), []
    assert len(_embedder(models, pauses).embed_documents(["a", "b"])) == 2
    assert pauses == [2.0, 4.0] and models.sizes == [2, 2, 2]


def test_retries_end_and_the_job_fails_closed() -> None:
    models, pauses = FakeModels(script=[429] * 10), []
    with pytest.raises(EmbeddingError):
        _embedder(models, pauses, retries=2).embed_query("x")
    assert len(pauses) == 2


def test_a_model_that_takes_one_text_per_call_is_found_once() -> None:
    models, pauses = FakeModels(single_only=True), []
    emb = _embedder(models, pauses)
    assert len(emb.embed_documents([f"t{i}" for i in range(9)])) == 9
    assert models.sizes == [4] + [1] * 9  # one refused batch, then one text per call
    assert pauses == []  # a refusal (400) is not retried as if it were quota


def test_a_text_the_model_refuses_alone_is_an_error() -> None:
    models = FakeModels(script=["ok", 400, 400])
    with pytest.raises(EmbeddingError):
        _embedder(models, []).embed_documents(["a", "b", "c", "d", "e"])


# --- resumable part files --------------------------------------------------------------------


class CountingEmbedder:
    def __init__(self, name: str = "m@asia-south1/4", fail_after: int | None = None) -> None:
        self.name = name
        self.fail_after = fail_after
        self.texts = 0

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * DIMS

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if self.fail_after is not None and self.texts + len(texts) > self.fail_after:
            raise EmbeddingError("quota")
        self.texts += len(texts)
        return [[0.1] * DIMS for _ in texts]


def _corpus(n: int) -> tuple[list[dict[str, Any]], dict[str, str]]:
    docs = [
        {
            "canonical_id": f"AP-FIN01-GOMS-{i}-2024",
            "department": "FIN01",
            "section": None,
            "classification": "UNCLASSIFIED",
            "file_no": None,
            "doc_type": "G.O.Ms",
            "issue_date": "2024-01-01",
            "subject": f"Order {i}",
        }
        for i in range(1, n + 1)
    ]
    texts = {d["canonical_id"]: f"Text of order {d['canonical_id']}. " * 10 for d in docs}
    return docs, texts


def _loaded(out: Path, parts: Sequence[str]) -> list[str]:
    rows = [json.loads(x) for p in parts for x in (out / p).read_text().splitlines()]
    return [r["canonical_id"] for r in rows]


def test_a_stopped_run_keeps_its_finished_parts_and_the_next_run_embeds_only_the_rest(
    tmp_path: Path,
) -> None:
    docs, texts = _corpus(10)
    with pytest.raises(EmbeddingError):  # quota ends the first run inside the third part
        write_passage_parts(docs, texts, CountingEmbedder(fail_after=5), tmp_path, docs_per_part=2)
    assert len(list(tmp_path.glob("part-*.done.json"))) == 2  # two complete parts
    again = CountingEmbedder()
    res = write_passage_parts(docs, texts, again, tmp_path, docs_per_part=2)
    assert (res.reused_documents, res.embedded_documents) == (4, 6)
    assert again.texts == 6  # nothing embedded twice
    ids = _loaded(tmp_path, res.parts)
    assert sorted(set(ids)) == sorted(d["canonical_id"] for d in docs)
    assert len(ids) == len(set(ids)) == res.passages  # each order once (one passage each here)


def test_changed_text_or_another_model_is_embedded_again(tmp_path: Path) -> None:
    docs, texts = _corpus(4)
    write_passage_parts(docs, texts, CountingEmbedder(), tmp_path, docs_per_part=2)
    texts[docs[0]["canonical_id"]] = "A corrected reading of the order. " * 10
    emb = CountingEmbedder()
    res = write_passage_parts(docs, texts, emb, tmp_path, docs_per_part=2)
    assert (res.reused_documents, res.embedded_documents) == (2, 2)  # its whole part again
    ids = _loaded(tmp_path, res.parts)
    assert len(ids) == len(set(ids)) == 4
    other = CountingEmbedder(name="another-model@asia-south1/4")
    res = write_passage_parts(docs, texts, other, tmp_path, docs_per_part=2)
    assert (res.reused_documents, res.embedded_documents) == (0, 4)
    assert len(_loaded(tmp_path, res.parts)) == 4
