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
# Only what the project uses (owner, 13 Nov 2026): per document order.pdf + ocr.txt + meta.json; manifests/relations.jsonl
# and provenance.jsonl; ocr_cache/ (Document AI layout = page/paragraph locations, so the cloud never pays twice).
# Never: _review/ (unverified), holdback/ (demo order), superseded text (ocr.archive.txt), working reports and lists
# (missing.txt, audit/validation reports, date_review.csv, failed.jsonl, gazette candidates, saved search pages),
# temp files, OS files. Logs live outside staging/ and are never uploaded.
# 13 Nov 2026: the first upload still sent the 8 _review/ meta.partial.json files; the patterns are now anchored
# anywhere in the path and meta.partial.json is excluded by name as well.
EXCLUDE='(^|.*/)_review/.*|(^|.*/)holdback/.*|.*meta\.partial\.json$|.*/__pycache__/.*|.*\.DS_Store$|.*\.tmp$|.*/ocr\.archive\.txt$|^manifests/(?!(relations|provenance)\.jsonl$).*'
python3 - "$SRC" "$EXCLUDE" <<'PY'
import os, re, sys
src, ex = sys.argv[1], re.compile(sys.argv[2])
keep, skip = {}, {}
for d, _, fs in os.walk(src):
    for f in fs:
        rel = os.path.relpath(os.path.join(d, f), src)
        kind = f if not re.fullmatch(r"[0-9a-f]{64}-p\d+\.json", f) else "<ocr cache>.json"
        (skip if ex.match(rel) else keep)[kind] = (skip if ex.match(rel) else keep).get(kind, 0) + 1
print("will upload:", ", ".join(f"{v} {k}" for k, v in sorted(keep.items(), key=lambda x: -x[1])))
print("left out:   ", ", ".join(f"{v} {k}" for k, v in sorted(skip.items(), key=lambda x: -x[1])))
PY
run gcloud storage rsync "$SRC" "$DEST" --recursive --exclude="$EXCLUDE"
