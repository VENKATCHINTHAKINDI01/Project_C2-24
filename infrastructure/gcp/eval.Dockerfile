# Evaluation image (ADR-0068): runs the billed / heavy evaluation suites as a Cloud Run Job, so no
# laptop has to hold the corpus or the compute. Built by 32_eval_job.sh from an allow-list.
# NOT the API image: it carries the synthetic e-files, the golden answer key and the test helpers
# the harness needs. The answer key stays evaluation-only: the app never reads it (CLAUDE.md §9.2).
ARG PYTHON_IMAGE=python:3.13-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.9
FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE}
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1 \
    PATH=/srv/backend/.venv/bin:$PATH
WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
# the backend with its dev group (TestClient) — the same locked versions as `make check`
RUN uv sync --frozen --all-extras --no-install-project
# RAGAS in its own environment, never in the backend's (ADR-0050)
RUN uv venv /srv/ragas --python /usr/local/bin/python3 \
 && uv pip install --python /srv/ragas/bin/python ragas==0.4.4 google-genai jsonref
COPY backend/app ./app
COPY backend/config ./config
COPY backend/prompts ./prompts
COPY backend/tests ./tests
COPY data /srv/data
COPY evaluation /srv/evaluation
COPY infrastructure/gcp/eval_job_entry.sh /srv/eval_job_entry.sh
# the RAGAS judge cache lives in the bucket (mounted at run time); the link is made here because
# /srv/evaluation is not writable by the job's user
RUN mkdir -p /srv/evaluation/reports \
 && ln -sfn /mnt/out/eval-cache/ragas /srv/evaluation/.ragas_cache \
 && chmod -R a+rX /srv \
 && chmod a+x /srv/eval_job_entry.sh \
 && useradd --uid 10001 --no-create-home app \
 && chown -R 10001 /srv/evaluation/reports /srv/data/synthetic/mock_v1/llm
USER 10001
ENTRYPOINT ["/srv/eval_job_entry.sh"]
