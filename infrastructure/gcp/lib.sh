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
# Cloud Run access settings (who may call a service: --allow/--no-allow-unauthenticated, --iap,
# --ingress, IAM/IAP bindings) are owned by the TechBharat admins once a service exists (their email,
# 24 Nov 2026: changes must be reviewed and coordinated first). Scripts set them only when creating a
# service; a redeploy leaves them as they are. True when the service exists; dry run assumes it does.
# Fails closed: when existence cannot be told (e.g. no permission), stop rather than guess.
service_exists() {
  [[ "$APPLY" != "1" ]] && return 0
  local out
  if out="$(gcloud run services describe "$1" --project "$PROJECT_ID" --region "$REGION" \
              --format 'value(metadata.name)' 2>&1)"; then return 0; fi
  if grep -qi "could not be found\|not found" <<<"$out"; then return 1; fi
  echo "Cannot tell whether $1 exists, so nothing was deployed: $out" >&2; exit 1
}
# Access changes on an existing service run only with SECURITY_CHANGE=approved, after the change was
# agreed with the TechBharat admins. Without it the command is printed, not run.
security_change() {
  if [[ "$APPLY" == "1" && "${SECURITY_CHANGE:-}" != "approved" ]]; then
    echo "[not run: access change, needs SECURITY_CHANGE=approved after admin review] $*"; return 0
  fi
  run "$@"
}
# Dataset-level access in BigQuery through the dataset's own access list (bq add-iam-policy-binding on a
# dataset "requires allowlisting" in this project, found 15 Nov 2026). role: READER | WRITER | OWNER.
# Adds the entry only if it is missing; never removes anything.
bq_dataset_grant() {
  local ds="$1" role="$2" email="$3"
  if [[ "$APPLY" != "1" ]]; then echo "[dry-run] add $role $email to the access list of $ds"; return 0; fi
  local tmp; tmp="$(mktemp)"
  bq show --format=prettyjson "$ds" > "$tmp"
  if python3 - "$tmp" "$role" "$email" <<'PY'
import json, sys
path, role, email = sys.argv[1:]
d = json.load(open(path))
acc = d.setdefault("access", [])
if any(a.get("role") == role and a.get("userByEmail") == email for a in acc):
    sys.exit(1)  # already there
acc.append({"role": role, "userByEmail": email})
json.dump(d, open(path, "w"))
PY
  then echo "+ bq update (add $role $email) $ds"; bq update --source "$tmp" "$ds"
  else echo "= $email already $role on $ds"; fi
  rm -f "$tmp"
}
