# Cloud rungs against the reference — 2026-11-15

Project `use-case-24-project`, region `asia-south1`. 1290 documents, 1669 relations (public orders). Scopes: outsider (public only); FIN01 department-wide; GAD01 section officer.

| Path | Asked | Different |
|---|---:|---:|
| L0 exact (BigQuery) | 453 | 0 |
| L1 filter (BigQuery) | 27 | 0 |
| L3 graph size (Cloud SQL) | 1 | 0 |
| L3 walk, 2 hops (Cloud SQL) | 120 | 0 |
| L2 meaning + keywords, top 10 (BigQuery) | 18 | 0 |

**SAME on every question**

## L2 threshold evidence (proposal only — not applied)

Known-item questions: 40 (twelve words copied from an order; an upper bound). Recall@1 0.45, recall@10 0.88.
Best score — known-item: min 0.743, 10th percentile 0.751, median 0.799; off-domain (10): max 0.561, median 0.507.
Separation found: a threshold of **0.656** sits between the worst off-domain score and the 10th-percentile known-item score. Proposed for `C2_L2_CLOUD_MIN_SCORE`; needs the owner's approval and a check on officers' own wording before use.
