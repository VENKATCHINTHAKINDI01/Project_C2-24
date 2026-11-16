#!/usr/bin/env bash
# Adds the question columns to c2_audit.query_log for the monitoring pad (plan §10.4 raw_query;
# ADR-0035): `question` (the officer's words, never document text) and `clearance_rank` (the asker's
# clearance, so the pad shows the words only to a monitoring officer cleared as high) and `flags`
# (unusual-activity signal codes for the pad's alerts, ADR-0036; REPEATED STRING). Additive:
# new NULLABLE / REPEATED columns, existing rows keep NULL / empty. Dry run by default; APPLY=1
# executes. Safe to re-run.
source "$(dirname "$0")/lib.sh"
SCHEMA="$HERE/../../data/schemas/bigquery/query_log.json"
run bq update --schema "$SCHEMA" "${PROJECT_ID}:${PREFIX}_audit.query_log"
