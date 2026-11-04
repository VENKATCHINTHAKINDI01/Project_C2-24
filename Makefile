# Developer commands. Run from the repo root. Unit tests never need cloud credentials (CLAUDE.md §11.13).
BACKEND := backend
UV := cd $(BACKEND) && env -u VIRTUAL_ENV uv

.PHONY: setup setup-all lint format typecheck test check eval run local-up local-down

setup:            ## core + dev deps
	$(UV) sync
setup-all:        ## also agents / gcp / cache extras
	$(UV) sync --all-extras
lint:
	$(UV) run ruff check . ../evaluation --config pyproject.toml
format:
	$(UV) run ruff format . ../evaluation --config pyproject.toml
typecheck:
	$(UV) run mypy
test:
	$(UV) run pytest -q
check: lint typecheck test
	$(UV) run ruff format --check . ../evaluation --config pyproject.toml
eval:             ## evaluation harness → evaluation/reports/ (exit 1 if any disclosure)
	$(UV) run python ../evaluation/run_eval.py
run:              ## local API on :8080
	$(UV) run uvicorn app.main:app --reload --port 8080
local-up:         ## Postgres + Valkey + Spanner emulator (needs Docker running)
	docker compose --env-file .env -f infrastructure/local/docker-compose.yml up -d
local-down:
	docker compose --env-file .env -f infrastructure/local/docker-compose.yml down
