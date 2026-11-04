# Evaluation harness

Independent of `backend/app/` (CLAUDE.md §9.2): only this folder and the tests read the ground truth in `data/synthetic/*/ground_truth/`; the app never does.

**Run:** `make eval` from the repo root (or, from `backend/`, `python ../evaluation/run_eval.py`). Writes `reports/<date>-baseline.{md,json}`; exit code 1 if any disclosure is found.

| Part | What it does |
|---|---|
| `harness/stack.py` | Builds the system under test with the real ingestion job over every corpus file. Held scans are re-submitted as their hand transcription — a declared stand-in for Document AI + reviewer confirmation |
| `slots_v1.json` | Stand-in for the orchestrator's intent + slots (Gemini later), written from question wording only. Measures retrieval given a correct intent |
| `harness/suites.py` | Retrieval (Recall@5/10, P@5, MRR, NDCG@10, ladder-level accuracy) · conflicts A–G via the pre-send check · leakage matrix (8 paths × 8 officers, oracle `access_matrix.csv`) · touchpoint scenarios that need no screens |
| `harness/metrics.py` | Metric definitions |

**Not measured yet (reported as such):** answer status, faithfulness / RAGAS, citation correctness of generated text (need Gemini); OCR accuracy (needs Document AI); conflict types B, D, G; 11 touchpoints that need the sandbox screens (P8).

All numbers are on SYNTHETIC mock corpus v1 with uncalibrated test thresholds and a keyword stand-in for Vertex AI Search. They are a baseline for comparison, not a result to quote as system performance.
