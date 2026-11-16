#!/usr/bin/env bash
# Memorystore for Redis — the shared answer + question-embedding cache (plan §10.2; CLAUDE.md §2.2
# "cache only"; ADR-0035). Dry run by default; APPLY=1 executes; I_ACCEPT_COST=1 is required too:
# a Basic 1 GB instance bills every hour it exists (~USD 35-50 / month in asia-south1, check pricing).
#   - instance c2-cache, Basic tier (no replica: a cache may be lost), private IP on the default VPC,
#     AUTH on; the connection URL (with the AUTH string) goes to Secret Manager secret c2-redis-url,
#     readable by c2-api only. Nothing secret is printed or written to disk.
#   - then: REDIS=1 APPLY=1 bash 20_api_service.sh  (adds Direct VPC egress + the secret to c2-api)
#   - to stop paying: gcloud redis instances delete c2-cache --region <region>  (the app falls back
#     to its in-memory cache once C2_REDIS_URL is removed: REDIS=0 bash 20_api_service.sh)
source "$(dirname "$0")/lib.sh"
require_cost_ack "Memorystore for Redis"
NAME="${PREFIX}-cache"
SECRET="${PREFIX}-redis-url"
NETWORK="${NETWORK:-default}"
run gcloud services enable redis.googleapis.com secretmanager.googleapis.com --project "$PROJECT_ID"
run gcloud redis instances create "$NAME" --project "$PROJECT_ID" --region "$REGION" \
  --tier basic --size 1 --redis-version redis_7_2 --network "$NETWORK" --enable-auth \
  --labels "app=c2-24,purpose=cache"
if [[ "$APPLY" == "1" ]]; then
  HOST="$(gcloud redis instances describe "$NAME" --project "$PROJECT_ID" --region "$REGION" --format 'value(host)')"
  PORT="$(gcloud redis instances describe "$NAME" --project "$PROJECT_ID" --region "$REGION" --format 'value(port)')"
  AUTH="$(gcloud redis instances get-auth-string "$NAME" --project "$PROJECT_ID" --region "$REGION" --format 'value(authString)')"
  if ! gcloud secrets describe "$SECRET" --project "$PROJECT_ID" >/dev/null 2>&1; then
    gcloud secrets create "$SECRET" --project "$PROJECT_ID" --replication-policy user-managed \
      --locations "$REGION"
  fi
  printf 'redis://:%s@%s:%s/0' "$AUTH" "$HOST" "$PORT" \
    | gcloud secrets versions add "$SECRET" --project "$PROJECT_ID" --data-file=-
  unset AUTH
  echo "+ secret $SECRET has a new version (not shown)"
else
  echo "[dry-run] read host/port/AUTH of $NAME and store redis://:<auth>@<host>:<port>/0 in secret $SECRET"
fi
run gcloud secrets add-iam-policy-binding "$SECRET" --project "$PROJECT_ID" \
  --member "serviceAccount:$(sa_email api)" --role roles/secretmanager.secretAccessor
echo "next: REDIS=1 EMBEDDING_MODEL=gemini-embedding-001 APPLY=1 bash 20_api_service.sh"
