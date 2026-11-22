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
│   ├── l2_validation_dataset.json  # L2 hybrid search calibration ground truth
│   └── semantic_cache_pairs.json   # Semantic cache reworded pairs
├── reports/                        # Immutable, dated Markdown and JSON run reports
├── benchmark_suite.py              # Automated latency, recall, QPS & fan-out benchmark suite
├── run_eval.py                     # Main CLI entrypoint for regression evaluation (`make eval`)
├── ask_golden.py                   # Golden question evaluation against live or recorded Gemini
├── calibrate_l2.py                 # Threshold calibration script for Rung L2 hybrid search
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

### 4. Cloud Infrastructure & Calibration
| Script | Command | Purpose |
| :--- | :--- | :--- |
| `cloud_ladder_check.py` | `uv run python evaluation/cloud_ladder_check.py` | Verifies that Cloud BigQuery and Cloud SQL/Spanner produce identical candidate sets to the in-memory reference stack. |
| `calibrate_l2.py` | `uv run python evaluation/calibrate_l2.py` | Tunes the cosine similarity threshold for L2 hybrid search against known-item validation data. |
| `semantic_cache_calibrate.py` | `uv run python evaluation/semantic_cache_calibrate.py` | Calibrates similarity thresholds for scoped answer cache hits. |

---

## Guidelines for Reports

All evaluation outputs are saved to `evaluation/reports/` with ISO timestamps (e.g. `reports/YYYY-MM-DD-label.md`). Reports are immutable historical artifacts: once committed, they are never modified.
