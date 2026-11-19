"""Typed settings and versioned config loading (plan §14.2, CLAUDE.md §11.5)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Environment(StrEnum):
    LOCAL = "local"
    GCP = "gcp"


class Settings(BaseSettings):
    """Process settings from `C2_*` environment variables. Secrets never live here in plain text."""

    model_config = SettingsConfigDict(env_prefix="C2_", env_file=".env", extra="ignore")

    env: Environment = Environment.LOCAL
    gcp_project_id: str | None = None
    gcp_region: str | None = None
    ontology_dir: Path = REPO_ROOT / "data" / "ontology"
    runtime_config_path: Path = REPO_ROOT / "backend" / "config" / "runtime.yaml"
    # Mock e-Office sandbox (plan §11): SYNTHETIC data, simulated sign-in. Never on in GCP unless
    # explicitly enabled for a demo.
    sandbox: bool | None = None  # None → on for local, off for gcp
    sandbox_seed_path: Path = REPO_ROOT / "data" / "synthetic" / "mock_v1" / "eoffice" / "seed.json"
    sandbox_corpus_dir: Path = REPO_ROOT / "data" / "synthetic" / "mock_v1"
    # Which synthetic sandbox data to load (ADR-0020): "v1" mock corpus, "v2" the 201-file set on
    # real public G.O.s, or "both". v2 needs the public orders in the data root, outside the repo.
    sandbox_seed: Literal["v1", "v2", "both"] = "v1"
    sandbox_v2_dir: Path = REPO_ROOT / "data" / "synthetic" / "mock_v1" / "efiles_v2" / "eoffice"
    sandbox_public_corpus_dir: Path | None = (
        None  # data root holding staging/rule-library (ADR-0006)
    )
    # saved page reads of the public orders, written by the graph job (--pdf-scans); read-only.
    # Unset: PDFs are parsed at start as before (ADR-0028 addendum 2).
    pdf_scan_cache_dir: Path | None = None
    # build the sandbox when the service starts instead of at the first assistant call (Cloud Run)
    sandbox_warm_start: bool = False
    # sandbox officers who may open the usage dashboard (comma-separated IDs; empty = nobody).
    # Aggregates only, but who sees them is still a decision: mock until the department says.
    monitoring_users: str = ""
    # what counts as unusual activity on the pad (ADR-0036): MOCK until the department decides
    monitoring_config_path: Path = REPO_ROOT / "backend" / "config" / "monitoring.yaml"
    draft_formats_path: Path = REPO_ROOT / "backend" / "config" / "draft_formats.yaml"  # ADR-0044
    # Memorystore (Redis/Valkey) — cache only (ADR-0035). Unset: in-memory cache in this instance.
    # redis://[:password@]host:6379/0 ; the password comes from Secret Manager, never the repo.
    redis_url: str | None = None
    cache_ttl_s: int = Field(default=6 * 3600, ge=60)
    embedding_cache_ttl_s: int = Field(default=7 * 86400, ge=60)
    # Who is calling (ADR-0039). "sandbox": the mock sign-in (X-Sandbox-User). "iap": the IAP
    # assertion forwarded by the frontend, verified here, e-mail mapped through the directory.
    identity: Literal["sandbox", "iap"] = "sandbox"
    # comma-separated, e.g. /projects/<number>/locations/<region>/services/c2-frontend
    iap_audiences: str = ""
    # per-officer limits per minute (ADR-0039): model-backed actions / every assistant action
    rate_model_per_minute: int = Field(default=20, ge=1)
    rate_any_per_minute: int = Field(default=120, ge=1)
    # model-suggested draft wording per officer per day (ADR-0060 cost control; 0 = none). Only
    # requests that reach a configured model count; the draft itself is always prepared.
    draft_wording_per_day: int = Field(default=40, ge=0)
    # largest request body accepted (bytes); an OCR correction of a long scan fits in 1 MiB
    max_body_bytes: int = Field(default=1_048_576, ge=1024)
    # an officer's attachment (scanned letter, PDF): the only route allowed more (ADR-0045)
    upload_max_bytes: int = Field(default=10_485_760, ge=1024)
    sandbox_config_path: Path = REPO_ROOT / "backend" / "config" / "sandbox.yaml"
    sandbox_replay: str | None = None  # name of a replay in sandbox.yaml (e.g. "tp04")
    # OCR (plan §4.1; ADR-0017). "none": scans wait in review unread. "documentai": live calls
    # (billed per page), cached on disk by file hash. "recorded": replay saved responses only.
    ocr_provider: Literal["none", "documentai", "recorded"] = "none"
    ocr_recorded_dir: Path = REPO_ROOT / "data" / "synthetic" / "mock_v1" / "ocr" / "documentai"
    docai_location: str | None = None  # defaults to gcp_region
    docai_ocr_processor_id: str | None = None
    # Pinned OCR model (ADR-0017 point 4, owner-approved 11 Nov 2026). The processor default in
    # asia-south1 (v1.0, 2020) cannot read Telugu. Changing it = new OCR evaluation run first.
    docai_ocr_processor_version: str | None = "pretrained-ocr-v2.1.1-2025-01-31"
    ocr_language_hints: tuple[str, ...] = ("te", "en")
    # Gemini (plan §7; ADR-0017): grounded judgment for conflict types B / G. "none": not run (the
    # pre-send report says so); "vertex": live regional calls, cached on disk per model by request;
    # "recorded": replay that cache only (no GCP calls).
    llm_provider: Literal["none", "vertex", "recorded"] = "none"
    gemini_model: str = "gemini-3.5-flash"
    gemini_location: str | None = None  # defaults to gcp_region; never the global endpoint
    # Text embeddings for rung L2 (ADR-0026). No default: the model must be one that answers in
    # the project's region (infrastructure/gcp/17_embedding_check.py).
    embedding_model: str | None = None
    embedding_dimensions: int = 768
    llm_recorded_dir: Path = REPO_ROOT / "data" / "synthetic" / "mock_v1" / "llm"
    # Fallback when Gemini is down (ADR-0021): an open model on Ollama on THIS machine only.
    llm_fallback: Literal["none", "ollama"] = "none"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str | None = None  # e.g. the model you pulled with `ollama pull`; required
    llm_failover_threshold: int = Field(default=2, ge=1)  # primary failures in a row
    llm_failover_cooldown_s: float = Field(default=60.0, gt=0)  # wait before trying it again
    # Source-document store (ADR-0014 rule 7). "memory": sandbox; "gcs": private raw bucket, under
    # a prefix that says what the data is (synthetic corpus here, never mixed with real files).
    document_store: Literal["memory", "gcs"] = "memory"
    gcs_raw_bucket: str | None = None
    gcs_documents_prefix: str = "synthetic/mock_v1/sources"
    # Application state (plan §3.5): review decisions, confirmed OCR text, audit trail. "memory":
    # sandbox, lost on restart. "postgres": C2_PG_DSN (local/test) or Cloud SQL with IAM auth.
    state_store: Literal["memory", "postgres"] = "memory"
    pg_dsn: str | None = None  # local/test only; never a password-bearing DSN on GCP
    cloudsql_instance: str | None = None  # project:region:instance
    cloudsql_user: str | None = None  # IAM DB user, e.g. c2-api@<project>.iam
    cloudsql_db: str = "c2"
    pg_pool_size: int = Field(default=4, ge=1, le=32)  # per instance; Cloud SQL caps connections
    pg_connect_timeout_s: int = Field(default=10, ge=1)
    pg_statement_timeout_ms: int = Field(default=10_000, ge=100)
    # outbound call limits (ADR-0039): a stuck service ends the request closed, never hangs it
    llm_timeout_s: float = Field(default=60.0, gt=0)
    llm_max_output_tokens: int = Field(default=4096, ge=256)  # caps the cost of one live call
    bq_timeout_s: float = Field(default=30.0, gt=0)
    # Where the public-order rungs are read from (ADR-0028). "memory": everything is ingested at
    # start (sandbox default). "cloud": the officer's e-Office papers stay in memory and the public
    # corpus is read from BigQuery (L0-L2, dataset `bq_dataset`) and Cloud SQL (L3).
    retrieval_backend: Literal["memory", "cloud"] = "memory"
    # The L3 graph store for the cloud rungs (ADR-0048): "postgres" = Cloud SQL (ADR-0023, the
    # default and the fallback); "spanner" = Spanner Graph (instance + database below), switched on
    # after `27_spanner_graph.py check` shows both stores give the same walks.
    graph_backend: Literal["postgres", "spanner"] = "postgres"
    spanner_instance: str | None = None  # e.g. c2-spanner
    spanner_database: str = "c2graph"
    # Query tracking (plan §10.4; ADR-0029): "bigquery" streams one record per question into
    # <project>.<bq_audit_dataset>.query_log (IDs and metadata only). The same switch sends the
    # officers' feedback actions to <project>.<bq_audit_dataset>.human_action (ADR-0031).
    query_log: Literal["memory", "bigquery"] = "memory"
    # keep the officer's question text in the query log for the monitoring pad (plan §10.4
    # raw_query; ADR-0035). Never document text.
    query_log_text: bool = True
    bq_audit_dataset: str = "c2_audit"
    bq_dataset: str = "c2_metadata"
    # Evidence threshold for the BigQuery L2 score (0-1). None = not calibrated: its hits are
    # listed but never end the ladder at L2 by themselves (ADR-0026, ADR-0028).
    l2_cloud_min_score: float | None = Field(default=None, gt=0, le=1)

    @property
    def sandbox_enabled(self) -> bool:
        return self.sandbox if self.sandbox is not None else self.env is Environment.LOCAL

    @model_validator(mode="after")
    def _v2_requires_public_corpus(self) -> Settings:
        if self.sandbox_seed != "v1" and self.sandbox_public_corpus_dir is None:
            raise ValueError(
                "C2_SANDBOX_SEED=v2/both requires C2_SANDBOX_PUBLIC_CORPUS_DIR (the data root)"
            )
        return self

    @model_validator(mode="after")
    def _cloud_rungs_need_their_stores(self) -> Settings:
        if self.retrieval_backend == "cloud" and not (
            self.gcp_project_id and self.gcp_region and (self.pg_dsn or self.cloudsql_instance)
        ):
            raise ValueError(
                "C2_RETRIEVAL_BACKEND=cloud needs C2_GCP_PROJECT_ID, C2_GCP_REGION and a Cloud SQL "
                "connection (C2_CLOUDSQL_INSTANCE + C2_CLOUDSQL_USER, or C2_PG_DSN)"
            )
        return self

    @model_validator(mode="after")
    def _spanner_graph_needs_its_instance(self) -> Settings:
        if self.graph_backend == "spanner" and not (self.gcp_project_id and self.spanner_instance):
            raise ValueError(
                "C2_GRAPH_BACKEND=spanner needs C2_GCP_PROJECT_ID and C2_SPANNER_INSTANCE"
            )
        return self

    @model_validator(mode="after")
    def _identity_is_configured(self) -> Settings:
        if self.identity == "iap" and not self.iap_audiences.strip():
            raise ValueError("C2_IDENTITY=iap needs C2_IAP_AUDIENCES")
        return self

    @model_validator(mode="after")
    def _gcp_requires_project(self) -> Settings:
        if self.env is Environment.GCP and not (self.gcp_project_id and self.gcp_region):
            raise ValueError("C2_ENV=gcp requires C2_GCP_PROJECT_ID and C2_GCP_REGION")
        return self


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class HierarchyLevel(_Frozen):
    level: int = Field(ge=1)
    instrument: str
    label: str
    basis: str | None = None  # where the placing comes from (public source or "assumption")


class Hierarchy(_Frozen):
    """AP instrument hierarchy (plan §4.5). Draft until confirmed by the department."""

    version: str
    status: str
    levels: tuple[HierarchyLevel, ...]

    @model_validator(mode="after")
    def _contiguous_unique(self) -> Hierarchy:
        numbers = [lv.level for lv in self.levels]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("hierarchy levels must be 1..N in order")
        if len({lv.instrument for lv in self.levels}) != len(self.levels):
            raise ValueError("hierarchy instruments must be unique")
        return self


class ClassificationLevel(_Frozen):
    rank: int = Field(ge=0)
    name: str
    basis: str | None = None  # public source of the grade, or "assumption"


class Classification(_Frozen):
    """Classification order, CSMOP grading (ADR-0002)."""

    version: str
    status: str
    levels: tuple[ClassificationLevel, ...]

    @model_validator(mode="after")
    def _contiguous_unique(self) -> Classification:
        if [lv.rank for lv in self.levels] != list(range(len(self.levels))):
            raise ValueError("classification ranks must be 0..N-1 in order")
        if len({lv.name for lv in self.levels}) != len(self.levels):
            raise ValueError("classification names must be unique")
        return self

    def rank_of(self, name: str) -> int:
        """The level's rank; an unknown mark counts as the most restricted (fail closed)."""
        return next((lv.rank for lv in self.levels if lv.name == name), len(self.levels) - 1)


class IngestionConfig(_Frozen):
    extraction_confidence_min: float | None = Field(default=None, ge=0, le=1)


class RetrievalConfig(_Frozen):
    l2_top_k: int | None = Field(default=None, ge=1)
    l2_rerank_min_score: float | None = None
    l3_max_hops: int | None = Field(default=None, ge=1)


class CacheConfig(_Frozen):
    answer_ttl_seconds: int | None = Field(default=None, ge=1)
    # plan §10.3 (Tier 2; ADR-0053): a reworded repeat in the same scope, with the same anchors and
    # the same content words, is served from the scoped answer cache
    reworded_repeats: bool = False
    artifact_ttl_seconds: int | None = Field(default=None, ge=1)


class RuntimeConfig(_Frozen):
    """Versioned thresholds. `None` means uncalibrated; consumers must not substitute a guess."""

    version: str
    ingestion: IngestionConfig
    retrieval: RetrievalConfig
    cache: CacheConfig


def _load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_hierarchy(path: Path) -> Hierarchy:
    return Hierarchy.model_validate(_load_yaml(path))


def load_classification(path: Path) -> Classification:
    return Classification.model_validate(_load_yaml(path))


def load_runtime_config(path: Path) -> RuntimeConfig:
    return RuntimeConfig.model_validate(_load_yaml(path))


@lru_cache
def get_settings() -> Settings:
    return Settings()
