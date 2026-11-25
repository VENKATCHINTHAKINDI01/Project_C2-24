#!/usr/bin/env bash
# Evaluation on GCP instead of a laptop (ADR-0068): a Cloud Run Job runs the heavy / billed suites
# with the public corpus mounted read-only from the raw bucket, and writes the reports to
# gs://<project>-<prefix>-artifacts/eval-reports/. Dry run by default; APPLY=1 executes.
#
#   bash 32_eval_job.sh build                      # image from an allow-list (Cloud Build)
#   MODE=leakage bash 32_eval_job.sh run           # leakage_v2 sweep, all 21 officers (USERS=V01,V07 for some)
#   MODE=ragas bash 32_eval_job.sh run             # rag_samples --live + ragas_score --live (vs RAGAS_BASELINE)
#   MODE=conversation bash 32_eval_job.sh run      # conversation_check --live
#   MODE=all bash 32_eval_job.sh run               # the three in turn
#   bash 32_eval_job.sh fetch                      # today's runs into evaluation/reports/cloud/<run>/ (no overwrite)
#
#   - runs as c2-ingest (EVAL_SA=<name> for another): it already reads the raw bucket, writes the
#     artifacts bucket and calls Vertex AI, so no IAM change is needed. Never touches c2-api or
#     c2-frontend, their settings or their access (ADR-0065).
#   - the image is NOT the API image: it carries the synthetic e-files, the golden answer key and the
#     harness; it stays in the project's private Artifact Registry and never serves traffic.
#   - SYNTHETIC data and public orders only (CLAUDE.md §4.14).
# Billing: CPU and memory only while the job runs (leakage: 4 vCPU / 16 GiB, about 1-2 h for 21
# officers; no model calls). ragas / conversation: Gemini calls (billed; the RAGAS judge cache in the
# bucket makes a re-run of the same samples free). Nothing bills while idle.
source "$(dirname "$0")/lib.sh"
ROOT="$(cd "$HERE/../.." && pwd)"
JOB="${PREFIX}-eval"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${PREFIX}/eval"
TAG="${TAG:-$(date +%Y%m%d-%H%M)}"
RAW="${PROJECT_ID}-${PREFIX}-raw"
ART="${PROJECT_ID}-${PREFIX}-artifacts"
BUILD_REGION="${BUILD_REGION:-$REGION}"
MODE="${MODE:-leakage}"
LABEL="${LABEL:-cloud}"
RAGAS_BASELINE="${RAGAS_BASELINE:-2026-11-19-ragas-after-fixes.json}"
ACTION="${1:-}"

build() {
  local keep=(backend/pyproject.toml backend/uv.lock backend/.python-version backend/app backend/config
              backend/prompts backend/tests data/ontology data/schemas data/synthetic evaluation
              infrastructure/gcp/eval.Dockerfile infrastructure/gcp/eval_job_entry.sh)
  local p
  for p in "${keep[@]}"; do [[ -e "$ROOT/$p" ]] || { echo "missing $p" >&2; exit 1; }; done
  CTX="$(mktemp -d)"; trap 'rm -rf "$CTX"' EXIT
  for p in "${keep[@]}"; do mkdir -p "$CTX/$(dirname "$p")"; cp -R "$ROOT/$p" "$CTX/$p"; done
  # reports and caches stay on the laptop; only the baseline the comparison needs goes in
  rm -rf "$CTX/evaluation/reports" "$CTX/evaluation/.ragas_cache"; mkdir -p "$CTX/evaluation/reports"
  if [[ -f "$ROOT/evaluation/reports/$RAGAS_BASELINE" ]]; then
    cp "$ROOT/evaluation/reports/$RAGAS_BASELINE" "$CTX/evaluation/reports/"
  else
    echo "note: baseline $RAGAS_BASELINE not found; RAGAS runs without a comparison"
  fi
  find "$CTX" \( -name __pycache__ -o -name .DS_Store -o -name .pytest_cache -o -name .mypy_cache \) -prune -exec rm -rf {} +
  chmod -R u=rwX,go=rX "$CTX"; chmod a+x "$CTX/infrastructure/gcp/eval_job_entry.sh"
  echo "build context: $(find "$CTX" -type f | wc -l | tr -d ' ') files, $(du -sh "$CTX" | cut -f1)  ->  $IMAGE:$TAG"
  run gcloud builds submit "$CTX" --project "$PROJECT_ID" --region "$BUILD_REGION" \
    --config "$HERE/cloudbuild.eval.yaml" --substitutions "_IMAGE=${IMAGE}:${TAG}"
  run gcloud artifacts docker tags add "${IMAGE}:${TAG}" "${IMAGE}:latest"
}

job() {
  local cpu=2 mem=4Gi
  [[ "$MODE" == "leakage" || "$MODE" == "all" ]] && { cpu=4; mem=16Gi; }
  # "|" separates the variables (gcloud's ^|^ form): USERS is itself comma-separated
  local env="^|^MODE=${MODE}|LABEL=${LABEL}|JOBS=${JOBS:-4}|USERS=${USERS:-}|RAGAS_BASELINE=${RAGAS_BASELINE}"
  env="${env}|C2_GCP_PROJECT_ID=${PROJECT_ID}|C2_GCP_REGION=${REGION}|C2_PDF_SCAN_CACHE_DIR=/mnt/pdf_scans"
  # the model bounds of the deployed c2-api (20_api_service.sh), so answers are judged as officers get them
  env="${env}|C2_LLM_MAX_OUTPUT_TOKENS=${LLM_MAX_OUTPUT_TOKENS:-8192}|C2_LLM_TIMEOUT_S=${LLM_TIMEOUT_S:-90}"
  [[ -n "${GEMINI_MODEL:-}" ]] && env="${env}|C2_GEMINI_MODEL=${GEMINI_MODEL}"
  env="${env}|JUDGE_MAX_TOKENS=${JUDGE_MAX_TOKENS:-8192}"
  # the RAGAS judge stays on the model of the 19 Nov baseline unless set: a new answering model
  # (GEMINI_MODEL) must be judged by the same judge, or the scores cannot be compared
  env="${env}|JUDGE_MODEL=${JUDGE_MODEL:-gemini-3.5-flash}"
  # the run is pinned to the image's digest, and the digest is written into run-config.json, so a
  # report always says exactly which code and settings produced it
  local ref="${IMAGE}:${TAG_RUN:-latest}"
  if [[ "$APPLY" == "1" ]]; then
    ref="$(gcloud artifacts docker images describe "$ref" --project "$PROJECT_ID" \
             --format 'value(image_summary.fully_qualified_digest)')"
  fi
  env="${env}|IMAGE_REF=${ref}"
  run gcloud run jobs deploy "$JOB" --project "$PROJECT_ID" --region "$REGION" --image "$ref" \
    --service-account "$(sa_email "${EVAL_SA:-ingest}")" \
    --add-volume "name=corpus,type=cloud-storage,bucket=${RAW},readonly=true,mount-options=only-dir=public-go" \
    --add-volume-mount "volume=corpus,mount-path=/mnt/corpus/staging" \
    --add-volume "name=scans,type=cloud-storage,bucket=${ART},readonly=true,mount-options=only-dir=graph/pdf_scans" \
    --add-volume-mount "volume=scans,mount-path=/mnt/pdf_scans" \
    --add-volume "name=out,type=cloud-storage,bucket=${ART}" \
    --add-volume-mount "volume=out,mount-path=/mnt/out" \
    --set-env-vars "$env" \
    --cpu "$cpu" --memory "$mem" --task-timeout 21600 --max-retries 0 --tasks 1
}

case "$ACTION" in
  build) build ;;
  run)
    job
    if ! run gcloud run jobs execute "$JOB" --project "$PROJECT_ID" --region "$REGION" --wait; then
      echo "--- the job's own last lines (mount chatter left out) ---"
      gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$JOB\" AND NOT textPayload:\"GCSFuse\"" \
        --project "$PROJECT_ID" --freshness=6h --limit 60 --order desc --format='value(textPayload)' 2>/dev/null | tail -r 2>/dev/null || true
      echo "partial reports (if any): gs://${ART}/eval-reports/"
      exit 1
    fi
    echo "done. Copy the reports with: $0 fetch"
    ;;
  fetch)
    # each run keeps its own folder under evaluation/reports/cloud/; files already there are never
    # overwritten (a second fetch of the same day adds only the new runs)
    run gcloud storage ls "gs://${ART}/eval-reports/"
    DAY="${DAY:-$(date -u +%Y-%m-%d)}"
    mkdir -p "$ROOT/evaluation/reports/cloud"
    run gcloud storage cp --recursive --no-clobber "gs://${ART}/eval-reports/${DAY}-*" "$ROOT/evaluation/reports/cloud/"
    echo "runs fetched into evaluation/reports/cloud/ (one folder per run, with its run-config.json)"
    ;;
  *) echo "usage: [APPLY=1] [MODE=leakage|ragas|conversation|all] $0 build|run|fetch" >&2; exit 2 ;;
esac
