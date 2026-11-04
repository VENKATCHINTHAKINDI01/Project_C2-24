"""FastAPI entrypoint — one service, modular monolith (plan §3.5)."""

from __future__ import annotations

from fastapi import FastAPI

from app.config import (
    get_settings,
    load_classification,
    load_hierarchy,
    load_runtime_config,
)


def create_app() -> FastAPI:
    """Build the app. Config is loaded eagerly so a bad config fails at startup, not mid-request."""
    settings = get_settings()
    hierarchy = load_hierarchy(settings.ontology_dir / "hierarchy.yaml")
    classification = load_classification(settings.ontology_dir / "classification.yaml")
    runtime = load_runtime_config(settings.runtime_config_path)

    app = FastAPI(title="C2-24 Institutional Memory", version="0.1.0")

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

    return app


app = create_app()
