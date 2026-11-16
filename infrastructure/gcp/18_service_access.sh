#!/usr/bin/env bash
# What c2-ingest (graph build job) and c2-api (sandbox API service) still need, narrowest level first.
# Dry run by default; APPLY=1 executes. Prints the roles each account holds before changing anything.
# Found 14-15 Nov 2026: c2-ingest could not create BigQuery load jobs (bigquery.jobs.create), so the
# documents table was loaded with the developer's login.
#   bucket / dataset level (the developer can usually grant these):
#     - c2-api:    raw bucket objectViewer (the service mounts the public corpus and the synthetic set)
#     - c2-ingest: c2_metadata dataset dataEditor (replace the documents / passages tables)
#     - c2-api:    c2_metadata dataset dataViewer (read L0-L2)
#   project level (no narrower scope exists; needs Project IAM Admin — if refused, the project owner runs
#   the lines marked OWNER):
#     - c2-ingest, c2-api: bigquery.jobUser (run queries / load jobs), aiplatform.user (embeddings, Gemini)
#     - c2-api: cloudsql.client + cloudsql.instanceUser (graph reads; c2-ingest already has them)
# Safe to run again.
source "$(dirname "$0")/lib.sh"
for who in ingest api; do
  echo "c2-${who} holds:"
  gcloud projects get-iam-policy "$PROJECT_ID" --flatten="bindings[].members" \
    --filter="bindings.members:serviceAccount:$(sa_email "$who")" --format="value(bindings.role)" \
    2>/dev/null | sed 's/^/  /' || echo "  (could not read the project policy)"
done
DS="${PROJECT_ID}:${PREFIX}_metadata"
run gcloud storage buckets add-iam-policy-binding "gs://${PROJECT_ID}-${PREFIX}-raw" \
  --member "serviceAccount:$(sa_email api)" --role roles/storage.objectViewer
# dataset access list (bq add-iam-policy-binding on a dataset needs allowlisting here; see lib.sh)
bq_dataset_grant "$DS" WRITER "$(sa_email ingest)"
bq_dataset_grant "$DS" READER "$(sa_email api)"
echo "--- OWNER (project level) ---"
for who in ingest api; do
  for role in roles/bigquery.jobUser roles/aiplatform.user; do
    run gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$(sa_email "$who")" \
      --role "$role" --condition None
  done
done
for role in roles/cloudsql.client roles/cloudsql.instanceUser; do
  run gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$(sa_email api)" \
    --role "$role" --condition None
done
