#!/usr/bin/env bash
# Spanner Graph (L3). Graph needs Enterprise edition; smallest size is 100 processing units.
source "$(dirname "$0")/lib.sh"
require_cost_ack "Spanner"
run gcloud spanner instances create "${PREFIX}-spanner" --project "$PROJECT_ID" \
  --config "regional-${REGION}" --edition ENTERPRISE --processing-units 100 \
  --description "C2-24 graph"
run gcloud spanner databases create "${PREFIX}graph" --instance "${PREFIX}-spanner" --project "$PROJECT_ID"
