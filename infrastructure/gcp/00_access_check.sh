#!/usr/bin/env bash
# Read-only access check, run first on access day. Changes nothing in GCP.
# Writes everything to access_check.out.txt (git-ignored) so it can be reviewed before any APPLY step.
# Commands that fail (missing permission) are recorded and the check carries on.
source "$(dirname "$0")/lib.sh"
export CLOUDSDK_CORE_DISABLE_PROMPTS=1  # never stop at a y/N prompt (e.g. "enable orgpolicy API?"): record and carry on
command -v gcloud >/dev/null || { echo "gcloud not installed: brew install --cask google-cloud-sdk" >&2; exit 1; }
OUT="$HERE/access_check.out.txt"
ACCOUNT="$(gcloud config get-value account 2>/dev/null)"
step() { echo; echo "### $*"; "$@" 2>&1 || echo "(failed: exit $?)"; }
{
  echo "C2-24 access check · $(date '+%Y-%m-%d %H:%M %Z') · project=$PROJECT_ID region=$REGION"
  step gcloud --version
  step gcloud auth list
  step gcloud config list
  step gcloud projects describe "$PROJECT_ID" --format "yaml(projectId,projectNumber,lifecycleState,parent)"
  step gcloud billing projects describe "$PROJECT_ID"
  echo; echo "### my roles on the project ($ACCOUNT)"
  gcloud projects get-iam-policy "$PROJECT_ID" --flatten "bindings[].members" \
    --filter "bindings.members:$ACCOUNT" --format "value(bindings.role)" 2>&1 || echo "(failed)"
  step gcloud services list --enabled --project "$PROJECT_ID" --format "value(config.name)"
  step gcloud org-policies list --project "$PROJECT_ID" --format "value(constraint)"
  for c in gcp.resourceLocations iam.disableServiceAccountKeyCreation iam.allowedPolicyMemberDomains run.allowedIngress; do
    step gcloud org-policies describe "$c" --project "$PROJECT_ID" --effective --format yaml
  done
  step gcloud storage buckets list --project "$PROJECT_ID" --format "value(name,location)"
  step bq ls --project_id "$PROJECT_ID"
} > "$OUT"
echo "Done. Output: $OUT"
