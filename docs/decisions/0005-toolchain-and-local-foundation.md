# ADR-0005: Toolchain and local-first foundation (before GCP access)

- **Date:** 2026-10-22
- **Status:** Proposed (owner to accept)
- **Plan section:** §3.5, §14.1, §14.2, §14.6

## Context
GCP access is delayed. We need a runnable, tested repository so P0–P2 work can proceed on synthetic data, plus a ready setup kit for the day access arrives.

## Decision
- **Python 3.13** (plan floor 3.11; `requires-python >=3.11`). uv for env + lockfile (`backend/uv.lock`). Cloud Run image `python:3.13-slim`.
- **Core deps:** fastapi, uvicorn, pydantic v2, pydantic-settings, pyyaml. **Optional extras**, resolved and locked now but installed only when their phase starts: `agents` (langgraph, langgraph-checkpoint-postgres, psycopg), `gcp` (storage, documentai, bigquery, spanner, discoveryengine, secret-manager, google-genai, cloud-sql connector), `cache` (redis). Dev: pytest, httpx, ruff, mypy (strict).
- **Gemini SDK:** `google-genai` with `vertexai=True` (Vertex AI only, CLAUDE.md §2.1).
- **Config:** thresholds in `backend/config/runtime.yaml`, ontology in `data/ontology/`. Uncalibrated values are `null`, never guessed.
- **Local stand-ins:** docker-compose with Postgres 16 (Cloud SQL), Valkey (Memorystore, cache only), Spanner emulator. Unit tests need none of them.
- **GCP kit:** plain gcloud scripts in `infrastructure/gcp/`, dry-run by default; costly resources need a second flag. No Terraform (Tier 3).

## Alternatives considered
| Option | Why not |
|---|---|
| Use the conda env `aenv/` directly | No lockfile; harder to reproduce in the Cloud Run image |
| Python 3.11/3.12 | Not installed locally; all chosen libs resolve and import on 3.13 (checked 2026-10-22) |
| `vertexai` SDK generative modules | Google's newer unified SDK is google-genai; keeps one client for Gemini + embeddings |
| Terraform for setup | Tier 3, forbidden in the PoC (CLAUDE.md §2.3) |

## Consequences
Work can continue without cloud credentials. Cloud adapters plug in behind interfaces later. If Python is pinned lower, re-lock and re-run checks.

## Mentor input (if any)
—
