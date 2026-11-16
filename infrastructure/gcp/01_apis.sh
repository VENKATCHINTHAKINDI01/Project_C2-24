#!/usr/bin/env bash
# Enable only the PoC services (CLAUDE.md §2.2). No Tier-3 APIs (Pub/Sub, Dataflow, Apigee, ...).
# orgpolicy: read-only use, so 00_access_check.sh can show the allowed-locations rule.
source "$(dirname "$0")/lib.sh"
run gcloud services enable \
  run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com \
  storage.googleapis.com documentai.googleapis.com aiplatform.googleapis.com \
  discoveryengine.googleapis.com bigquery.googleapis.com spanner.googleapis.com \
  sqladmin.googleapis.com redis.googleapis.com secretmanager.googleapis.com \
  cloudkms.googleapis.com iap.googleapis.com iam.googleapis.com iamcredentials.googleapis.com \
  orgpolicy.googleapis.com \
  --project "$PROJECT_ID"
