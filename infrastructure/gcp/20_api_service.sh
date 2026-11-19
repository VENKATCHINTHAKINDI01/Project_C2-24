#!/usr/bin/env bash
# The sandbox API on Cloud Run (plan §3.5, §11; ADR-0028). Dry run by default; APPLY=1 deploys.
# Before: 18_service_access.sh, 19_upload_synthetic.sh, 13_backend_image.sh, and a finished graph job (14).
#   - service c2-api, runs as c2-api (no keys); NOT public: only signed-in project members can call it.
#     Open it with:  gcloud run services proxy c2-api --region <region> --port 8080   → http://localhost:8080
#   - SANDBOX: mock e-Office, synthetic files; every response carries the sandbox banner header
#   - e-Office papers (synthetic) are ingested in memory while the instance starts (warm start);
#     the public orders are read from BigQuery (L0-L2) and Cloud SQL (L3): C2_RETRIEVAL_BACKEND=cloud
#   - one instance at most: review decisions made in the sandbox live in that instance's memory
#   - SEED=v2 (default; the 203-file set) or v1;  LLM=recorded (default; saved Gemini answers, no cost)
#     or vertex (live Gemini, billed; LLM_TIMEOUT_S=30, LLM_MAX_OUTPUT_TOKENS=4096, WORDING_PER_DAY=40,
#     MODEL_PER_MINUTE=20 per officer);  EMBEDDING_MODEL=<name> turns on the BigQuery L2 part
#   - needs (project level) bigquery.jobUser + aiplatform.user on c2-api; WRITER on <prefix>_audit
# Billing: CPU only while a request runs (instances scale to zero); first call after idle is slow.
source "$(dirname "$0")/lib.sh"
SERVICE="${PREFIX}-api"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${PREFIX}/backend:${TAG:-latest}"
RAW="${PROJECT_ID}-${PREFIX}-raw"
ART="${PROJECT_ID}-${PREFIX}-artifacts"
ENV="C2_SANDBOX=true,C2_SANDBOX_SEED=${SEED:-v2},C2_SANDBOX_PUBLIC_CORPUS_DIR=/mnt/corpus"
ENV="${ENV},C2_RETRIEVAL_BACKEND=cloud,C2_GCP_PROJECT_ID=${PROJECT_ID},C2_GCP_REGION=${REGION}"
ENV="${ENV},C2_CLOUDSQL_INSTANCE=${PROJECT_ID}:${REGION}:${PREFIX}-sql,C2_CLOUDSQL_USER=${PREFIX}-api@${PROJECT_ID}.iam"
ENV="${ENV},C2_CLOUDSQL_DB=${PREFIX},C2_LLM_PROVIDER=${LLM:-recorded}"
# live Gemini (ADR-0060): bounded per call (time, output tokens) and per officer per day for draft
# wording; a stuck or failing model ends closed (circuit breaker), never a guessed line
if [[ "${LLM:-recorded}" == "vertex" ]]; then
  ENV="${ENV},C2_LLM_TIMEOUT_S=${LLM_TIMEOUT_S:-30},C2_LLM_MAX_OUTPUT_TOKENS=${LLM_MAX_OUTPUT_TOKENS:-4096}"
  ENV="${ENV},C2_DRAFT_WORDING_PER_DAY=${WORDING_PER_DAY:-40},C2_RATE_MODEL_PER_MINUTE=${MODEL_PER_MINUTE:-20}"
fi
[[ -n "${EMBEDDING_MODEL:-}" ]] && ENV="${ENV},C2_EMBEDDING_MODEL=${EMBEDDING_MODEL},C2_EMBEDDING_DIMENSIONS=${EMBEDDING_DIMENSIONS:-768}"
# only an owner-approved value (cloud_ladder_check.py proposes one); unset = cloud L2 never ends the
# ladder on its own
[[ -n "${L2_MIN_SCORE:-}" ]] && ENV="${ENV},C2_L2_CLOUD_MIN_SCORE=${L2_MIN_SCORE}"
# query log + officers' feedback to <prefix>_audit (21, 22); QUERY_LOG=memory keeps them in the instance
ENV="${ENV},C2_QUERY_LOG=${QUERY_LOG:-bigquery}"
# start fast (ADR-0028 addendum 2): build the sandbox while the instance starts, from the page reads
# the graph job saved (14_graph_job.sh writes graph/pdf_scans/); without them PDFs are parsed as before
ENV="${ENV},C2_SANDBOX_WARM_START=true,C2_PDF_SCAN_CACHE_DIR=/mnt/pdf_scans"
# c2-api reads the saved page reads (public orders only) from the artifacts bucket, read-only
run gcloud storage buckets add-iam-policy-binding "gs://${ART}" \
  --member "serviceAccount:$(sa_email api)" --role roles/storage.objectViewer
# L3 graph store (ADR-0048): unset = Cloud SQL (default); GRAPH=spanner reads Spanner Graph
# (26_spanner_graph.sh, loaded by 27, compared by cloud_ladder_check.py --spanner-instance first)
if [[ "${GRAPH:-}" == "spanner" ]]; then
  ENV="${ENV},C2_GRAPH_BACKEND=spanner,C2_SPANNER_INSTANCE=${SPANNER_INSTANCE:-${PREFIX}-spanner}"
  ENV="${ENV},C2_SPANNER_DATABASE=${SPANNER_DATABASE:-${PREFIX}graph}"
fi
# monitoring officers besides the sandbox.yaml one (comma-separated sandbox IDs), optional
[[ -n "${MONITORING_USERS:-}" ]] && ENV="${ENV},C2_MONITORING_USERS=${MONITORING_USERS}"
# Memorystore (24_memorystore.sh): REDIS=1 adds the cache URL from Secret Manager and a private path
# to the VPC (Direct VPC egress, private ranges only); REDIS=0 takes them off again (in-memory
# cache); unset leaves the service as it is
EXTRA=()
if [[ "${REDIS:-}" == "1" ]]; then
  EXTRA=(--set-secrets "C2_REDIS_URL=${PREFIX}-redis-url:latest"
         --network "${NETWORK:-default}" --subnet "${SUBNET:-default}" --vpc-egress private-ranges-only)
elif [[ "${REDIS:-}" == "0" ]]; then
  EXTRA=(--remove-secrets C2_REDIS_URL --clear-network)
fi
run gcloud run deploy "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE" \
  --service-account "$(sa_email api)" --no-allow-unauthenticated \
  --add-volume "name=corpus,type=cloud-storage,bucket=${RAW},readonly=true,mount-options=only-dir=public-go" \
  --add-volume-mount "volume=corpus,mount-path=/mnt/corpus/staging" \
  --add-volume "name=synthetic,type=cloud-storage,bucket=${RAW},readonly=true,mount-options=only-dir=synthetic/mock_v1" \
  --add-volume-mount "volume=synthetic,mount-path=/srv/data/synthetic/mock_v1" \
  --add-volume "name=scans,type=cloud-storage,bucket=${ART},readonly=true,mount-options=only-dir=graph/pdf_scans" \
  --add-volume-mount "volume=scans,mount-path=/mnt/pdf_scans" \
  --set-env-vars "$ENV" \
  --cpu 2 --memory 4Gi --cpu-boost \
  --startup-probe "httpGet.path=/readyz,httpGet.port=8080,periodSeconds=10,timeoutSeconds=10,failureThreshold=60" --timeout 600 --min-instances 0 --max-instances 1 --port 8080 \
  ${EXTRA[@]+"${EXTRA[@]}"}
echo "check:  gcloud run services proxy ${SERVICE} --project ${PROJECT_ID} --region ${REGION} --port 8080"
echo "then:   curl -s -H 'X-Sandbox-User: <officer id>' -X POST localhost:8080/assist/search \\"
echo "          -H 'content-type: application/json' -d '{\"query\": \"transfer of teachers\"}'"
