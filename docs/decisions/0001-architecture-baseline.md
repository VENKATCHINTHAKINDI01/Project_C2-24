# ADR-0001: Architecture baseline (modular monolith on GCP)

- **Date:** 2026-10-13
- **Status:** Accepted
- **Plan section:** §3.5, §3.6

## Context
Need one agreed stack before coding.

## Decision
FastAPI modular monolith on Cloud Run; LangGraph over typed AgentState; Gemini + embeddings on Vertex AI; Vertex AI Search (L2); Spanner Graph behind GraphRepository (L3); BigQuery (L0/L1, audit, query log); Cloud SQL Postgres (authz tuples, checkpointer); Memorystore (cache only); Document AI (OCR).

## Alternatives considered
| Option | Why not |
|---|---|
| Microservices | PoC scale; module boundaries kept for later split |
| BigQuery-only | Weak multi-hop supersession traversal |
| Neo4j / other vector DB | Not native GCP; extra operations |

## Consequences
Swapping the graph store needs only a new GraphRepository implementation.

## Mentor input (if any)
Plan reviewed; mentor found the plan good (13 Oct 2026).
