#!/usr/bin/env bash
# Build the backend image on GCP (Cloud Build) and push it to Artifact Registry repo "$PREFIX".
# Dry run by default; APPLY=1 executes. Nothing is built on the laptop and Docker is not needed there.
# Only what the image needs is sent (an allowlist copied to a temp folder): backend/{app,config,prompts},
# the lock files, data/ontology, data/schemas/postgres and the Dockerfile. Never: .env, data/synthetic, tests, the corpus.
# Billing: a few build-minutes per run. BUILD_REGION=global if the regional build pool is refused.
source "$(dirname "$0")/lib.sh"
ROOT="$(cd "$HERE/../.." && pwd)"
TAG="${TAG:-$(date +%Y%m%d-%H%M)}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${PREFIX}/backend"
BUILD_REGION="${BUILD_REGION:-$REGION}"
KEEP=(backend/Dockerfile backend/pyproject.toml backend/uv.lock backend/.python-version
      backend/app backend/config backend/prompts data/ontology data/schemas/postgres)
for p in "${KEEP[@]}"; do [[ -e "$ROOT/$p" ]] || { echo "missing $p" >&2; exit 1; }; done
CTX="$(mktemp -d)"; trap 'rm -rf "$CTX"' EXIT
for p in "${KEEP[@]}"; do
  mkdir -p "$CTX/$(dirname "$p")"
  cp -R "$ROOT/$p" "$CTX/$p"
done
find "$CTX" \( -name __pycache__ -o -name .DS_Store \) -prune -exec rm -rf {} +
# The image runs as a non-root user: every file must be world-readable. Files written by sync tools
# can be 0600 (14 Nov 2026: "Permission denied: /srv/backend/app/graph/__init__.py" at job start).
chmod -R u=rwX,go=rX "$CTX"
echo "build context: $(find "$CTX" -type f | wc -l | tr -d ' ') files, $(du -sh "$CTX" | cut -f1)  ->  $IMAGE:$TAG"
run gcloud builds submit "$CTX" --project "$PROJECT_ID" --region "$BUILD_REGION" \
  --config "$HERE/cloudbuild.backend.yaml" --substitutions "_IMAGE=${IMAGE}:${TAG}"
run gcloud artifacts docker tags add "${IMAGE}:${TAG}" "${IMAGE}:latest"
echo "image: ${IMAGE}:${TAG} (also tagged latest)"
