# ADR-0026 — Rung L2 (meaning + keyword search) on BigQuery in asia-south1, in place of Vertex AI Search

- **Date:** 14 Nov 2026 · **Status:** Accepted by the owner, 14 Nov 2026 ("proceed with option B"). A substitution
  under CLAUDE.md §2.3; CoE / department still to confirm the data-residency requirement itself (ADR-0017)
- **Plan:** §3.2 (L2), §3.6 · **Changes:** the plan's L2 store · **Milestone:** M3

## Why (the reason for the decision)
1. **Vertex AI Search cannot run in India.** Google offers its data stores only in `global`, `us` and `eu`
   (locations page, read 14 Nov 2026). The project's region is asia-south1, and ADR-0017 already rules out the
   global endpoint because it gives no data-residency guarantee. The records this system is for are
   departmental e-Office papers; indexing them outside India is not something this project can decide.
2. **BigQuery is already the L0/L1 store, in region.** Putting L2 in the same dataset means one store for three
   rungs and no new service.
3. **One access rule, already proven.** The scope predicate that guards L0/L1 (ADR-0025) guards L2 unchanged:
   every passage row carries its document's access tags, and the scope is the WHERE clause of the search. A
   passage outside the officer's scope is never scored. With Vertex AI Search the same rule would have had to be
   re-expressed in a second filter language and proven again.
4. **Scale fits.** About 1,400 orders → on the order of 10⁴ passages. An exact (brute-force) cosine search over
   that is trivial for BigQuery; no vector index is needed, so there is no approximate-search recall question.

## What is built
- Table `<project>.c2_metadata.passages`: passage text (about 1,200 characters, 200 overlap), its embedding,
  the embedding model's name, and the document's access tags and descriptive columns. Derived data, replaced in
  one load job per build (from a file the job writes to the artifacts bucket).
- Embeddings: a Vertex AI text-embedding model called in asia-south1, never the global endpoint. The model is a
  setting with no default (`C2_EMBEDDING_MODEL`): `17_embedding_check.py` shows which models answer in region
  and how they treat Telugu, and the owner picks one.
- Search (`app/retrieval/bigquery_l2.py`, one fixed template): score = 0.7 × cosine similarity of the best
  passage + 0.3 × share of the question's words found in it; best passage per document; top K. The question
  reaches BigQuery only as a bound vector and bound words. Rows are re-checked with `scope.admits` in code.
- Same `HybridRetriever` interface as the keyword stand-in, so the ladder does not change.

## Consequences / limits
- **Not Vertex AI Search:** no built-in reranker, no extractive answers, no query understanding. Ranking quality
  must be measured (Recall@K, MRR on the golden questions) against the keyword stand-in before it replaces it.
- The 0.7 / 0.3 weights and the passage size are starting values, not calibrated. The ladder's L2 threshold
  (`l2_rerank_min_score`) was set for the stand-in's scores and must be set again for this 0-to-1 score.
- Every query scans the passages table (small). At a much larger corpus: a BigQuery vector index with
  pre-filtering, or the plan's store if it becomes available in India.
- An embedding call is needed per question; if it fails, L2 fails closed (no unscoped or keyword-only fallback
  is taken silently).
- If the embedding model is changed, the whole table must be rebuilt (the model name is stored per row).
- `CLAUDE.md` §2.2 and the plan still name Vertex AI Search at L2: to be amended by the owner to point here.

## Alternatives rejected
- **Vertex AI Search in global / us / eu for public + synthetic data only:** keeps the plan, but the PoC would
  then prove a path that cannot be used for the real records.
- **Vertex AI Vector Search (regional):** a second store and a second filter language for the same rule.
- **Keep the keyword stand-in:** in region, but no search by meaning.

## Addendum, 15 Nov 2026 — building the passages table
- Service roles granted by the admin (bigquery.jobUser, aiplatform.user on c2-api and c2-ingest), so the
  graph job embeds and loads as c2-ingest, and c2-api can search and embed questions at serving time.
- **Resumable embedding:** passages are written as part files of 25 orders under `graph/passages/`, each
  with a manifest written only once the part is complete (model name, each order's text hash). A run
  that stops loses at most one part; the next run keeps every complete part made by the same model for
  unchanged text, embeds only the rest, and loads exactly the kept parts (`loaded.json`). Parts not
  kept stay in the bucket unused — nothing is deleted.
- **Quota:** 408/429/5xx answers are retried with pauses of 2, 4, 8… up to 60 s (6 tries), then the job
  fails closed. A model that refuses several texts per call is found on the first refused batch and is
  then called one text at a time for the rest of the run.
- **Threshold:** `cloud_ladder_check.py` now reports L2 evidence — known-item recall (twelve copied
  words; an upper bound) and best-score spreads against ten off-domain questions — and proposes a
  value only when the two separate. `C2_L2_CLOUD_MIN_SCORE` stays unset until the owner approves one;
  unset, cloud L2 adds candidates but never ends the ladder on its own.
- **Built and checked (15 Nov 2026, owner's run):** job `c2-graph-build-z29sb` (~45 min, exit 0) loaded 17,696
  passages from all 1,290 indexed orders with 1,969 requests to gemini-embedding-001 (768, asia-south1);
  `cloud_ladder_check.py`: L2 top-10 equal to the reference on 18/18 questions (L0 453, L1 27, L3 121: 0
  different). Threshold evidence: known-item (copied words) recall@1 0.45, @10 0.88, best scores 0.743–0.80;
  off-domain max 0.561; proposal 0.656.
- **Threshold not set (decision):** in the ladder the L2 threshold only decides which rung is named as having
  answered (`answered_by`, the ladder label); L3 runs whenever relations are needed and no answer depends on
  it. The evidence also measures the easy case (off-domain questions), not the one that matters (an
  in-domain question whose best passage is the wrong order — recall@1 is only 0.45 even with copied words).
  `C2_L2_CLOUD_MIN_SCORE` stays unset; revisit with officer-worded questions when ladder-level accuracy on
  the public corpus is measured. Follow-up: look at the 12 % of copied-word questions that missed the top
  10 (likely boilerplate shared by many orders).
