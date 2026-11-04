"""Typed settings and versioned config loading (plan §14.2, CLAUDE.md §11.5)."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

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
    sandbox_config_path: Path = REPO_ROOT / "backend" / "config" / "sandbox.yaml"

    @property
    def sandbox_enabled(self) -> bool:
        return self.sandbox if self.sandbox is not None else self.env is Environment.LOCAL

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


class IngestionConfig(_Frozen):
    extraction_confidence_min: float | None = Field(default=None, ge=0, le=1)


class RetrievalConfig(_Frozen):
    l2_top_k: int | None = Field(default=None, ge=1)
    l2_rerank_min_score: float | None = None
    l3_max_hops: int | None = Field(default=None, ge=1)


class CacheConfig(_Frozen):
    answer_ttl_seconds: int | None = Field(default=None, ge=1)
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
