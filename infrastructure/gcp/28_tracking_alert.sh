#!/usr/bin/env bash
# Alert when the tracking buffer fills (plan §14.4; ADR-0049). Dry run by default; APPLY=1 executes.
#   - c2-api keeps query-log and feedback rows it could not write to BigQuery, and retries them. If the
#     buffer fills, it drops the oldest and logs one fixed CRITICAL line: C2_TRACKING_BUFFER_FULL
#   - this script makes a log-based metric counting that line, and an alert policy on it (any
#     occurrence in 5 minutes). Add a notification channel in the console (Monitoring → Alerting →
#     the policy → Edit) to be told by e-mail; without one the incident still shows in the console.
#   - developer (roles/editor) is enough. Billing: log-based metrics and alert policies of this size
#     are within the free allotment.
source "$(dirname "$0")/lib.sh"
METRIC="${PREFIX}_tracking_buffer_full"
FILTER='resource.type="cloud_run_revision" AND textPayload:"C2_TRACKING_BUFFER_FULL"'
POLICY="$(mktemp)"; trap 'rm -f "$POLICY"' EXIT
cat > "$POLICY" <<JSON
{
  "displayName": "C2-24: tracking rows dropped (buffer full)",
  "documentation": {"content": "c2-api could not write query-log / feedback rows to BigQuery for long enough that its retry buffer filled and the oldest rows were dropped. Check BigQuery access and quota for ${PREFIX}_audit (plan §14.4, ADR-0049).", "mimeType": "text/markdown"},
  "combiner": "OR",
  "conditions": [{
    "displayName": "C2_TRACKING_BUFFER_FULL logged",
    "conditionThreshold": {
      "filter": "metric.type=\"logging.googleapis.com/user/${METRIC}\" AND resource.type=\"cloud_run_revision\"",
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
    --description "C2-24 tracking rows dropped: retry buffer full (ADR-0049)" --log-filter "$FILTER"
fi
if [[ "$APPLY" == "1" ]] && gcloud alpha monitoring policies list --project "$PROJECT_ID" \
    --filter 'displayName="C2-24: tracking rows dropped (buffer full)"' --format 'value(name)' 2>/dev/null | grep -q .; then
  echo "= alert policy exists"
else
  run gcloud alpha monitoring policies create --project "$PROJECT_ID" --policy-from-file "$POLICY"
fi
