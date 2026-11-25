#!/usr/bin/env bash
# Entry point of the evaluation Cloud Run Job (ADR-0068). MODE=leakage | ragas | conversation | all.
# Reports are written as on a laptop (evaluation/reports/) and copied to the artifacts bucket,
# mounted at /mnt/out: eval-reports/<date>-<mode>[-label]/. The RAGAS judge cache lives in the bucket
# (eval-cache/ragas), so a re-run of the same samples costs nothing. Exit 1 if any suite failed.
set -uo pipefail
MODE="${MODE:-all}"; LABEL="${LABEL:-cloud}"
REPORTS=/srv/evaluation/reports
# one folder per run (date, time, mode, label): a re-run never replaces an earlier run's reports
OUT="/mnt/out/eval-reports/$(date -u +%Y-%m-%d-%H%M)-${MODE}-${LABEL}"
mkdir -p "$OUT" /mnt/out/eval-cache/ragas
[[ -L /srv/evaluation/.ragas_cache ]] || ln -sfn /mnt/out/eval-cache/ragas /srv/evaluation/.ragas_cache  # made in the image
before="$(mktemp)"; ls "$REPORTS" | sort > "$before"
cd /srv/backend
status=0
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
STEPS="$(mktemp)"  # one line per suite step: <exit code> <command>
step() {
  echo "=== $* ==="
  "$@"; local rc=$?
  echo "$rc $*" >> "$STEPS"
  [[ $rc -eq 0 ]] || { echo "FAILED: $*"; status=1; }
}

leakage() {
  local args=(--public-dir /mnt/corpus --jobs "${JOBS:-4}" --label "$LABEL")
  [[ -n "${USERS:-}" ]] && args+=(--users "$USERS")
  step python ../evaluation/leakage_v2.py "${args[@]}"
}
ragas() {
  step python ../evaluation/rag_samples.py --live --label "$LABEL"
  local s; s="$(ls -t "$REPORTS"/*-rag-samples-"$LABEL".jsonl 2>/dev/null | head -1)"
  if [[ -z "$s" ]]; then echo "FAILED: no samples file"; status=1; return; fi
  local cmp=()
  [[ -n "${RAGAS_BASELINE:-}" && -f "$REPORTS/$RAGAS_BASELINE" ]] && cmp=(--compare "$REPORTS/$RAGAS_BASELINE")
  step /srv/ragas/bin/python ../evaluation/ragas_score.py "$s" --live --label "$LABEL" \
    --judge-max-tokens "${JUDGE_MAX_TOKENS:-8192}" --judge-model "${JUDGE_MODEL:-gemini-3.5-flash}" "${cmp[@]}"
}
conversation() { step python ../evaluation/conversation_check.py --live --label "$LABEL"; }

case "$MODE" in
  leakage) leakage ;;
  ragas) ragas ;;
  conversation) conversation ;;
  all) leakage; ragas; conversation ;;
  *) echo "unknown MODE=$MODE (leakage | ragas | conversation | all)"; exit 2 ;;
esac

# what produced these reports: image digest, model and its limits as the code resolved them, judge
# settings, each step's exit code (never compare reports made under different settings)
STARTED="$STARTED" STEPS="$STEPS" OUT="$OUT" python - <<'PY' || { echo "FAILED: run-config.json"; status=1; }
import datetime as dt
import json
import os

from app.config import get_settings

s = get_settings()
steps = [ln.split(" ", 1) for ln in open(os.environ["STEPS"]).read().splitlines() if ln]
cfg = {
    "image": os.environ.get("IMAGE_REF"),
    "execution": os.environ.get("CLOUD_RUN_EXECUTION"),
    "mode": os.environ.get("MODE"),
    "label": os.environ.get("LABEL"),
    "users": os.environ.get("USERS") or "all",
    "jobs": os.environ.get("JOBS"),
    "started": os.environ["STARTED"],
    "finished": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "model": {
        "name": s.gemini_model,
        "location": s.gemini_location or s.gcp_region,
        "max_output_tokens": s.llm_max_output_tokens,
        "timeout_s": s.llm_timeout_s,
    },
    "judge": {
        "model": os.environ.get("JUDGE_MODEL", "gemini-3.5-flash"),
        "max_tokens": int(os.environ.get("JUDGE_MAX_TOKENS", "8192")),
        "ragas": "0.4.4",
        "baseline": os.environ.get("RAGAS_BASELINE"),
    },
    "steps": [{"exit": int(rc), "command": cmd} for rc, cmd in steps],
}
name = os.path.basename(os.environ["OUT"]) + "-run-config.json"
with open(os.path.join(os.environ["OUT"], name), "w") as fh:
    json.dump(cfg, fh, indent=2)
print(json.dumps(cfg, indent=2))
PY

# the new reports (never the baselines that came with the image) go to the bucket
comm -13 "$before" <(ls "$REPORTS" | sort) | while read -r f; do cp "$REPORTS/$f" "$OUT/"; done
echo "=== reports: gs://<artifacts bucket>/eval-reports/$(basename "$OUT")/ ==="
for f in "$OUT"/*.md; do [[ -f "$f" ]] && { echo "--- $(basename "$f") (first lines) ---"; head -40 "$f"; }; done
exit "$status"
