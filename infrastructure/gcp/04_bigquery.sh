#!/usr/bin/env bash
# Datasets only; table schemas land with the P0 data-model task (data/schemas/).
source "$(dirname "$0")/lib.sh"
for ds in metadata audit; do
  run bq --location "$REGION" mk --dataset --description "C2-24 ${ds}" "${PROJECT_ID}:${PREFIX}_${ds}"
done
echo "Then grant $(sa_email api) roles/bigquery.dataEditor on ${PREFIX}_audit only (console: dataset > Share)."
