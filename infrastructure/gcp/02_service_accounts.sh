#!/usr/bin/env bash
# One service account per workload. Project-level roles for the PoC; tighten to resource-level later.
# (bash 3.2-compatible: macOS default shell has no associative arrays.)
# SKIP_ROLES=1: create the accounts only; run again later without it (create then fails with
# 'already exists' — use ROLES_ONLY=1) once Project IAM Admin is available.
source "$(dirname "$0")/lib.sh"
roles_for() {
  case "$1" in
    api) echo "roles/aiplatform.user roles/discoveryengine.viewer roles/bigquery.jobUser roles/bigquery.dataViewer roles/spanner.databaseReader roles/cloudsql.client roles/cloudsql.instanceUser roles/secretmanager.secretAccessor roles/storage.objectViewer" ;;
    ingest) echo "roles/documentai.apiUser roles/aiplatform.user roles/discoveryengine.editor roles/bigquery.jobUser roles/bigquery.dataEditor roles/spanner.databaseUser roles/cloudsql.client roles/cloudsql.instanceUser roles/storage.objectAdmin" ;;
    frontend) echo "" ;;
  esac
}
for sa in api ingest frontend; do
  [[ "${ROLES_ONLY:-0}" == "1" ]] || run gcloud iam service-accounts create "${PREFIX}-${sa}" --display-name "C2-24 ${sa}" --project "$PROJECT_ID"
  [[ "${SKIP_ROLES:-0}" == "1" ]] && continue  # Editor can create SAs but not grant roles (needs Project IAM Admin)
  for role in $(roles_for "$sa"); do
    run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member "serviceAccount:$(sa_email "$sa")" --role "$role" --condition None
  done
done
# Audit writes: api gets dataEditor on the audit dataset only — see 04_bigquery.sh.
