# Frontend image for Cloud Run (plan §2.1; ADR-0032): the built e-Office screens + a small server
# that forwards API calls to the private c2-api with this service's own ID token.
# Build from the repo root:  docker build -f frontend/Dockerfile -t c2-frontend .
FROM node:24-slim AS web
WORKDIR /src
COPY frontend/eoffice/package.json frontend/eoffice/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/eoffice/index.html frontend/eoffice/tsconfig.json frontend/eoffice/vite.config.ts ./
COPY frontend/eoffice/src ./src
RUN npx tsc --noEmit && npx vite build

FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# same versions as backend/uv.lock
RUN pip install starlette==1.9.0 uvicorn==0.54.0 httpx==0.28.1 google-auth==2.62.0 requests==2.34.2
WORKDIR /srv/server
COPY frontend/server/server.py ./
COPY --from=web /src/dist /srv/web
RUN useradd --uid 10001 app
USER app
EXPOSE 8080
CMD ["uvicorn", "server:from_env", "--factory", "--host", "0.0.0.0", "--port", "8080"]
