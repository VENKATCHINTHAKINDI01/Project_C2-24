#!/usr/bin/env bash
# Read-only: shows what actually exists. Use this as evidence before marking setup done (CLAUDE.md §11.11).
source "$(dirname "$0")/lib.sh"
command -v gcloud >/dev/null || { echo "gcloud not installed" >&2; exit 1; }
set -x
gcloud services list --enabled --project "$PROJECT_ID" --format "value(config.name)"
gcloud iam service-accounts list --project "$PROJECT_ID" --format "value(email)"
gcloud storage buckets list --project "$PROJECT_ID" --format "value(name)"
bq ls --project_id "$PROJECT_ID"
gcloud sql instances list --project "$PROJECT_ID"
gcloud spanner instances list --project "$PROJECT_ID"
gcloud artifacts repositories list --project "$PROJECT_ID" --location "$REGION"
