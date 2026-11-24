"""FastAPI entrypoint — one service, modular monolith (plan §3.5).

Composition root: the only place that wires the mock e-Office sandbox (`app.eoffice_mock`) to the
core through the `EOfficeConnector` (CLAUDE.md §2.4). Core modules never import the sandbox.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import functools
import logging
import re
import threading
import time
from collections.abc import AsyncIterator, Callable
from typing import Any, cast

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.agents.llm import llm_from_settings
from app.agents.routes import build_assist_router
from app.agents.runtime import AssistRuntime
from app.audit.log import AuditLog
from app.audit.pg_log import PostgresAuditLog
from app.auth.identity import IapIdentity, SandboxIdentity
from app.auth.rate_limit import RateLimiter
from app.cache.redis_cache import RedisAnswerCache, redis_client
from app.cache.semantic import SemanticIndex
from app.config import (
    Environment,
    Settings,
    get_settings,
    load_classification,
    load_hierarchy,
    load_runtime_config,
)
from app.connectors.eoffice import (
    UNAVAILABLE,
    ConnectorError,
    ConnectorUnavailableError,
    EOfficeConnector,
    GuardedConnector,
)
from app.hitl.feedback import (
    ActionLog,
    BigQueryActionLog,
    InMemoryActionLog,
    action_from_outcome,
)
from app.hitl.pg_queue import PostgresConfirmedText, PostgresReviewQueue
from app.http_guard import HttpGuard, ReadGate
from app.ingestion.detect import use_saved_scans
from app.ingestion.document_store import document_store_from_settings
from app.ingestion.ocr import OcrEngine, RecordedOcrFiles, ocr_from_settings, version_dir
from app.memory.history import InMemoryChatHistory, PostgresChatHistory
from app.memory.pg_session import PostgresSessionMemory
from app.memory.session import SessionMemory
from app.noting.draft_studio import load_formats
from app.noting.references import ReferenceConfig
from app.noting.workspace import InMemoryWorkspaceStore, PostgresWorkspaceStore
from app.pg import pg_from_settings
from app.retrieval.bigquery_index import BigQueryRunner
from app.retrieval.cloud import cloud_rungs_from_settings
from app.retrieval.graph_expansion import NotCalibratedError
from app.retrieval.ladder import LadderConfig
from app.retrieval.request_memo import RequestMemoMiddleware
from app.tracking.model_usage import InMemoryModelUsage, ModelQuota, PostgresModelUsage
from app.tracking.monitor import MonitorData, build_monitor, rows_from_bigquery
from app.tracking.profiler import ProfileMiddleware
from app.tracking.query_log import BigQueryQueryLog, InMemoryQueryLog, QueryLog
from app.tracking.signals import Person, Refusal, build_alerts, load_signal_config
from app.tracking.usage import Usage, summarise, summarise_bigquery


def _sandbox_ladder(settings: Settings) -> LadderConfig:
    raw = yaml.safe_load(settings.sandbox_config_path.read_text(encoding="utf-8"))
    r = raw["retrieval"]
    return LadderConfig(
        l2_top_k=r["l2_top_k"], l2_min_score=r["l2_rerank_min_score"], l3_max_hops=r["l3_max_hops"]
    )


def _sync(run: AssistRuntime | None, connector: EOfficeConnector) -> None:
    if run is not None:
        run.sync(connector)


def sandbox_ocr(settings: Settings, sandbox_cfg: dict[str, Any]) -> OcrEngine | None:
    """SANDBOX: replay recorded Document AI output (no GCP calls): the v1 synthetic scans when
    sandbox.yaml says so, and for v2 the real public orders' responses already paid for by the
    corpus OCR run (joined per file by data_collection/tools/join_ocr_cache.py; ADR-0020)."""
    version = settings.docai_ocr_processor_version
    roots = []
    if (
        settings.sandbox_seed != "v2"
        and (sandbox_cfg.get("ocr") or {}).get("provider") == "recorded"
    ):
        roots.append(version_dir(settings.ocr_recorded_dir, version))
    if settings.sandbox_seed != "v1" and settings.sandbox_public_corpus_dir is not None:
        roots.append(
            version_dir(
                settings.sandbox_public_corpus_dir / "staging" / "ocr_recorded" / "documentai",
                version,
            )
        )
    if not roots:
        return None
    # later roots win, as before; responses are read per file, never all held in memory
    return RecordedOcrFiles(list(reversed(roots)), f"documentai:recorded:{roots[0].name}")


log = logging.getLogger(__name__)


def query_log_from_settings(settings: Settings) -> QueryLog:
    if settings.query_log == "bigquery":
        if not settings.gcp_project_id:
            raise ValueError("C2_QUERY_LOG=bigquery needs C2_GCP_PROJECT_ID")
        table = f"{settings.gcp_project_id}.{settings.bq_audit_dataset}.query_log"
        return BigQueryQueryLog(settings.gcp_project_id, table)
    return InMemoryQueryLog()


def action_log_from_settings(settings: Settings) -> ActionLog:
    """Feedback goes where the query log goes, so the two join on query_id (ADR-0031)."""
    if settings.query_log == "bigquery":
        if not settings.gcp_project_id:
            raise ValueError("C2_QUERY_LOG=bigquery needs C2_GCP_PROJECT_ID")
        table = f"{settings.gcp_project_id}.{settings.bq_audit_dataset}.human_action"
        return BigQueryActionLog(settings.gcp_project_id, table)
    return InMemoryActionLog()


def app_logging() -> None:
    """The app's own log lines (logger "app.*") at INFO on stderr, where Cloud Run keeps them.
    Without this only WARNING and above came through, so the per-request "cloud queries" line
    never reached Cloud Logging (24 Nov 2026). Other libraries keep their own levels. The app
    logs IDs, counts and decisions only, never document text (CLAUDE.md §4.11)."""
    app_log = logging.getLogger("app")
    if not app_log.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
        app_log.addHandler(handler)
        app_log.setLevel(logging.INFO)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the app. Config is loaded eagerly so a bad config fails at startup, not mid-request."""
    settings = settings or get_settings()
    app_logging()
    use_saved_scans(settings.pdf_scan_cache_dir)
    hierarchy = load_hierarchy(settings.ontology_dir / "hierarchy.yaml")
    classification = load_classification(settings.ontology_dir / "classification.yaml")
    runtime = load_runtime_config(settings.runtime_config_path)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Cloud Run (C2_SANDBOX_WARM_START): build the sandbox while the instance starts (with
        # startup CPU boost), not inside the first officer's request; a bad build fails the start
        build = getattr(app.state, "assist_runtime", None)
        if settings.sandbox_warm_start and build is not None:
            started = time.monotonic()
            build()
            # print, not log.info: uvicorn leaves app loggers at WARNING, and this line is the
            # start-up timing the owner reads in Cloud Logging (not found on revision 00005)
            print(f"sandbox built at start in {time.monotonic() - started:.1f} s", flush=True)
        yield
        # tracking rows still waiting (plan §14.4): one last try, then say what is lost
        for buffer in getattr(app.state, "tracking_buffers", ()):
            buffer.close()

    local = settings.env is Environment.LOCAL  # the API's own docs only on a developer machine
    app = FastAPI(
        title="C2-24 Institutional Memory",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if local else None,
        redoc_url=None,
        openapi_url="/openapi.json" if local else None,
    )

    @app.exception_handler(ConnectorUnavailableError)
    async def _connector_down(_request: Request, _exc: ConnectorUnavailableError) -> JSONResponse:
        # plan §14.4: the assistant says the e-Office link is unavailable; never a partial answer
        return JSONResponse(status_code=503, content={"detail": UNAVAILABLE})

    pg = pg_from_settings(settings)  # None = in-memory state (sandbox default)
    audit: AuditLog = PostgresAuditLog(pg) if pg is not None else AuditLog()
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

    @app.get("/readyz")
    def readyz() -> JSONResponse:
        """Readiness: 200 once the assistant can answer (its runtime is built, or there is none to
        build); 503 while it is still building. For load balancers and start-up probes."""
        build = getattr(app.state, "assist_runtime", None)
        ready = build is None or build.cache_info().currsize > 0
        return JSONResponse(
            status_code=200 if ready else 503, content={"ready": ready, "env": settings.env.value}
        )

    if not settings.sandbox_enabled:
        app.add_middleware(
            HttpGuard,
            max_body_bytes=settings.max_body_bytes,
            upload_max_bytes=settings.upload_max_bytes,
        )
        return app  # assist routes need a real e-Office connector (not available yet)

    from app.eoffice_mock.adapter import adapter_from_seed, load_seed, merge_seeds
    from app.eoffice_mock.corpus import (
        arrivals_from_v2,
        artefacts_from_corpus,
        artefacts_from_v2,
    )
    from app.eoffice_mock.models import BANNER, SandboxProfile
    from app.eoffice_mock.routes import build_sandbox_router

    seeds, artefacts, arrivals = [], [], []
    if settings.sandbox_seed in ("v1", "both"):
        seeds.append(load_seed(settings.sandbox_seed_path))
        artefacts += artefacts_from_corpus(settings.sandbox_corpus_dir)
    if settings.sandbox_seed in ("v2", "both"):
        assert settings.sandbox_public_corpus_dir is not None  # enforced by Settings
        seeds.append(load_seed(settings.sandbox_v2_dir / "seed_v2.json"))
        artefacts += artefacts_from_v2(settings.sandbox_v2_dir, settings.sandbox_public_corpus_dir)
        arrivals = arrivals_from_v2(settings.sandbox_v2_dir, settings.sandbox_public_corpus_dir)
    seed = merge_seeds(*seeds)
    sandbox_cfg = yaml.safe_load(settings.sandbox_config_path.read_text(encoding="utf-8"))
    # MOCK monitoring officer(s) (ADR-0035): a sign-in for the monitoring pad, no files of their own
    monitors = [
        SandboxProfile.model_validate(p)
        for p in (sandbox_cfg.get("monitoring") or {}).get("officers", [])
    ]
    if monitors:
        seed = seed.model_copy(update={"profiles": [*seed.profiles, *monitors]})
    holdback = (
        sandbox_cfg.get("replays", {})[settings.sandbox_replay] if settings.sandbox_replay else []
    )
    adapter = adapter_from_seed(
        seed,
        artefacts=artefacts,
        holdback=holdback,
        arrivals=arrivals,
        approver_posts=(sandbox_cfg.get("order_approval") or {}).get("approver_posts", []),
    )
    app.state.adapter = adapter

    def known_login(uid: str) -> str | None:
        """A sandbox profile with a login (never a staff post)."""
        try:
            return adapter.profile(uid).user_id
        except ConnectorError:
            return None

    if settings.identity == "iap":
        # MOCK directory (sandbox.yaml `directory`): verified e-mail → e-Office user. A real
        # deployment reads the department's employee master through the connector.
        directory = {
            str(k).strip().lower(): str(v) for k, v in (sandbox_cfg.get("directory") or {}).items()
        }
        who: Callable[[Any], str | None] = IapIdentity(
            tuple(a.strip() for a in settings.iap_audiences.split(",") if a.strip()),
            lambda email: known_login(directory[email]) if email in directory else None,
        )
    else:
        who = SandboxIdentity(known_login)

    def identify(request: Request) -> str | None:
        """ADR-0039: the sandbox sign-in, or the verified IAP assertion (C2_IDENTITY)."""
        return who(request.headers)

    redis = redis_client(settings.redis_url) if settings.redis_url else None

    # functools.cache alone lets every request that arrives before the first build finishes start
    # its own build (several minutes of CPU each on a cold instance): one build, the rest wait
    build_lock = threading.Lock()
    built: list[AssistRuntime] = []

    @functools.cache
    def assist_runtime() -> AssistRuntime | None:
        with build_lock:
            if not built:
                built.append(_build_runtime())
            return built[0]

    def _build_runtime() -> AssistRuntime:
        build_started = time.monotonic()
        try:
            cfg, calibrated = LadderConfig.from_runtime(runtime), True
        except NotCalibratedError:
            cfg, calibrated = _sandbox_ladder(settings), False  # labelled demo values
        run = AssistRuntime.build(
            adapter.documents(),
            ontology_dir=settings.ontology_dir,
            hierarchy=hierarchy,
            classification=classification,
            cfg=cfg,
            calibrated=calibrated,
            as_of=seed.as_of,
            received_at=dt.datetime.combine(seed.as_of, dt.time(9), tzinfo=dt.UTC),
            open_files=adapter.open_files(),
            references=ReferenceConfig.model_validate(sandbox_cfg["references"])
            if "references" in sandbox_cfg
            else None,  # sandbox test values (labelled), never a guessed default
            ocr=ocr_from_settings(settings) or sandbox_ocr(settings, sandbox_cfg),
            documents=document_store_from_settings(settings),
            queue=PostgresReviewQueue(pg) if pg is not None else None,
            confirmed_text=PostgresConfirmedText(pg) if pg is not None else None,
            public_ocr_auto_pass=(sandbox_cfg.get("ocr") or {}).get(
                "public_auto_pass_min_confidence"
            )
            if settings.sandbox_seed != "v1"
            else None,
            llm=llm_from_settings(settings),
            # v1 rules cite the invented mock_v1 orders, v2 rules the real public orders: the two
            # sets share order numbers, so each seed uses its own file ("both" keeps v1's)
            rules_file="authority_rules_v2.yaml"
            if settings.sandbox_seed == "v2"
            else "authority_rules.yaml",
        )
        run.cloud = cloud_rungs_from_settings(settings, redis)  # None unless backend=cloud
        if redis is not None:  # Memorystore: answers shared by all instances (ADR-0035)
            run.stores.cache = RedisAnswerCache(redis, ttl_s=settings.cache_ttl_s)
        # reworded repeats (plan §10.3; ADR-0053): the index is per instance, the answers are not
        run.stores.reworded = SemanticIndex(enabled=runtime.cache.reworded_repeats)
        app.state.sandbox_build = {
            "built_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "build_seconds": round(time.monotonic() - build_started, 1),
            "warm_start": settings.sandbox_warm_start,
        }
        return run

    app.state.assist_runtime = assist_runtime
    app.add_middleware(ReadGate, lock_of=lambda: built[0].rw if built else None)

    actions = action_log_from_settings(settings)
    app.state.actions = actions  # tests read the in-memory log
    app.include_router(
        build_sandbox_router(
            adapter=adapter,
            classification=classification,
            identify=identify,
            on_event=lambda: _sync(assist_runtime(), adapter),
            on_outcome=lambda out: actions.write(action_from_outcome(out)),
        )
    )
    query_log = query_log_from_settings(settings)
    app.state.tracking_buffers = [
        b for b in (getattr(query_log, "buffer", None), getattr(actions, "buffer", None)) if b
    ]
    signals = load_signal_config(settings.monitoring_config_path)  # MOCK thresholds (ADR-0036)
    runner: list[Any] = []  # the BigQuery client, made on first use only

    def cache_stats() -> dict[str, Any]:
        run = app.state.assist_runtime()
        out: dict[str, Any] = run.stores.cache.stats() if run is not None else {}
        emb = getattr(getattr(run, "cloud", None), "embedder", None) if run else None
        if emb is not None and hasattr(emb, "hits"):
            out["embedding_hits"], out["embedding_misses"] = emb.hits, emb.misses
        if run is not None:  # reworded repeats (ADR-0053): this instance's counts
            out |= run.stores.reworded.stats()
        return out

    def monitor(since: dt.date, viewer_rank: int) -> MonitorData:
        start = getattr(app.state, "sandbox_build", None)
        if isinstance(query_log, InMemoryQueryLog) and isinstance(actions, InMemoryActionLog):
            recs, acts, cut = list(query_log.records), list(actions.actions), False
        else:
            if not runner:
                runner.append(
                    BigQueryRunner(
                        settings.gcp_project_id or "",
                        settings.gcp_region or "",
                        settings.bq_timeout_s,
                    )
                )
            audit_ds = f"{settings.gcp_project_id}.{settings.bq_audit_dataset}"
            recs, acts, cut = rows_from_bigquery(
                runner[0], f"{audit_ds}.query_log", f"{audit_ds}.human_action", since
            )
        # refused requests of the window, from the audit trail (who, when, which kind: no IDs)
        refusals = [
            Refusal(ts=e.at, user_id=e.user_id, action=e.action)
            for e in audit.refused_since(
                dt.datetime.combine(since, dt.time(), dt.UTC) - dt.timedelta(days=1)
            )
            if e.user_id
        ]
        people = {p.user_id: Person(role=p.post, department=p.department) for p in seed.profiles}
        alerts = build_alerts(signals, recs, refusals, acts, since, viewer_rank, people)
        return build_monitor(
            recs,
            acts,
            since,
            viewer_rank,
            start=start,
            cache=cache_stats(),
            truncated=cut,
            alerts=alerts,
        )

    def usage(since: dt.date) -> Usage:
        start = getattr(app.state, "sandbox_build", None)
        if isinstance(query_log, InMemoryQueryLog) and isinstance(actions, InMemoryActionLog):
            return summarise(query_log.records, actions.actions, since, start)
        if not runner:
            runner.append(
                BigQueryRunner(
                    settings.gcp_project_id or "", settings.gcp_region or "", settings.bq_timeout_s
                )
            )
        audit_ds = f"{settings.gcp_project_id}.{settings.bq_audit_dataset}"
        return summarise_bigquery(
            runner[0], f"{audit_ds}.query_log", f"{audit_ds}.human_action", since, start
        )

    # optional model calls per officer per day, and their log (ADR-0060 addendum): in Cloud SQL
    # when state is in Postgres, so the limit holds across instances and restarts
    model_usage = PostgresModelUsage(pg) if pg is not None else InMemoryModelUsage()
    # chat history (ADR-0066): the officer's own conversations, kept by the server
    chat_history = PostgresChatHistory(pg) if pg is not None else InMemoryChatHistory()
    app.state.chat_history = chat_history
    app.state.model_usage = model_usage
    app.include_router(
        build_assist_router(
            connector=cast(EOfficeConnector, GuardedConnector(adapter)),  # plan §14.4
            runtime=assist_runtime,
            audit=audit,
            identify=identify,
            memory=PostgresSessionMemory(pg) if pg is not None else SessionMemory(),
            query_log=query_log,
            actions=actions,
            usage=usage,
            monitoring_users=frozenset(
                [u.strip() for u in settings.monitoring_users.split(",") if u.strip()]
                + [p.user_id for p in monitors]
            ),
            log_questions=settings.query_log_text,
            monitor=monitor,
            signals=signals,
            limiter=RateLimiter(settings.rate_model_per_minute, settings.rate_any_per_minute),
            wording_quota=ModelQuota(model_usage, settings.draft_wording_per_day),
            draft_formats=load_formats(settings.draft_formats_path),  # validated at start
            workspaces=PostgresWorkspaceStore(pg) if pg is not None else InMemoryWorkspaceStore(),
            history=chat_history,
        )
    )
    app.state.banner = BANNER
    # each request reads a cloud record once (within-request reuse only; never across requests)
    app.add_middleware(RequestMemoMiddleware)
    if paths := frozenset(
        p.strip() for p in re.split(r"[,;]", settings.profile_paths) if p.strip()
    ):
        app.add_middleware(ProfileMiddleware, paths=paths)  # around the memo and the route
    # outermost: body limit, request ID, no-store headers, and the neutral answer to any failure
    app.add_middleware(
        HttpGuard,
        max_body_bytes=settings.max_body_bytes,
        upload_max_bytes=settings.upload_max_bytes,
    )
    return app


app = create_app()
