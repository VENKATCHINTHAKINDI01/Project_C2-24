#!/usr/bin/env bash
# Alert when a Cloud SQL automated backup fails (ADR-0057). Dry run by default; APPLY=1 executes.
#   - Cloud SQL writes a System Event audit log entry (always on, no charge) for every automated
#     backup window: protoPayload.methodName="cloudsql.instances.automatedBackup", with
#     protoPayload.metadata.windowStatus = STATUS_SUCCEEDED | STATUS_ATTEMPT_FAILED | STATUS_FAILED |
#     STATUS_SKIPPED (docs: "View audit logs for automated backups").
#   - this script makes a log-based metric counting ATTEMPT_FAILED / FAILED entries for this
#     project's instance and an alert policy on it (any occurrence). A backup that silently never
#     runs is caught by 31_restore_drill.py CHECK_ONLY=1 (latest successful backup older than 26 h),
#     which is on the operations checklist (infrastructure/gcp/OPERATIONS.md).
#   - NOTIFY_EMAIL=you@example.gov.in adds an e-mail notification channel to the policy; without it
#     the incident still shows in the console (Monitoring → Alerting).
#   - developer (roles/editor) is enough. Billing: within the free allotment.
source "$(dirname "$0")/lib.sh"
METRIC="${PREFIX}_sql_backup_failed"
NAME="C2-24: Cloud SQL automated backup failed"
FILTER="logName=\"projects/${PROJECT_ID}/logs/cloudaudit.googleapis.com%2Fsystem_event\" AND protoPayload.methodName=\"cloudsql.instances.automatedBackup\" AND resource.type=\"cloudsql_database\" AND resource.labels.database_id=\"${PROJECT_ID}:${PREFIX}-sql\" AND (protoPayload.metadata.windowStatus=\"STATUS_FAILED\" OR protoPayload.metadata.windowStatus=\"STATUS_ATTEMPT_FAILED\")"
CHANNEL=""
if [[ -n "${NOTIFY_EMAIL:-}" ]]; then
  if [[ "$APPLY" == "1" ]]; then
    CHANNEL="$(gcloud beta monitoring channels list --project "$PROJECT_ID" \
      --filter "type=\"email\" AND labels.email_address=\"${NOTIFY_EMAIL}\"" --format 'value(name)' | head -1)"
    if [[ -z "$CHANNEL" ]]; then
      echo "+ create e-mail channel for ${NOTIFY_EMAIL}"
      CHANNEL="$(gcloud beta monitoring channels create --project "$PROJECT_ID" \
        --display-name "C2-24 backups (${NOTIFY_EMAIL})" --type email \
        --channel-labels "email_address=${NOTIFY_EMAIL}" --format 'value(name)')"
    else
      echo "= e-mail channel exists"
    fi
  else
    echo "[dry-run] e-mail notification channel for ${NOTIFY_EMAIL}"
  fi
fi
POLICY="$(mktemp)"; trap 'rm -f "$POLICY"' EXIT
cat > "$POLICY" <<JSON
{
  "displayName": "${NAME}",
  "documentation": {"content": "An automated backup of ${PREFIX}-sql failed (windowStatus STATUS_FAILED or STATUS_ATTEMPT_FAILED). Check the audit log entry for the reason (another operation running, organisation location policy, instance stopped), then take an on-demand backup in asia-south1 and confirm it with 31_restore_drill.py CHECK_ONLY=1 (ADR-0057).", "mimeType": "text/markdown"},
  "combiner": "OR",
  "notificationChannels": [$( [[ -n "$CHANNEL" ]] && echo "\"$CHANNEL\"" )],
  "conditions": [{
    "displayName": "automated backup failed",
    "conditionThreshold": {
      "filter": "metric.type=\"logging.googleapis.com/user/${METRIC}\" AND resource.type=\"cloudsql_database\"",
      "comparison": "COMPARISON_GT", "thresholdValue": 0, "duration": "0s",
      "aggregations": [{"alignmentPeriod": "300s", "perSeriesAligner": "ALIGN_COUNT"}]
    }
  }]
}
JSON
if [[ "$APPLY" == "1" ]] && gcloud logging metrics describe "$METRIC" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "= metric $METRIC exists"
else
  run gcloud logging metrics create "$METRIC" --project "$PROJECT_ID" \
    --description "C2-24 Cloud SQL automated backup failed (ADR-0057)" --log-filter "$FILTER"
fi
if [[ "$APPLY" == "1" ]] && gcloud alpha monitoring policies list --project "$PROJECT_ID" \
    --filter "displayName=\"${NAME}\"" --format 'value(name)' 2>/dev/null | grep -q .; then
  echo "= alert policy exists"
else
  run gcloud alpha monitoring policies create --project "$PROJECT_ID" --policy-from-file "$POLICY"
fi
