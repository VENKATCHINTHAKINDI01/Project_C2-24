# GCP setup runbook: access day

Minimal PoC infrastructure (plan §3.5, §14.6). One project, synthetic data plus the public G.O. corpus (ADR-0006; public records only, no department data). **No Terraform, CI/CD, Pub/Sub, Dataflow or other Tier-3 services** (CLAUDE.md §2.3). Nothing here has been run against a real project yet. Use `verify.sh` output as the evidence before anything is marked done.

## 0. Before access arrives

Ask the CoE / project admin for:

| Item | Why |
|---|---|
| Project ID + billing account attached | everything |
| Your role: `roles/owner`, or `editor` + `resourcemanager.projectIamAdmin` + `iam.serviceAccountAdmin` | to run `02_service_accounts.sh` |
| Region / data-residency rule (we propose `asia-south1`, Mumbai) | all regional resources. **[To confirm]** |
| Budget + budget alert on the billing account | Cloud SQL and Spanner bill while idle |
| Org policy constraints (e.g. `iam.disableServiceAccountKeyCreation`, allowed locations, domain-restricted sharing) | may block steps below; we use no SA keys anyway |
| Gemini model access on Vertex AI in the chosen region | drafting/reasoning |
| Whether IAP OAuth consent / an internal user group is available | app gating (P8) |

Install the CLI locally: `brew install --cask google-cloud-sdk`, then `gcloud auth login` and `gcloud auth application-default login`.

## 1. Run order

```bash
cd infrastructure/gcp
cp config.env.example config.env        # fill PROJECT_ID, REGION (config.env is git-ignored)
gcloud config set project <PROJECT_ID>

./00_access_check.sh                      # READ-ONLY: who am I, roles, billing, org policies -> access_check.out.txt
./01_apis.sh                              # dry run: prints commands
APPLY=1 ./01_apis.sh                      # executes
APPLY=1 ./02_service_accounts.sh
APPLY=1 ./03_storage.sh
# 08_upload_public_corpus.sh: NOT now — the old public corpus is to be archived and re-collected
# (owner decision, 9 Nov 2026); upload the new collection when it is ready
APPLY=1 ./04_bigquery.sh
APPLY=1 ./07_artifact_registry.sh
I_ACCEPT_COST=1 APPLY=1 ./05_cloudsql.sh  # bills while idle
# then, from backend/: env -u VIRTUAL_ENV uv run python ../infrastructure/gcp/12_cloudsql_schema.py  (dry run; APPLY=1 creates tables + grants)
# knowledge graph on GCP (ADR-0023), after 12 has been applied:
./13_backend_image.sh                     # Cloud Build -> Artifact Registry (allowlisted context; BUILD_REGION=global if the regional pool is refused)
./14_graph_job.sh                         # Cloud Run Job c2-graph-build; APPLY=1 RUN=1 runs it, LIMIT=50 for a trial
I_ACCEPT_COST=1 APPLY=1 ./06_spanner.sh   # bills while idle; create when P1/P3 graph work starts
./verify.sh                               # read-only evidence; paste into PROGRESS.md
```

Scripts are not idempotent on re-run: `create` fails with "already exists". That's expected; skip that step.

## 2. Manual steps (no script, because exact commands depend on console/API options at the time)

| When | Step | Note |
|---|---|---|
| P1 | Public corpus: OCR the scans listed in `pending_ocr.jsonl` and the 100 orders with unreadable printed dates, extract effective dates, then re-run `data_collection/tools/{reconcile_dates,audit_corpus,extract_relations}.py` | see `data_collection/README.md` |
| P1 | Create Document AI processors: Enterprise Document OCR (+ Layout Parser / Form Parser for tables) | **Verify which locations offer them.** Historically only `us`/`eu` multi-regions. That's a data-residency question for the department. |
| P1/P3 | Create a Vertex AI Search data store (unstructured docs with metadata) + search app | Filterable fields must include department, section, classification, file_id (plan §4.6). Verify location options. |
| P3 | Memorystore (Valkey/Redis), smallest tier | Cache only. Create it when caching is built, not before (cost). Needs a VPC connector / Direct VPC egress from Cloud Run. |
| P8 | IAP in front of Cloud Run (backend + frontend) | Needs OAuth consent screen + allowed group. |
| Any | Secret Manager entries | None needed yet: Cloud SQL uses IAM DB auth and Cloud Run uses its service account. Add only when a real secret appears. |

## 3. Service accounts (least privilege, PoC level)

| SA | Runs | Roles (project-level for now; tighten to resource-level later) |
|---|---|---|
| `c2-api` | Cloud Run backend | aiplatform.user, discoveryengine.viewer, bigquery.jobUser + dataViewer, spanner.databaseReader, cloudsql.client + instanceUser, secretmanager.secretAccessor, storage.objectViewer; bigquery.dataEditor on `c2_audit` only |
| `c2-ingest` | Cloud Run Jobs (batch ingestion) | documentai.apiUser, aiplatform.user, discoveryengine.editor, bigquery.jobUser + dataEditor, spanner.databaseUser, cloudsql.client + instanceUser, storage.objectAdmin |
| `c2-frontend` | Cloud Run frontend | none |

No service-account keys are created. Local dev uses your own ADC credentials.

## 4. After setup

1. Paste `verify.sh` output into the PROGRESS.md task ledger.
2. Set `C2_ENV=gcp`, `C2_GCP_PROJECT_ID`, `C2_GCP_REGION` in `.env` (never commit it).
3. Record the confirmed region and any org-policy surprises in `docs/LEARNINGS.md` and an ADR.
