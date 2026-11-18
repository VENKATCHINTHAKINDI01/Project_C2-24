# Backend image: the C2-24 API (plan §3.5) and its one-shot jobs (migrations, graph build).
# Build from the repo root:
#   docker build -f backend/Dockerfile -t c2-backend .
# Base images are build arguments so a network without Docker Hub can use its own mirror
# (e.g. --build-arg PYTHON_IMAGE=<registry>/python:3.13-slim). Defaults are the public images.
ARG PYTHON_IMAGE=python:3.13-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.9
FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE}
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1 \
    PATH=/srv/backend/.venv/bin:$PATH
WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --frozen --no-dev --all-extras --no-install-project
COPY backend/app ./app
COPY backend/config ./config
COPY backend/prompts ./prompts
COPY data/ontology /srv/data/ontology
COPY data/schemas/postgres /srv/data/schemas/postgres
# The image runs as uid 10001: make the copied sources world-readable whatever their mode on the
# build machine (a file saved as 0600 broke the local build on 17 Nov 2026)
RUN chmod -R a+rX /srv/backend/app /srv/backend/config /srv/backend/prompts /srv/data \
 && useradd --uid 10001 --no-create-home app
USER 10001
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
