#!/usr/bin/env bash
# Collect FIN01, GAD01, ESE01 for 2016–2025 (YEARS="2017 2016" for a subset) from the archive mirror, then the orders they cite (depth 1).
# Usage:   bash data_collection/tools/run_batches.sh   # TEST MODE: 2 new orders per dept-year
#          bash tools/run_batches.sh ESE01           # one department
#          LIMIT=20 bash tools/run_batches.sh GAD01  # fewer orders per year
# Safe to stop (Ctrl+C) and re-run: existing orders are skipped. Logs go to logs/.
# Corpus is frozen as of 31-12-2025 (scope.yaml as_of); no 2026 orders are collected.
set -u
# Code lives in Project_1/data_collection (ADR-0006); the corpus lives in the data root ($C2_DC_DATA_ROOT or
# data_collection/local.env). Tools are called by absolute path; staging/ and logs/ are relative to the data root.
TOOLS="$(cd "$(dirname "$0")" && pwd)"
PKG="$(dirname "$TOOLS")"
if [ -z "${C2_DC_DATA_ROOT:-}" ] && [ -f "$PKG/local.env" ]; then
  C2_DC_DATA_ROOT="$(grep -E '^C2_DC_DATA_ROOT=' "$PKG/local.env" | head -1 | cut -d= -f2- | sed -e 's/^["]//' -e 's/["]$//')"
fi
case "${C2_DC_DATA_ROOT:-}" in "~/"*) C2_DC_DATA_ROOT="$HOME/${C2_DC_DATA_ROOT#\~/}";; esac
if [ -z "${C2_DC_DATA_ROOT:-}" ] || [ ! -d "$C2_DC_DATA_ROOT" ]; then
  echo "Set C2_DC_DATA_ROOT (see data_collection/local.env.example)" >&2; exit 1
fi
export C2_DC_DATA_ROOT
PY=${PY:-$PKG/.venv/bin/python}
cd "$C2_DC_DATA_ROOT"
# TEST MODE by default (18 Oct 2026: tools are built and tested on a few files only).
# Full run needs FULL=1:  FULL=1 bash tools/run_batches.sh   (cap 60 per dept-year; highest estimate is 42)
if [ "${FULL:-0}" = "1" ]; then LIMIT=${LIMIT:-60}; else LIMIT=${LIMIT:-2}; echo "TEST MODE: $LIMIT new orders per dept-year (FULL=1 for a full run)"; fi
DEPTS=${*:-FIN01 GAD01 ESE01}
mkdir -p logs

# Network guard (12 Nov 2026: a network cut mid-run made every later request fail with an SSL error
# and the script raced through the remaining years). Before each step, wait until archive.org answers
# with a valid certificate, up to 60 minutes; a step that fails is retried once after the network is back.
net_ok() { "$PY" -c 'import requests,sys; requests.head("https://archive.org/", timeout=20); sys.exit(0)' >/dev/null 2>&1; }
wait_net() {
  local n=0
  until net_ok; do
    n=$((n+1)); [ "$n" -gt 60 ] && { echo "!! archive.org unreachable for 60 min, stopping; re-run to resume"; exit 2; }
    [ "$n" -eq 1 ] && echo "!! network down or intercepted (SSL); waiting, checking every 60 s"
    sleep 60
  done
}
step() {   # step <log> <args...>: run collect_ia once, and once more if it fails (after the network is back)
  local log="$1"; shift
  wait_net; "$PY" "$TOOLS"/collect_ia.py "$@" >> "$log" 2>&1 && return 0
  echo "!! step failed (see $log); retrying once after a network check"
  wait_net; "$PY" "$TOOLS"/collect_ia.py "$@" >> "$log" 2>&1 || echo "!! step failed twice: $*"
}

for d in $DEPTS; do
  for y in ${YEARS:-2025 2024 2023 2022 2021 2020 2019 2018 2017 2016}; do
    echo "== $d $y"
    step "logs/collect_${d}.log" --dept "$d" --from "$y-01-01" --to "$y-12-31" --limit "$LIMIT"
    grep -E "^seen" "logs/collect_${d}.log" | tail -1
  done
  echo "== $d: links, then cited orders (depth 1)"
  $PY "$TOOLS"/extract_relations.py staging | head -1
  step "logs/cited_${d}.log" --cited staging/manifests/missing.txt
  grep -E "^seen" "logs/cited_${d}.log" | tail -1
  $PY "$TOOLS"/extract_relations.py staging | head -1
  $PY "$TOOLS"/validate.py staging 2>/dev/null | tail -1
done

echo; echo "== coverage"
$PY "$TOOLS"/check_coverage.py | grep -E "PASS|PARTIAL|GAP"
find staging/rule-library -name meta.json | sed 's|.*rule-library/[a-z]*/||;s|/[0-9]*/AP.*||' | sort | uniq -c
