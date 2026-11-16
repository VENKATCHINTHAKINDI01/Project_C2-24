"""The cloud rungs for the public order corpus, built from settings (ADR-0028)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.cache.redis_cache import CachedEmbedder
from app.config import Settings
from app.graph.postgres import PostgresGraphRepository
from app.pg import Pg, pg_from_settings
from app.retrieval.bigquery_index import BigQueryRunner, BigQueryScopedIndex
from app.retrieval.bigquery_l2 import BigQueryHybridRetriever, BigQueryPassageText, VertexEmbedder
from app.retrieval.cloud_sources import CloudSourceFiles
from app.retrieval.composite import GraphReader
from app.retrieval.ladder import HybridRetriever
from app.retrieval.scoped import ScopedRetriever


@dataclass(frozen=True)
class CloudRungs:
    index: ScopedRetriever  # L0 / L1 (BigQuery)
    graph: GraphReader  # L3 (Cloud SQL)
    l2: HybridRetriever | None  # BigQuery passages; None when no embedding model is set
    l2_min_score: float | None  # None = uncalibrated (never ends the ladder alone)
    pg: Pg | None = None
    passages: BigQueryPassageText | None = None  # order text for evidence (cloud-only orders)
    sources: CloudSourceFiles | None = None  # the files of cloud-only orders (mounted corpus)
    embedder: Any = None  # the question embedder (cached in Redis when configured)


def cloud_rungs_from_settings(settings: Settings, redis: Any = None) -> CloudRungs | None:
    """None for the in-memory backend. Misconfiguration raises at start (fail closed)."""
    if settings.retrieval_backend != "cloud":
        return None
    project, region = settings.gcp_project_id, settings.gcp_region
    assert project and region  # noqa: S101 — enforced by Settings
    pg = pg_from_settings(settings.model_copy(update={"state_store": "postgres"}))
    assert pg is not None  # noqa: S101 — postgres was just selected
    runner = BigQueryRunner(project, region)
    l2: BigQueryHybridRetriever | None = None
    embedder: Any = None
    if settings.embedding_model:
        embedder = VertexEmbedder(
            project, region, settings.embedding_model, settings.embedding_dimensions
        )
        if redis is not None:  # a repeated question skips the embedding call (ADR-0035)
            embedder = CachedEmbedder(embedder, redis, ttl_s=settings.embedding_cache_ttl_s)
        l2 = BigQueryHybridRetriever(runner, f"{project}.{settings.bq_dataset}.passages", embedder)
    return CloudRungs(
        index=BigQueryScopedIndex(runner, f"{project}.{settings.bq_dataset}.documents"),
        graph=PostgresGraphRepository(pg),
        l2=l2,
        l2_min_score=settings.l2_cloud_min_score,
        pg=pg,
        passages=BigQueryPassageText(runner, f"{project}.{settings.bq_dataset}.passages")
        if settings.embedding_model
        else None,
        sources=CloudSourceFiles(
            runner,
            f"{project}.{settings.bq_dataset}.documents",
            settings.sandbox_public_corpus_dir / "staging",
        )
        if settings.sandbox_public_corpus_dir is not None
        else None,
        embedder=embedder,
    )
