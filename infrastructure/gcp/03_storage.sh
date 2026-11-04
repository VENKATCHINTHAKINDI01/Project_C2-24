#!/usr/bin/env bash
# Raw documents + artifacts. Private, uniform access, versioned (superseded docs are never deleted, CLAUDE.md §5.8).
source "$(dirname "$0")/lib.sh"
for b in raw artifacts; do
  run gcloud storage buckets create "gs://${PROJECT_ID}-${PREFIX}-${b}" --project "$PROJECT_ID" \
    --location "$REGION" --uniform-bucket-level-access --public-access-prevention
  run gcloud storage buckets update "gs://${PROJECT_ID}-${PREFIX}-${b}" --versioning
done
