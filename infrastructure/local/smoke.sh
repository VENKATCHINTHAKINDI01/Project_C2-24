#!/usr/bin/env bash
# Build and start the whole stack in containers, check it end to end, then stop it (ADR-0043).
# From the repo root:   bash infrastructure/local/smoke.sh
#   KEEP=1     leave the stack running afterwards (open http://localhost:${C2_WEB_PORT:-8080})
#   base images from a mirror: PYTHON_IMAGE=… NODE_IMAGE=… UV_IMAGE=… POSTGRES_IMAGE=… (see compose.yaml)
# Synthetic data only; nothing leaves this machine. Exit 0 = every check passed.
set -euo pipefail
cd "$(dirname "$0")/../.."
C=(docker compose -f infrastructure/local/compose.yaml)
W="http://127.0.0.1:${C2_WEB_PORT:-8080}"
fail=0
check() { if eval "$2" >/dev/null 2>&1; then echo "  ok    $1"; else echo "  FAIL  $1"; fail=1; fi; }
cleanup() { [[ "${KEEP:-0}" == "1" ]] || "${C[@]}" down -v --remove-orphans >/dev/null 2>&1; }
trap cleanup EXIT

echo "build and start (first build takes a few minutes)…"
"${C[@]}" up -d --build --wait >/dev/null
SID="$(od -An -N10 -tx1 /dev/urandom | tr -d ' \n')"
ask() { curl -fsS -D - -o /dev/null -X POST "$W/assist/chat" -H "X-Sandbox-User: $1" \
          -H "content-type: application/json" -d "{\"message\":\"$2\",\"session_id\":\"$SID\"}"; }

echo "checks:"
check "schema job applied every migration" \
  "[[ \$(${C[*]} ps -a migrate --format '{{.ExitCode}}') == 0 ]] && ${C[*]} logs migrate | grep -q \"applied \$(ls data/schemas/postgres/*.sql | wc -l | tr -d ' ') migration\""
check "screens are served" "curl -fsS $W/ | grep -q '<div id=\"root\">'"
check "mock sign-in lists officers, with the sandbox banner" "curl -fsS $W/sandbox/profiles | grep -q 'not NIC e-Office'"
check "an officer's question is answered and never cached" "ask U01 'Has a transfer on spouse grounds been decided before?' | grep -qi '^cache-control: no-store'"
check "unknown caller is refused" "[[ \$(curl -s -o /dev/null -w '%{http_code}' -X POST $W/assist/chat -H 'content-type: application/json' -d '{\"message\":\"hello there\"}') == 401 ]]"
check "conversation kept in Postgres across an API restart" \
  "${C[*]} restart api && ${C[*]} up -d --wait api && ask U01 'Summarise that again' && [[ \$(${C[*]} exec -T db psql -U c2 -d c2 -tAc 'select count(*) from session_turns') -ge 2 ]]"
check "audit events recorded" "[[ \$(${C[*]} exec -T db psql -U c2 -d c2 -tAc 'select count(*) from audit_events') -ge 1 ]]"
check "API and database have no host port" "! ${C[*]} ps --format '{{.Service}} {{.Ports}}' | grep -E '^(api|db) .*->'"
check "app containers run as non-root on a read-only filesystem" \
  "for s in api web; do [[ \$(${C[*]} exec -T \$s id -u) == 10001 ]] && ! ${C[*]} exec -T \$s touch /srv/probe; done"

if [[ $fail == 0 ]]; then echo "PASS: the stack works end to end"; else echo "FAILED: see above"; fi
[[ "${KEEP:-0}" == "1" ]] && echo "running: $W  (stop: ${C[*]} down)"
exit $fail
