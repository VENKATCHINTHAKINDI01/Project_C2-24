# ADR-0025 — Ladder rungs L0/L1 on BigQuery; where L2 can run is an open decision

- **Date:** 14 Nov 2026 · **Status:** L0/L1: Accepted (the plan's own choice, now built). L2 location: decided 14 Nov 2026 → option B, see ADR-0026 · **Plan:** §3.2, §3.6, §5.2 · **Milestone:** M3

## L0 / L1 on BigQuery (built)
- One table, `<project>.c2_metadata.documents` (asia-south1): canonical ID, base ID, access tags (department,
  section, classification, file number), type, hierarchy level, dates, subject. Derived data: the graph build job
  replaces it in one load job each run (readers see the old table or the new one, never half).
- Two fixed templates (`app/retrieval/bigquery_index.py`): exact ID (L0) and structured filter (L1). The officer's
  scope is part of the WHERE clause of both; every value is a bound parameter; the table name is validated at
  start-up. No SQL is built from a question or by a model.
- Defence in depth: each returned row is checked again with `scope.admits`; a row the rule refuses is dropped and
  logged as a defect. An unknown classification matches neither marking list, so it is outside every scope.
- Proof without the cloud: the same templates run on DuckDB in the unit tests and give the same answers as the
  in-memory reference on random corpora (mixed departments, markings incl. an unknown one, file papers) under
  five scopes. Proof on the cloud: `evaluation/cloud_ladder_check.py` (owner run).
- New dev-only dependency: `duckdb` (tests). Not in the image.

## L2: Vertex AI Search has no India location (finding, 14 Nov 2026)
Google's locations page lists `global`, `us` and `eu` for Vertex AI Search data stores — no `asia-south1`, no
India multi-region. ADR-0017 already says the global endpoint is not a fallback because it gives no residency
guarantee. So the plan's L2 store cannot run in the project's region. Options:

| Option | Residency | Plan | Notes |
|---|---|---|---|
| A. Vertex AI Search in `global` / `us` / `eu`, public orders and synthetic files only | Outside India | As planned | Fine for a PoC on public + synthetic data; must be re-decided before any restricted departmental paper is indexed |
| B. BigQuery in asia-south1 as L2: vector search over Vertex AI embeddings + keyword match, same table and scope predicate as L0/L1 | In region (if the embedding model is served in asia-south1 — to verify) | **Substitution** (CLAUDE.md §2.3 needs explicit approval) | One store for L0–L2, scope predicate already proven; quality to be measured against the keyword stand-in |
| C. Keep the keyword stand-in for the PoC | In region | Gap stays | No semantic search |

Decided the same day: option B (owner). Built and recorded in ADR-0026.
