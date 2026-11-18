#!/usr/bin/env bash
# Spanner Graph for the knowledge graph (plan §3.6, §5.2; ADR-0048). Dry run by default; APPLY=1 executes.
#   - a FREE TRIAL instance (owner, 18 Nov 2026): no charge for 90 days, Spanner Graph included, 10 GB,
#     one per project lifetime, no SLA. After 90 days it stops serving and is deleted 30 days later
#     unless upgraded:  gcloud spanner instances update c2-spanner --instance-type=provisioned  (billed).
#   - database c2graph with data/schemas/spanner/0001_graph.ddl (graph_nodes, graph_edges, property graph)
#   - access, least privilege: c2-api reads (databaseReader); c2-ingest reads/writes (databaseUser)
#   - PART=dev (developer, roles/editor): instance + database. PART=owner (project owner / Spanner Admin):
#     the two database IAM bindings (setIamPolicy is not in roles/editor). Default: both, in order.
#   Then: load the graph (27_spanner_graph_load.py), compare (evaluation/cloud_ladder_check.py
#   --spanner-instance), and only then switch the API (20_api_service.sh GRAPH=spanner).
source "$(dirname "$0")/lib.sh"
ROOT="$(cd "$HERE/../.." && pwd)"
INSTANCE="${SPANNER_INSTANCE:-${PREFIX}-spanner}"
DATABASE="${SPANNER_DATABASE:-${PREFIX}graph}"
PART="${PART:-all}"
DDL_SRC="$ROOT/data/schemas/spanner/0001_graph.ddl"
[[ -f "$DDL_SRC" ]] || { echo "missing $DDL_SRC" >&2; exit 1; }
# gcloud takes ';'-separated statements; the schema's comment lines are dropped first
DDL="$(mktemp)"; trap 'rm -f "$DDL"' EXIT
grep -v '^[[:space:]]*--' "$DDL_SRC" | sed 's/[[:space:]]*--.*$//' > "$DDL"

if [[ "$PART" != "owner" ]]; then
  run gcloud services enable spanner.googleapis.com --project "$PROJECT_ID"
  if [[ "$APPLY" == "1" ]] && gcloud spanner instances describe "$INSTANCE" --project "$PROJECT_ID" >/dev/null 2>&1; then
    echo "= instance $INSTANCE exists"
  else
    run gcloud spanner instances create "$INSTANCE" --project "$PROJECT_ID" \
      --instance-type=free-instance --config "regional-${REGION}" \
      --description "C2-24 graph (free trial)"
  fi
  if [[ "$APPLY" == "1" ]] && gcloud spanner databases describe "$DATABASE" --instance "$INSTANCE" --project "$PROJECT_ID" >/dev/null 2>&1; then
    echo "= database $DATABASE exists (schema left as it is)"
  else
    run gcloud spanner databases create "$DATABASE" --instance "$INSTANCE" --project "$PROJECT_ID" \
      --ddl-file "$DDL"
  fi
fi

if [[ "$PART" != "dev" ]]; then
  run gcloud spanner databases add-iam-policy-binding "$DATABASE" --instance "$INSTANCE" --project "$PROJECT_ID" \
    --member "serviceAccount:$(sa_email api)" --role roles/spanner.databaseReader
  run gcloud spanner databases add-iam-policy-binding "$DATABASE" --instance "$INSTANCE" --project "$PROJECT_ID" \
    --member "serviceAccount:$(sa_email ingest)" --role roles/spanner.databaseUser
fi
echo "instance: $INSTANCE ($PROJECT_ID, regional-$REGION, free trial) · database: $DATABASE"
