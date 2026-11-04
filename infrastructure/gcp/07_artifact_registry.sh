#!/usr/bin/env bash
# Docker repo for the backend/frontend images deployed to Cloud Run.
source "$(dirname "$0")/lib.sh"
run gcloud artifacts repositories create "${PREFIX}" --project "$PROJECT_ID" \
  --repository-format docker --location "$REGION" --description "C2-24 images"
