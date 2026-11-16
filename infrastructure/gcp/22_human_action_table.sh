#!/usr/bin/env bash
# Feedback table for plan §9.2 / §10.4 (ADR-0031): <project>:<prefix>_audit.human_action, one row per
# officer action on an assistant output (thumbs, flag accepted/dismissed, Yellow Note confirmed /
# edited / discarded). IDs, fixed codes and an edit share only — no text. Append-only; the view
# query_log_actions gives each query its latest action (plan §10.4 field human_action).
# Dry run by default; APPLY=1 executes. c2-api already writes to this dataset (21_query_log_table.sh).
# The service writes here when C2_QUERY_LOG=bigquery (same switch as the query log).
source "$(dirname "$0")/lib.sh"
SCHEMA="$HERE/../../data/schemas/bigquery/human_action.json"
DS="${PROJECT_ID}:${PREFIX}_audit"
SQL_DS="\`${PROJECT_ID}.${PREFIX}_audit\`"
[[ "${SKIP_TABLE:-0}" == "1" ]] || run bq mk --table --time_partitioning_field ts --time_partitioning_type DAY \
  --description "C2-24 officer feedback: IDs, fixed codes and edit share only; no text" \
  "${DS}.human_action" "$SCHEMA"
VIEW_SQL="SELECT q.* EXCEPT (human_action), a.action AS human_action, a.reason AS human_reason,
  a.edit_share AS human_edit_share
FROM ${SQL_DS}.query_log AS q
LEFT JOIN (
  SELECT * EXCEPT (rn) FROM (
    SELECT query_id, action, reason, edit_share,
           ROW_NUMBER() OVER (PARTITION BY query_id ORDER BY ts DESC) AS rn
    FROM ${SQL_DS}.human_action)
  WHERE rn = 1) AS a
USING (query_id)"
run bq mk --use_legacy_sql=false --view "$VIEW_SQL" \
  --description "Query log with each query's latest officer action (plan 10.4 human_action)" \
  "${DS}.query_log_actions"
