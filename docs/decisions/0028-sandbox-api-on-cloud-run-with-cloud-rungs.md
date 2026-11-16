# ADR-0028 — Sandbox API on Cloud Run, reading the public corpus from the cloud rungs

- **Date:** 15 Nov 2026 · **Status:** Accepted (owner, 14 Nov 2026: "API on Cloud Run reading the cloud rungs …
  complete them") · **Plan:** §3.2, §3.5, §11 · **Milestones:** M3, M8 (first deployment)

## Context
L0/L1 (BigQuery), L3 (Cloud SQL) and the L2 code (BigQuery passages) exist and agree with the in-memory reference
on the real services (`evaluation/reports/2026-11-14-cloud-ladder-check.md`: 601 questions, 0 different). The
sandbox API still answered only from memory, and ran only on a laptop.

## Decision
- **Two stores behind each rung.** The officer's e-Office papers (synthetic, ingested at start) stay in memory;
  the public order corpus is read from the cloud. `app/retrieval/composite.py` puts both behind the existing
  interfaces, so the ladder, tools and routes do not change:
  - L0/L1: the first store with an exact hit answers; filters are the union, newest first.
  - L3: one walk over both graphs (a step may go from an e-Office note in memory to a public order and on to the
    order that replaced it in Cloud SQL); the same breadth-first walk as the reference, the scope applied to every
    node before it is returned or expanded.
  - L2: the stores' scores are on different scales (BM25 vs 0–1), so each hit is judged against its own store's
    evidence threshold. A store with no calibrated threshold (the BigQuery L2 today) is listed but can never end
    the ladder at L2 by itself.
  - Every part applies the officer's scope itself; the wrapper only merges, so no part can widen another.
- **Switch:** `C2_RETRIEVAL_BACKEND=cloud` (default `memory`). Missing project, region or Cloud SQL settings stop
  the service at start (fail closed).
- **Deployment (`infrastructure/gcp/18–20`):** Cloud Run service `c2-api`, service account `c2-api`, not public
  (IAM-authenticated; opened with `gcloud run services proxy`). The public corpus and the synthetic set are
  mounted read-only from the raw bucket. The synthetic upload is an allowlist: the answer keys
  (ground truth, access matrices, scenarios) are never put where the service can read them. One instance at most
  (sandbox review state lives in memory). Saved Gemini answers by default (`LLM=recorded`); live Gemini is opt-in.

## Consequences / limits
- **Evidence text for cloud-only orders:** the cited-answer path quotes passages from texts held in memory. A
  public order that is only in the cloud (not cited by any synthetic file) can be found and walked, but not yet
  quoted: the evidence builder must read its passage text from the BigQuery passages table. Next step.
- The first assistant call after a cold start ingests the synthetic set (about 2 minutes).
- No frontend deployed yet (P8); the API is used through the proxy.
- The Cloud Run flags (volume `only-dir` mount option in particular) are written from the gcloud reference and
  have not run yet.

## Evidence
`tests/unit/test_composite_rungs.py` (12 tests): two graph stores walk exactly like one on 6 random graphs × 75
scoped walks; a walk crosses memory → cloud and never through a node outside the scope; two metadata stores answer
like one; L2 thresholds judged per store; the sandbox reads a cloud part through `/assist/search` within each
officer's scope (8 officers, a confidential order seen by exactly the cleared ones). Suite: 1435 passed, 5 skipped.

## Addendum — 15 Nov 2026
- **Deployed by the owner** (revision `c2-api-00002-2dz`): IAM-only (403 without sign-in), first search 319 s
  (synthetic set loaded), later calls under a second. The demo hold-back order was uploaded alone to
  `public-go/holdback/` (the sandbox reads it at start; the graph job reads only `rule-library/`).
- **A failing cloud store now fails closed with one neutral message**: any unexpected error ends the request
  with HTTP 503 and "The request could not be completed right now. Please try again later."; only the error's
  type is logged (the text can carry query parameters). Found when BigQuery refused c2-api (no
  `bigquery.jobs.create`).
- **Reference lookup (touchpoint 10) reads the cloud part** (it used the in-memory index only).
- **Cloud-only orders can be quoted**: when the passages table exists, an order held only in BigQuery has its
  text rebuilt from its passages (fixed template, scope in the WHERE clause, read only after the record passed
  the officer's re-check, overlaps removed). Closes the first limit above.

## Addendum, 15 Nov 2026 — the file of a cloud-only order
- **Found on the owner's deploy (revision c2-api-00003-jwb):** `GET /assist/documents/AP-GAD01-GOMS-31-2018` as
  V14 (GAD01, department-wide) → 404. The order is visible (BigQuery L0 + re-check), but the service keeps
  files only for the ~120 sandbox orders it ingests (`public_index.csv`); the other 1,170 public orders exist
  for it only in BigQuery, so there was no stored file to show, and the route gave the "not available" 404.
- **Fix:** the graph build records each indexed order's file path (relative to the corpus staging root) and
  SHA-256 in the documents table (`source_path`, `source_sha256`). For a record that passed the re-check and
  has no file in memory, the service reads `source_path`/`source_sha256` with the officer's scope in the
  WHERE clause (`CloudSourceFiles`), reads the file from the mounted corpus (`/mnt/corpus/staging`), refuses a
  path outside the corpus, and serves it only if the bytes hash to the recorded value. Anything else gives the
  same 404 as before.
- Needs one more graph-job run to fill the two columns (passages are reused: no new embedding requests).

## Addendum 2, 15 Nov 2026 — a fast start
- **Measured:** the first call after idle waited 319–373 s on Cloud Run. Profiled locally (py-spy, seed v2, same
  inputs): 99 % of the sandbox build was ingestion, and almost all of that was pypdf reading the 120 public
  orders' PDFs — each one read three times (detection's text, detection's `page.images`, which parses the content
  stream again, and native extraction). The 515 synthetic papers are not PDFs and cost almost nothing.
- **Read each PDF once:** `pdf_scan` keeps a file's page reads (text, carries-an-image) for the run, keyed by the
  file's hash; detection, extraction and `pdf_text_layer` share it.
- **Image check without a second parse:** `_has_image` finds image XObjects in the page's resources (and forms
  inside them) the way pypdf's `page.images` does, and asks pypdf the slow way only when the content may hold an
  inline image (`BI`). Same answer on every page checked: the whole public corpus (1,374 PDFs, 7,682 pages, 2,451
  with images: 0 different, 0 unreadable; same pypdf 6.21.4) plus the synthetic and test PDFs; about 15× faster.
- **Saved page reads:** the graph job writes each public order's page reads to `graph/pdf_scans/<sha256>.json`
  (`--pdf-scans`); c2-api mounts that folder read-only (`C2_PDF_SCAN_CACHE_DIR`) and uses a saved read only if it
  was made by the same pypdf version (then it is exactly what parsing gives) — otherwise it parses as before.
  c2-api gets objectViewer on the artifacts bucket for this (public orders' derived text only).
- **Warm start:** `C2_SANDBOX_WARM_START=true` builds the sandbox while the instance starts (with
  `--cpu-boost`; startup probe allows up to 10 min), so no officer request carries the build, and a broken build
  fails the start instead of every request.
- **Result locally:** sandbox build 113.7 s → 43.6 s (read once + fast image check) → 2.4 s (saved reads), with
  the same 343 indexed / 292 held and identical texts (checked). Cloud Run timing to be measured after deploy.
