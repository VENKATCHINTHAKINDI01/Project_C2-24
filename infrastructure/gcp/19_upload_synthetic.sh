#!/usr/bin/env bash
# Copy the SYNTHETIC sandbox data the API reads to gs://<project>-<prefix>-raw/synthetic/mock_v1/ (ADR-0028).
# Dry run by default; APPLY=1 executes. Never deletes in the bucket.
# Allowlist, not the whole folder: the answer keys stay on the laptop. The application never reads them
# (CLAUDE.md §9.2) and a service that mounts the bucket must not be able to either. Left out: ground_truth/,
# access_matrix.csv, users.csv, manifest.json, efiles_v2/{ground_truth,scenarios,manifests,efiles,directory}.
source "$(dirname "$0")/lib.sh"
SRC="$HERE/../../data/synthetic/mock_v1"
DEST="gs://${PROJECT_ID}-${PREFIX}-raw/synthetic/mock_v1"
for part in documents ocr llm eoffice efiles_v2/eoffice; do
  [[ -d "$SRC/$part" ]] || { echo "missing $SRC/$part" >&2; exit 1; }
  run gcloud storage rsync "$SRC/$part" "$DEST/$part" --recursive --exclude='.*\.DS_Store$|.*/__pycache__/.*'
done
run gcloud storage cp "$SRC/documents_index.csv" "$SRC/README.md" "$DEST/"
