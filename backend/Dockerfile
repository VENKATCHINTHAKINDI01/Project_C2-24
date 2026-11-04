# Backend image for Cloud Run (plan §3.5). Build from the repo root:
#   docker build -f backend/Dockerfile -t c2-backend .
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --all-extras --no-install-project
COPY backend/app ./app
COPY backend/config ./config
COPY backend/prompts ./prompts
COPY data/ontology /srv/data/ontology
RUN useradd --uid 10001 app
USER app
EXPOSE 8080
CMD ["/srv/backend/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
