#!/usr/bin/env bash
# Copy the public G.O. corpus (ADR-0006) to the private raw bucket under public-go/. Dry run by default; APPLY=1 executes.
# Source: $C2_DC_DATA_ROOT/staging (data_collection/local.env). Not uploaded: _review/ (unverified) and holdback/
# (the demo order that must arrive live). rsync without --delete-unmatched-destination-objects: never deletes in GCS.
source "$(dirname "$0")/lib.sh"
ENV_FILE="$HERE/../../data_collection/local.env"
if [[ -z "${C2_DC_DATA_ROOT:-}" && -f "$ENV_FILE" ]]; then
  C2_DC_DATA_ROOT="$(grep -E '^C2_DC_DATA_ROOT=' "$ENV_FILE" | head -1 | cut -d= -f2- | sed -e 's/^["]//' -e 's/["]$//')"
fi
case "${C2_DC_DATA_ROOT:-}" in "~/"*) C2_DC_DATA_ROOT="$HOME/${C2_DC_DATA_ROOT#\~/}";; esac
SRC="${C2_DC_DATA_ROOT:-}/staging"
[[ -d "$SRC" ]] || { echo "No corpus at '$SRC' — set C2_DC_DATA_ROOT in data_collection/local.env" >&2; exit 1; }
DEST="gs://${PROJECT_ID}-${PREFIX}-raw/public-go"
echo "corpus: $SRC  ($(find "$SRC/rule-library" -name meta.json 2>/dev/null | wc -l | tr -d ' ') documents)  ->  $DEST"
run gcloud storage rsync "$SRC" "$DEST" --recursive --exclude='^_review/.*|^holdback/.*|.*/__pycache__/.*|.*\.DS_Store$'
