# ADR-0023 — Knowledge graph in Cloud SQL first, Spanner Graph later; built on GCP by a Cloud Run Job

- **Date:** 14 Nov 2026 · **Status:** Accepted (owner, 14 Nov 2026: "Cloud SQL now, Spanner later"; "use GCP for building") · **Plan:** §3.5, §3.6, §4, §5.2 · **Milestones:** M1, M2

## Context
The plan's graph store is Spanner Graph, with the note (§3.6) that the relation schema is store-agnostic and
Postgres is the allowed alternative. On 14 Nov 2026 the project has no Spanner instance (it bills while idle) and a
Cloud SQL instance that is already paid for and already holds the review queue and audit trail. The corpus is
small (1,374 public orders, about 4,300 candidate relations). Until now the graph existed only in memory, rebuilt
by the sandbox at start-up from the 120 orders the synthetic set cites.

## Decision
- **Store:** two tables in Cloud SQL, `graph_nodes` and `graph_edges` (`data/schemas/postgres/0002_graph.sql`), in
  the plan's store-agnostic shape: an edge is (source, kind, target, confirmed). A node carries the access tags
  the scope needs (department, section, classification, file number) plus descriptive columns.
- **Same interface:** `PostgresGraphRepository` implements `GraphRepository`. Agents, the ladder and the temporal
  engine do not change; moving to Spanner Graph later means one more adapter and a copy of two tables.
- **Scope at every step:** the walk is done one hop at a time in the application, and `scope.admits` is applied to
  every node before it is returned or expanded — the same code path as the in-memory reference, proved equal by
  a contract test on random graphs with mixed classifications. No recursive SQL: a recursive query would have to
  re-implement the access rule in SQL, and two copies of an access rule drift.
- **Built on GCP, not on the laptop:** Cloud Run Job `c2-graph-build` (service account `c2-ingest`, no keys) runs
  the NORMAL ingestion pipeline (`python -m app.graph.build`) over the raw bucket mounted read-only, writes
  `nodes.jsonl`, `edges.jsonl`, `held.jsonl`, `report.md` to the artifacts bucket, then upserts into Cloud SQL
  with IAM login. The image is built by Cloud Build from an allowlisted context (no `.env`, no data).
- **Least privilege:** `c2-ingest` may SELECT / INSERT / UPDATE the graph tables (no DELETE); `c2-api` may only
  SELECT.
- **No paid model calls:** scans replay the Document AI readings already in `public-go/ocr_recorded/`.

## Consequences / limits
- A walk costs one or two small queries per visited node. Fine at this size and at `l3_max_hops` 2–3; at a much
  larger corpus this is the reason to move to Spanner Graph (or to batch the frontier per hop).
- Edges read by pattern stay `confirmed = false` until an officer confirms them (plan §7.3); the walk skips them
  unless asked. Nothing is promoted by the load.
- The load only adds and updates. An order that later fails ingestion keeps its old row until a rebuild into
  empty tables; acceptable for a public, append-only corpus, to be revisited with restricted data.
- The OCR auto-pass threshold used by the job is the uncalibrated sandbox value; the report says so.
- The running API still builds its in-memory graph from the sandbox seed. Reading the graph from Cloud SQL at
  request time is the next step (with Vertex AI Search / BigQuery for the other rungs).

## Alternatives rejected
- **Spanner Graph now:** the planned store, but an idle cost with no benefit at 1,374 nodes. Deferred, not dropped.
- **Recursive CTE walk:** fewer round trips, but the access rule would live twice.
- **Build on the laptop and upload the result:** the owner asked for the build to run on GCP; it also keeps the
  corpus, the build and the store inside the project boundary.
