#!/usr/bin/env bash
# The officer-facing screens on Cloud Run behind IAP (plan §2.1, §3.5, §11; ADR-0032).
# Dry run by default; APPLY=1 executes. Before: 20_api_service.sh (c2-api must exist).
#   - image: frontend/Dockerfile (built screens + a small pass-through server), built on Cloud Build
#   - service c2-frontend, runs as c2-frontend; reaches c2-api with its own ID token (run.invoker on
#     c2-api only). c2-api stays private (IAM); people reach c2-frontend only through IAP.
#   - IAP_MEMBERS: who may open it, comma-separated, e.g. "user:a@example.com,group:fellows@example.com"
#     (required with APPLY=1). Organisation accounts work with Google's managed OAuth client; accounts
#     outside the organisation need an External consent screen + own OAuth client (console, once).
#   - the sandbox sign-in (choosing an officer profile) stays simulated, as in plan §11.4
#   - PART=dev (developer, roles/editor is enough): build the image, deploy c2-frontend with IAP on.
#     PART=owner (project owner / Run Admin + IAP Admin): the three IAM bindings — c2-frontend may call
#     c2-api; the IAP agent may call c2-frontend; IAP_MEMBERS may pass IAP. Default: both, in order.
#     Found 15 Nov 2026: roles/editor cannot set IAM policy on a service (run.services.setIamPolicy).
#   - TAG=<existing tag> with PART=dev SKIP_BUILD=1 deploys an image already built
# Billing: CPU only while a request runs (scales to zero); IAP itself has no charge for this use.
source "$(dirname "$0")/lib.sh"
ROOT="$(cd "$HERE/../.." && pwd)"
SERVICE="${PREFIX}-frontend"
API="${PREFIX}-api"
TAG="${TAG:-$(date +%Y%m%d-%H%M)}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${PREFIX}/frontend"
BUILD_REGION="${BUILD_REGION:-$REGION}"
PART="${PART:-all}"
if [[ "$APPLY" == "1" && "$PART" != "dev" && -z "${IAP_MEMBERS:-}" ]]; then
  echo "Set IAP_MEMBERS (who may open the screens), e.g. IAP_MEMBERS=user:you@example.com" >&2; exit 1
fi
KEEP=(frontend/Dockerfile frontend/server/server.py frontend/eoffice/package.json
      frontend/eoffice/package-lock.json frontend/eoffice/index.html frontend/eoffice/tsconfig.json
      frontend/eoffice/vite.config.ts frontend/eoffice/src)
for p in "${KEEP[@]}"; do [[ -e "$ROOT/$p" ]] || { echo "missing $p" >&2; exit 1; }; done
CTX="$(mktemp -d)"; trap 'rm -rf "$CTX"' EXIT
for p in "${KEEP[@]}"; do mkdir -p "$CTX/$(dirname "$p")"; cp -R "$ROOT/$p" "$CTX/$p"; done
find "$CTX" \( -name .DS_Store -o -name '*.test.ts' -o -name '*.test.tsx' \) -prune -exec rm -rf {} +
chmod -R u=rwX,go=rX "$CTX"
echo "build context: $(find "$CTX" -type f | wc -l | tr -d ' ') files  ->  $IMAGE:$TAG"

if [[ "$PART" != "owner" ]]; then
  run gcloud services enable iap.googleapis.com --project "$PROJECT_ID"
  if [[ "${SKIP_BUILD:-0}" != "1" ]]; then
    run gcloud builds submit "$CTX" --project "$PROJECT_ID" --region "$BUILD_REGION" \
      --config "$HERE/cloudbuild.frontend.yaml" --substitutions "_IMAGE=${IMAGE}:${TAG}"
    run gcloud artifacts docker tags add "${IMAGE}:${TAG}" "${IMAGE}:latest"
  fi
  if [[ "$APPLY" == "1" ]]; then
    API_URL="$(gcloud run services describe "$API" --project "$PROJECT_ID" --region "$REGION" --format 'value(status.url)')"
  else
    API_URL="https://${API}-<hash>.${REGION}.run.app"
  fi
  run gcloud run deploy "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --image "${IMAGE}:${TAG}" \
    --service-account "$(sa_email frontend)" --no-allow-unauthenticated --iap \
    --set-env-vars "C2_API_URL=${API_URL}" \
    --cpu 1 --memory 512Mi --timeout 900 --min-instances 0 --max-instances 2 --port 8080
fi
if [[ "$PART" != "dev" ]]; then
  echo "--- OWNER: IAM bindings (needs Run Admin + IAP Admin) ---"
  if [[ "$APPLY" == "1" ]]; then
    NUMBER="$(gcloud projects describe "$PROJECT_ID" --format 'value(projectNumber)')"
  else
    NUMBER="<project-number>"
  fi
  # c2-frontend may call c2-api (and nothing else)
  run gcloud run services add-iam-policy-binding "$API" --project "$PROJECT_ID" --region "$REGION" \
    --member "serviceAccount:$(sa_email frontend)" --role roles/run.invoker
  # IAP calls the service as its own agent
  run gcloud run services add-iam-policy-binding "$SERVICE" --project "$PROJECT_ID" --region "$REGION" \
    --member "serviceAccount:service-${NUMBER}@gcp-sa-iap.iam.gserviceaccount.com" --role roles/run.invoker
  IFS=',' read -r -a MEMBERS <<< "${IAP_MEMBERS:-user:<you@example.com>}"
  for m in "${MEMBERS[@]}"; do
    run gcloud iap web add-iam-policy-binding --project "$PROJECT_ID" --region "$REGION" \
      --resource-type cloud-run --service "$SERVICE" --member "$m" --role roles/iap.httpsResourceAccessor
  done
fi
echo "open:  the c2-frontend URL (gcloud run services describe ${SERVICE} --region ${REGION} --format 'value(status.url)')"
