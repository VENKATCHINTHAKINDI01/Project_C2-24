# Developer commands. Run from the repo root. Unit tests never need cloud credentials (CLAUDE.md §11.13).
BACKEND := backend
UV := cd $(BACKEND) && env -u VIRTUAL_ENV uv

.PHONY: setup setup-all lint format typecheck test check eval run fe-install fe-dev fe-check local-up local-down

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
fe-install:       ## sandbox screens: install pinned npm deps (Node 20+)
	cd frontend/eoffice && npm ci
fe-dev:           ## sandbox screens on :5173 (proxies the API on :8080 — run `make run` too)
	cd frontend/eoffice && npm run dev
fe-check:         ## sandbox screens: typecheck, tests, production build
	cd frontend/eoffice && npm run typecheck && npm test && npm run build
local-up:         ## Postgres + Valkey + Spanner emulator (needs Docker running)
	docker compose --env-file .env -f infrastructure/local/docker-compose.yml up -d
local-down:
	docker compose --env-file .env -f infrastructure/local/docker-compose.yml down
