# Evaluation Harness & Benchmark Suite

Independent of `backend/app/` ([CLAUDE.md §9.2](../CLAUDE.md)): only this folder and the tests read the ground truth in `data/synthetic/*/ground_truth/`; the core application never does.

**Primary Commands:**
- Continuous regression harness: `make eval` (runs `run_eval.py` $\to$ writes `reports/<date>-baseline.{md,json}`; exits 1 if any unauthorized disclosure is detected).
- Comprehensive benchmark suite: `uv run python evaluation/benchmark_suite.py` (latency, recall, concurrency, and high-degree fan-out simulation).

---

## Directory Organization & Script Catalog

```
evaluation/
├── harness/                        # Reusable test harness infrastructure
│   ├── stack.py                    # Ingests corpus files and builds evaluation stack
│   ├── suites.py                   # Retrieval, conflict, leakage, and touchpoint suites
│   ├── metrics.py                  # Formal definitions (Recall@K, MRR, NDCG@10, P@K)
│   ├── limits.py                   # Request limiter overrides for burst evaluations
│   ├── opposites.py                # Fail-closed opposite scenario validator
│   └── sandbox_flow.py             # HTTP-level touchpoint flow tests
├── data/                           # Evaluation-specific fixtures and datasets
│   ├── l2_validation_dataset.json  # format example only (not a calibration set)
│   ├── l2_validation_known_item.json  # L2 calibration set (150 known-item queries, public orders)
│   ├── l2_holdout_dataset.json     # family-disjoint L2 holdout (100 queries)
│   ├── l2_calibration.json         # last measured calibration (not active until adopted)
│   ├── l2_*_predictions_*.json     # per-query scores and gate results of a calibrate_l2.py --write run
│   └── semantic_cache_pairs.json   # Semantic cache reworded pairs
├── reports/                        # Immutable, dated Markdown and JSON run reports
├── benchmark_suite.py              # Automated latency, recall, QPS & fan-out benchmark suite
├── run_eval.py                     # Main CLI entrypoint for regression evaluation (`make eval`)
├── ask_golden.py                   # Golden question evaluation against live or recorded Gemini
├── build_l2_validation.py          # L2 calibration set (+ no-answer questions) and its family-disjoint holdout
├── calibrate_l2.py                 # measures the L2 early exit as the ladder runs it; --holdout checks it
├── cloud_ladder_check.py           # Verification script comparing Cloud SQL, Spanner, and BigQuery
├── leakage_v2.py                   # Comprehensive permission leakage matrix across all roles
├── noting_live.py                  # Live noted draft verification against synthetic precedents
├── ocr_scans.py                    # Document AI OCR confidence gating and review probe
├── ocr_telugu_probe.py             # Telugu/English bilingual OCR accuracy probe
├── presend_v2.py                   # 7-type statutory conflict detection evaluation
├── rag_samples.py                  # RAG sample generator for citation & groundedness scoring
├── ragas_score.py                  # RAGAS 0.4.4 LLM-judge groundedness evaluation
├── semantic_cache_calibrate.py     # Embedding threshold calibration for semantic answer cache
└── slots_v1.json                   # Golden intent and slot extraction mappings
```

---

## Script Categories & Usage

### 1. Regression & Benchmarking
| Script | Command | Purpose |
| :--- | :--- | :--- |
| `run_eval.py` | `make eval` | Runs the full evaluation harness over the synthetic corpus; asserts zero disclosure. |
| `benchmark_suite.py` | `uv run python evaluation/benchmark_suite.py` | Measures Recall@K, MRR, NDCG@10, sub-millisecond rung latencies, 5,800+ QPS concurrency, and high-degree graph fan-out bounds (ADR-0063). |

### 2. RAG Quality & Groundedness (ADR-0050)
| Script | Environment | Purpose |
| :--- | :--- | :--- |
| `rag_samples.py` | Backend venv | Extracts cited evidence packages and evaluates citation correctness / completeness offline without an external judge. |
| `ragas_score.py` | Throwaway venv | Evaluates faithfulness and answer relevancy using RAGAS 0.4.4 and Gemini in `asia-south1` (caching judge responses in `.ragas_cache/`). |

### 3. Security & Access Control
| Script | Command | Purpose |
| :--- | :--- | :--- |
| `leakage_v2.py` | `uv run python evaluation/leakage_v2.py --jobs 4` | Evaluates multi-officer access matrices across direct reference, keyword, vector, graph, summary, and count paths. |
| `presend_v2.py` | `uv run python evaluation/presend_v2.py` | Evaluates the 7 conflict types (A–G) during pre-send file dispatch. |
| `conversation_check.py` | `cd backend && uv run python ../evaluation/conversation_check.py [--live]` | ADR-0067: model intent routing (accuracy vs the fixed rules, off-list answers = 0) and the chat answer layout over every golden question (forbidden records = 0, each checked statement shown once). Exit 1 on any critical failure. `--live` is billed. |

### 4. Cloud Infrastructure & Calibration
| Script | Command | Purpose |
| :--- | :--- | :--- |
| `cloud_ladder_check.py` | `uv run python evaluation/cloud_ladder_check.py` | Verifies that Cloud BigQuery and Cloud SQL/Spanner produce identical candidate sets to the in-memory reference stack. |
| `build_l2_validation.py` | `python3 evaluation/build_l2_validation.py --zip <corpus.zip> --filter-bq --out …` · options: `--no-answer K` (questions whose answer is not in the index), `--exclude-families-of <dataset>` (keep clear of another set's order families), `--holdout-of <calibration json>` (the holdout) | Builds the known-item calibration set from public order subjects, or its family-disjoint holdout. |
| `calibrate_l2.py` | `cd backend && uv run python ../evaluation/calibrate_l2.py --backend local\|cloud --margin 0.03 [--write]` · `--holdout <dataset>` checks the saved calibration | Measures the L2 early exit exactly as the ladder runs it (one hit per order, score gap, attribute and graph gates); a threshold qualifies only if the 95% lower bound of its precision clears the target. `--backend cloud` is billed and needs the owner's explicit approval; it refuses invented IDs and never writes a calibration from fewer than 100 queries. |
| `semantic_cache_calibrate.py` | `uv run python evaluation/semantic_cache_calibrate.py` | Calibrates similarity thresholds for scoped answer cache hits. |

---

## Guidelines for Reports

All evaluation outputs are saved to `evaluation/reports/` with ISO timestamps (e.g. `reports/YYYY-MM-DD-label.md`). Reports are immutable historical artifacts: once committed, they are never modified.
