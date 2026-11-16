#!/usr/bin/env bash
# Query log table for plan §10.4 (ADR-0029): <project>:<prefix>_audit.query_log, one row per question,
# IDs and metadata only (schema: data/schemas/bigquery/query_log.json). Dry run by default; APPLY=1 executes.
# Partitioned by day on ts, so analytics read only the days they need. c2-api gets write on this dataset
# only (streaming insert needs no BigQuery job). Turn it on in the service with C2_QUERY_LOG=bigquery.
source "$(dirname "$0")/lib.sh"
SCHEMA="$HERE/../../data/schemas/bigquery/query_log.json"
TABLE="${PROJECT_ID}:${PREFIX}_audit.query_log"
# SKIP_TABLE=1 when the table already exists (bq mk fails with "already exists")
[[ "${SKIP_TABLE:-0}" == "1" ]] || run bq mk --table --time_partitioning_field ts --time_partitioning_type DAY \
  --description "C2-24 query log: IDs and metadata only, no question or answer text" "$TABLE" "$SCHEMA"
# WRITER on the dataset = BigQuery Data Editor on this dataset only (dataset access list; see lib.sh)
bq_dataset_grant "${PROJECT_ID}:${PREFIX}_audit" WRITER "$(sa_email api)"
