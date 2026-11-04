#!/usr/bin/env bash
# Shared helpers. Dry run by default: commands are printed, not executed. APPLY=1 executes.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$HERE/config.env" ]] || { echo "Missing $HERE/config.env (copy config.env.example)" >&2; exit 1; }
# shellcheck source=/dev/null
source "$HERE/config.env"
: "${PROJECT_ID:?set PROJECT_ID in config.env}" "${REGION:?set REGION}" "${PREFIX:?set PREFIX}"
APPLY="${APPLY:-0}"
if [[ "$APPLY" == "1" ]]; then
  command -v gcloud >/dev/null || { echo "gcloud not installed" >&2; exit 1; }
  [[ "$(gcloud config get-value project 2>/dev/null)" == "$PROJECT_ID" ]] \
    || { echo "Active gcloud project != $PROJECT_ID; run: gcloud config set project $PROJECT_ID" >&2; exit 1; }
fi
run() { if [[ "$APPLY" == "1" ]]; then echo "+ $*"; "$@"; else echo "[dry-run] $*"; fi; }
require_cost_ack() {  # resources that bill while idle need an explicit second flag
  if [[ "$APPLY" == "1" && "${I_ACCEPT_COST:-0}" != "1" ]]; then
    echo "$1 bills while idle. Re-run with I_ACCEPT_COST=1 APPLY=1 after checking budget." >&2; exit 1
  fi
}
sa_email() { echo "${PREFIX}-$1@${PROJECT_ID}.iam.gserviceaccount.com"; }
