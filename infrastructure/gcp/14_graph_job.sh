#!/usr/bin/env bash
# Knowledge graph of the public corpus, built on GCP (ADR-0023): a Cloud Run Job runs the normal ingestion
# pipeline over gs://<project>-<prefix>-raw/public-go and loads the result into Cloud SQL (graph, L3) and
# BigQuery <prefix>_metadata.documents (document metadata, ladder rungs L0/L1).
# Dry run by default.  APPLY=1 creates/updates the job.  APPLY=1 RUN=1 also runs it and waits.
# Before the first run: 12_cloudsql_schema.py (tables + grants) and 13_backend_image.sh (image).
#   - runs as c2-ingest (no keys); Cloud SQL through the connector with IAM login (no password)
#   - raw bucket mounted READ-ONLY; files go to gs://<project>-<prefix>-artifacts/graph/
#   - no Document AI and no Gemini calls: scans replay the readings already in public-go/ocr_recorded/
#   - LOAD=0 builds the files only
#   - safe to run again: rows are upserted, files overwritten.  LIMIT=50 for a short trial run.
# Billing: one task, 2 vCPU / 8 GiB, about 15-20 minutes for 1,374 orders; nothing bills while idle.
# With EMBEDDING_MODEL: + one embedding request per passage batch (Vertex, in region; cents for the
# whole corpus) and longer — quota answers are waited out and retried.
source "$(dirname "$0")/lib.sh"
JOB="${PREFIX}-graph-build"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${PREFIX}/backend:${TAG:-latest}"
RAW="${PROJECT_ID}-${PREFIX}-raw"
ART="${PROJECT_ID}-${PREFIX}-artifacts"
ARGS="-m,app.graph.build,--staging-dir,/mnt/raw/public-go,--out,/mnt/artifacts/graph,--pdf-scans,/mnt/artifacts/graph/pdf_scans"
# pdf_scans/: each public order's page reads, read by c2-api at start instead of parsing the PDFs
# LOAD=0: build the files only (use while c2-ingest lacks the Cloud SQL roles; then 16_graph_load.py)
[[ "${LOAD:-1}" == "1" ]] && ARGS="${ARGS},--load-postgres,--load-bigquery,${PROJECT_ID}.${PREFIX}_metadata.documents"
# Passages + embeddings for rung L2 (ADR-0026). EMBEDDING_MODEL must be one that answers in $REGION
# (17_embedding_check.py); without it the passages step is left out.
EMBED_ENV=""
if [[ "${LOAD:-1}" == "1" && -n "${EMBEDDING_MODEL:-}" ]]; then
  # part files under graph/passages/: a run that stops keeps its finished parts; running again
  # embeds only the rest (nothing is billed twice for an unchanged order)
  ARGS="${ARGS},--load-passages,${PROJECT_ID}.${PREFIX}_metadata.passages,gs://${ART}/graph"
  EMBED_ENV=",C2_EMBEDDING_MODEL=${EMBEDDING_MODEL},C2_EMBEDDING_DIMENSIONS=${EMBEDDING_DIMENSIONS:-768}"
else
  echo "note: EMBEDDING_MODEL not set — the passages table (rung L2) is not built in this run"
fi
[[ -n "${LIMIT:-}" ]] && ARGS="${ARGS},--limit,${LIMIT}"
run gcloud run jobs deploy "$JOB" --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE" \
  --service-account "$(sa_email ingest)" \
  --add-volume "name=raw,type=cloud-storage,bucket=${RAW},readonly=true" \
  --add-volume-mount "volume=raw,mount-path=/mnt/raw" \
  --add-volume "name=artifacts,type=cloud-storage,bucket=${ART}" \
  --add-volume-mount "volume=artifacts,mount-path=/mnt/artifacts" \
  --set-env-vars "C2_GCP_PROJECT_ID=${PROJECT_ID},C2_GCP_REGION=${REGION},C2_CLOUDSQL_INSTANCE=${PROJECT_ID}:${REGION}:${PREFIX}-sql,C2_CLOUDSQL_USER=${PREFIX}-ingest@${PROJECT_ID}.iam,C2_CLOUDSQL_DB=${PREFIX}${EMBED_ENV}" \
  --command /srv/backend/.venv/bin/python "--args=$ARGS" \
  --cpu 2 --memory 8Gi --task-timeout 7200 --max-retries 0 --tasks 1
if [[ "${RUN:-0}" == "1" ]]; then
  if ! run gcloud run jobs execute "$JOB" --project "$PROJECT_ID" --region "$REGION" --wait; then
    echo "--- the job's own last lines (mount chatter left out) ---"
    gcloud logging read "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"$JOB\" AND NOT textPayload:\"GCSFuse\" AND NOT textPayload:\"severity=INFO\"" \
      --project "$PROJECT_ID" --freshness=20m --limit 40 --order desc --format='value(textPayload)' | tail -r 2>/dev/null || true
    exit 1
  fi
  run gcloud storage cat "gs://${ART}/graph/report.md"
else
  echo "job defined. Run it with: APPLY=1 RUN=1 $0"
fi
