# Evaluation harness

Independent of `backend/app/` (CLAUDE.md §9.2): only this folder and the tests read the ground truth in `data/synthetic/*/ground_truth/`; the app never does.

**Run:** `make eval` from the repo root (or, from `backend/`, `python ../evaluation/run_eval.py`). Writes `reports/<date>-baseline.{md,json}`; exit code 1 if any disclosure is found.

| Part | What it does |
|---|---|
| `harness/stack.py` | Builds the system under test with the real ingestion job over every corpus file. Held scans are re-submitted as their hand transcription — a declared stand-in for Document AI + reviewer confirmation |
| `slots_v1.json` | Stand-in for the orchestrator's intent + slots (Gemini later), written from question wording only. Measures retrieval given a correct intent |
| `harness/suites.py` | Retrieval (Recall@5/10, P@5, MRR, NDCG@10, ladder-level accuracy) · conflicts A–G via the pre-send check · leakage matrix (8 paths × 8 officers, oracle `access_matrix.csv`) · touchpoint scenarios that need no screens |
| `harness/metrics.py` | Metric definitions |

**RAG quality (ADR-0050):** `rag_samples.py` (backend env) scores citation correctness / completeness and context precision / recall by record with no judge, and writes the samples; `ragas_score.py` scores them with RAGAS 0.4.4 and a Gemini judge in its own throwaway environment (`uv run --no-project --with ragas==0.4.4 --with google-genai --with jsonref python evaluation/ragas_score.py <samples.jsonl> [--live]`; billed with `--live`, cached in `.ragas_cache/`).

**Also here:** `harness/sandbox_flow.py` runs the touchpoint scenarios over HTTP against a fresh sandbox, as the screens call them. The scripts at the top of this folder (`ask_golden.py`, `leakage_v2.py`, `presend_v2.py`, `noting_live.py`, `ocr_scans.py`, `cloud_ladder_check.py`) are separate runs against the v2 corpus or live services; each one says in its docstring what it needs.

To compare with a saved run, use `python ../evaluation/run_eval.py --label <name> --compare ../evaluation/reports/<run>.json`.

All numbers are on the SYNTHETIC corpus, with uncalibrated test thresholds; the default run uses a keyword stand-in for L2. They are a baseline for comparison, not a result to quote as system performance. Reports are dated and never edited after they are written.
