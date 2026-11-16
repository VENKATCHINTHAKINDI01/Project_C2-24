#!/usr/bin/env bash
# Access the graph build job (14) needs, at the narrowest level. Dry run by default; APPLY=1 executes.
# Found 14 Nov 2026: the job could not mount the raw bucket ("c2-ingest … does not have storage.objects.list"),
# i.e. the project-level roles of 02_service_accounts.sh were never granted to c2-ingest.
#   - raw bucket:        objectViewer (read + list only; the job mounts it read-only)
#   - artifacts bucket:  objectUser   (read, list, create, overwrite; no bucket administration)
#   - Cloud SQL:         cloudsql.client + cloudsql.instanceUser (project level: these roles have no narrower
#                        scope). Needs Project IAM Admin; if refused, ask the project owner to run these two lines.
# Safe to run again (bindings are added only if missing).
source "$(dirname "$0")/lib.sh"
SA="serviceAccount:$(sa_email ingest)"
echo "roles c2-ingest holds on the project now:"
gcloud projects get-iam-policy "$PROJECT_ID" --flatten="bindings[].members" \
  --filter="bindings.members:$SA" --format="value(bindings.role)" 2>/dev/null | sed 's/^/  /' || echo "  (could not read the project policy)"
run gcloud storage buckets add-iam-policy-binding "gs://${PROJECT_ID}-${PREFIX}-raw" \
  --member "$SA" --role roles/storage.objectViewer
run gcloud storage buckets add-iam-policy-binding "gs://${PROJECT_ID}-${PREFIX}-artifacts" \
  --member "$SA" --role roles/storage.objectUser
for role in roles/cloudsql.client roles/cloudsql.instanceUser; do
  run gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "$SA" --role "$role" --condition None
done
