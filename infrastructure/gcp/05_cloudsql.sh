#!/usr/bin/env bash
# Cloud SQL Postgres: app data, authz tuples, review decisions, audit, LangGraph checkpointer.
# IAM DB auth only: no DB passwords; apps connect through the Cloud SQL connector (no open IP ranges).
# PoC size (owner OK 11 Nov 2026): shared-core db-g1-small (~US$31/month in asia-south1 + storage),
# no SLA on shared core, which is fine for a PoC. Override with TIER=db-custom-1-3840 if it is too small.
source "$(dirname "$0")/lib.sh"
require_cost_ack "Cloud SQL"
INSTANCE="${PREFIX}-sql"
TIER="${TIER:-db-g1-small}"
ME="$(gcloud config get-value account 2>/dev/null)"
run gcloud sql instances create "$INSTANCE" --project "$PROJECT_ID" --region "$REGION" \
  --database-version POSTGRES_16 --edition ENTERPRISE --tier "$TIER" \
  --storage-size 10 --storage-auto-increase --backup --deletion-protection \
  --database-flags cloudsql.iam_authentication=on
run gcloud sql databases create "${PREFIX}" --instance "$INSTANCE" --project "$PROJECT_ID"
for sa in api ingest; do
  run gcloud sql users create "${PREFIX}-${sa}@${PROJECT_ID}.iam" --instance "$INSTANCE" \
    --type cloud_iam_service_account --project "$PROJECT_ID"
done
# The developer's own login, for schema work and local runs (IAM user; still no password).
run gcloud sql users create "$ME" --instance "$INSTANCE" --type cloud_iam_user --project "$PROJECT_ID"
