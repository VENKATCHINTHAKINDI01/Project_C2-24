#!/usr/bin/env bash
# Cloud SQL Postgres: app data, authz tuples, LangGraph checkpointer. IAM DB auth — no DB passwords.
source "$(dirname "$0")/lib.sh"
require_cost_ack "Cloud SQL"
INSTANCE="${PREFIX}-sql"
run gcloud sql instances create "$INSTANCE" --project "$PROJECT_ID" --region "$REGION" \
  --database-version POSTGRES_16 --edition ENTERPRISE --tier db-custom-1-3840 \
  --storage-size 10 --backup --database-flags cloudsql.iam_authentication=on
run gcloud sql databases create "${PREFIX}" --instance "$INSTANCE" --project "$PROJECT_ID"
for sa in api ingest; do
  run gcloud sql users create "${PREFIX}-${sa}@${PROJECT_ID}.iam" --instance "$INSTANCE" \
    --type cloud_iam_service_account --project "$PROJECT_ID"
done
