# ADR-0017: Keep everything in asia-south1 (Mumbai); Gemini 3.5 Flash for reasoning and drafting

- **Date:** 2026-11-11
- **Status:** Proposed (region: CoE / department to confirm data residency). Point 4 (OCR model pin) accepted by the owner, 11 Nov 2026
- **Plan section:** §3.5 (GCP services), §7 (agents / Gemini); CLAUDE.md §2.1, §2.2

## Context
GCP access arrived on 11 Nov 2026 (project `use-case-24-project`). The org policy puts no limit on
locations. The open question was whether every service the plan needs exists in one Indian region.
We checked it in the project itself, with `infrastructure/gcp/09_regional_checks.sh` (read-only,
no cost):
- **Document AI in asia-south1:** OCR and Form Parser processors can be created; the OCR processor
  `c2-ocr` exists. Layout Parser is listed but **cannot be created** there (us/eu only), so page and
  paragraph locators come from the OCR output.
- **Gemini in asia-south1:** of the 38 Gemini IDs in Model Garden, only `gemini-3.5-flash` and
  `gemini-3.5-flash-lite` answer there (countTokens HTTP 200). All the others return 404.
- **The global endpoint** gives no data-residency guarantee (Google docs), so it is not a fallback.
- Buckets, BigQuery datasets and Artifact Registry were already created in asia-south1. They are
  empty and can be recreated.

## Decision (proposed)
1. **Every regional resource goes in `asia-south1`**: Storage, Document AI, Vertex AI (Gemini,
   embeddings, Search where offered), BigQuery, Cloud SQL, Spanner, Cloud Run, Artifact Registry.
2. **Gemini model:** `gemini-3.5-flash` for grounded judgment (types B, D, G) and drafting, and
   `gemini-3.5-flash-lite` for cheap classification and slot-filling. Both are set in config, not
   code, and the model ID is recorded in every evaluation report.
3. **No global endpoint**, and no model outside the region, without a new decision.
4. **Pin the Document AI OCR model version** in config (`C2_DOCAI_OCR_PROCESSOR_VERSION`), and
   record it in every OCR report. The processor default in asia-south1 is
   `pretrained-ocr-v1.0-2020-09-23`, which **cannot read Telugu**. On the synthetic Telugu photo D16
   (probe, 11 Nov 2026, `evaluation/reports/2026-11-11-ocr-telugu-probe.md`) it gave Latin-script
   noise: confidence 0.51, word recall 0.04, with or without te/en hints. `pretrained-ocr-v2.1.1-2025-01-31`
   (Google "Release Candidate", deployed in asia-south1) read the same photo at confidence 0.97 and
   recall 0.98. Full scan comparison (8 files, replay with rows rebuilt from line geometry):
   v2.1.1 had word recall 0.960 vs 0.842 and English page confidence 0.974–0.989 vs 0.963–0.984;
   identities 7/8 on both. **Pin v2.1.1: accepted by the owner, 11 Nov 2026.** Google labels it
   "Release Candidate", so re-run `evaluation/ocr_scans.py` before any version change.
   Responses are cached per version, so models are never mixed.

## Alternatives
| Option | Why not (now) |
|---|---|
| `us` / `us-central1` for Document AI or Gemini | Data leaves India; only worth it if the department allows that |
| Global endpoint for newer models | No residency guarantee |
| Wait for Pro-class models in asia-south1 | Blocks P3–P5. Flash can be swapped later through config, with an evaluation run |

## Consequences
- Prompts and evaluation baselines are set on `gemini-3.5-flash`. Any later model change re-runs
  the RAG, citation and conflict suites (CLAUDE.md §9.5).
- Still to check in-region when each piece is built: Vertex AI embeddings and Vertex AI Search data
  stores. If one of them is missing in asia-south1, raise it as a new decision; don't silently use
  another region.

## Addendum — first use: conflict types B / G (13 Nov 2026, owner OK)
- `backend/app/agents/llm.py`: Gemini on the regional Vertex AI endpoint (`gemini_location` defaults to
  `gcp_region`, never the global endpoint), temperature 0, JSON answer with a response schema. Each answer is
  cached on disk per model and request (`data/synthetic/mock_v1/llm/<model>/`), so a question is paid for once;
  `C2_LLM_PROVIDER=recorded` replays the cache with no calls; default `none` (check not run).
- `backend/app/conflict/judgment.py` + `prompts/conflict_contradiction.v1.md`. Only pairs of cited records the
  officer may see, with at least one lower instrument, and not joined by a supersede / amend link (those are A / F).
  The model sees only excerpts of the two texts, marked as data. An answer counts only when both quotes appear word
  for word in those excerpts. B vs G is decided from hierarchy levels, not by the model. Flags are advisory and
  uncertain. If the model fails, the pre-send report says the check is incomplete (fail closed).

## Addendum — B / G after the first live run (13 Nov 2026)
First live run (29 questions, 0 incomplete): B 7/8, G 2/10, clean 0/38 flagged. Hand check: the 7 B flags are right;
2 extra G flags were weak (same rule in other words; a quote about another provision). Causes of the G misses, fixed:
- excerpts: OCR'd rule texts have no paragraph breaks, so whole-paragraph excerpts skipped the clause. Now the head
  plus half-overlapping line windows (~400 chars), ranked by word and word-pair overlap with the other document
  (rarer terms count more); the officer's note only breaks ties and is never sent; up to 6,000 chars per document;
- gazette citations in notes ("A.P. Gazette (Extraordinary / PART I) No.3880, dated …") now resolve to the masthead
  ID; without a printed edition and part they stay unresolved (nothing guessed);
- prompt `conflict_contradiction.v2`: same rule in other words is not a contradiction; both quotes on the same point;
  a missing passage means "insufficient". v1 is kept for the recorded first run.
A new prompt or excerpt changes every request key, so the next live run asks all questions again (31, cents).
After the prompt-v2 run (G 7/10): the quote check ignores spacing around hyphens only (OCR line breaks); an
unconfirmed supersession inferred from matching subjects (§7.3) no longer exempts a pair from the check, while links
stated in the text or confirmed by an officer still do.

## Mentor / department input
The CoE / department must confirm that asia-south1 meets the data-residency requirement.
