"""FastAPI entrypoint — one service, modular monolith (plan §3.5).

Composition root: the only place that wires the mock e-Office sandbox (`app.eoffice_mock`) to the
core through the `EOfficeConnector` (CLAUDE.md §2.4). Core modules never import the sandbox.
"""

from __future__ import annotations

import datetime as dt
import functools
from collections.abc import Awaitable, Callable

import yaml
from fastapi import FastAPI, Request, Response

from app.agents.routes import build_assist_router
from app.agents.runtime import AssistRuntime
from app.audit.log import AuditLog
from app.config import (
    Settings,
    get_settings,
    load_classification,
    load_hierarchy,
    load_runtime_config,
)
from app.connectors.eoffice import ConnectorError, EOfficeConnector
from app.retrieval.graph_expansion import NotCalibratedError
from app.retrieval.ladder import LadderConfig

SANDBOX_USER_HEADER = "X-Sandbox-User"  # simulated sign-in: sandbox only, never in production


def _sandbox_ladder(settings: Settings) -> LadderConfig:
    raw = yaml.safe_load(settings.sandbox_config_path.read_text(encoding="utf-8"))
    r = raw["retrieval"]
    return LadderConfig(
        l2_top_k=r["l2_top_k"], l2_min_score=r["l2_rerank_min_score"], l3_max_hops=r["l3_max_hops"]
    )


def _sync(run: AssistRuntime | None, connector: EOfficeConnector) -> None:
    if run is not None:
        run.sync(connector)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Config is loaded eagerly so a bad config fails at startup, not mid-request."""
    settings = settings or get_settings()
    hierarchy = load_hierarchy(settings.ontology_dir / "hierarchy.yaml")
    classification = load_classification(settings.ontology_dir / "classification.yaml")
    runtime = load_runtime_config(settings.runtime_config_path)

    app = FastAPI(title="C2-24 Institutional Memory", version="0.1.0")
    audit = AuditLog()
    app.state.audit = audit

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        """Liveness plus loaded config versions. No document data, no identity data."""
        return {
            "status": "ok",
            "env": settings.env.value,
            "hierarchy_version": hierarchy.version,
            "classification_version": classification.version,
            "runtime_config_version": runtime.version,
        }

    if not settings.sandbox_enabled:
        return app  # assist routes need a real connector + IAP identity (later)

    from app.eoffice_mock.adapter import adapter_from_seed, load_seed
    from app.eoffice_mock.corpus import artefacts_from_corpus
    from app.eoffice_mock.models import BANNER
    from app.eoffice_mock.routes import build_sandbox_router

    seed = load_seed(settings.sandbox_seed_path)
    sandbox_cfg = yaml.safe_load(settings.sandbox_config_path.read_text(encoding="utf-8"))
    holdback = (
        sandbox_cfg.get("replays", {})[settings.sandbox_replay] if settings.sandbox_replay else []
    )
    adapter = adapter_from_seed(
        seed, artefacts=artefacts_from_corpus(settings.sandbox_corpus_dir), holdback=holdback
    )
    app.state.adapter = adapter

    def identify(request: Request) -> str | None:
        """Simulated sign-in: only sandbox profiles with a login (never a staff post)."""
        uid = request.headers.get(SANDBOX_USER_HEADER)
        if not uid:
            return None
        try:
            return adapter.profile(uid).user_id
        except ConnectorError:
            return None

    @functools.cache
    def assist_runtime() -> AssistRuntime | None:
        try:
            cfg, calibrated = LadderConfig.from_runtime(runtime), True
        except NotCalibratedError:
            cfg, calibrated = _sandbox_ladder(settings), False  # labelled demo values
        return AssistRuntime.build(
            adapter.documents(),
            ontology_dir=settings.ontology_dir,
            hierarchy=hierarchy,
            classification=classification,
            cfg=cfg,
            calibrated=calibrated,
            as_of=seed.as_of,
            received_at=dt.datetime.combine(seed.as_of, dt.time(9), tzinfo=dt.UTC),
            open_files=adapter.open_files(),
        )

    app.state.assist_runtime = assist_runtime

    @app.middleware("http")
    async def banner(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Mock-Sandbox"] = "synthetic; not NIC e-Office"  # ASCII header
        return response

    app.include_router(
        build_sandbox_router(
            adapter=adapter,
            classification=classification,
            identify=identify,
            on_event=lambda: _sync(assist_runtime(), adapter),
        )
    )
    app.include_router(
        build_assist_router(
            connector=adapter, runtime=assist_runtime, audit=audit, identify=identify
        )
    )
    app.state.banner = BANNER
    return app


app = create_app()
