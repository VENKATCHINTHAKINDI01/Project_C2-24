# Evaluation report — 2026-11-04T07:18:13+00:00

**SYNTHETIC mock corpus v1. Baseline on the reference stack, not on GCP.** L2 is a keyword stand-in; thresholds are uncalibrated test values; scanned pages are indexed from hand transcriptions standing in for Document AI + reviewer confirmation; type-C rules are `mock` (testing only).

- Indexed: 28 documents · from transcription: D01, D02, D09, D11, D13, D15, D22 · not indexed: D16
- Slots: slots_v1 (2026-11-04) · ladder config: {'l2_top_k': 10, 'l2_min_score': 1.0, 'l3_max_hops': 2, '_note': 'test values, NOT calibrated (plan §3.2 thresholds still open)'}

## Compared with `2026-11-04-baseline.json`

| Metric | Before | Now |
|---|---:|---:|
| leakage disclosures | 0 | 0 |
| leakage checks | 1062 | 1126 |
| recall@5 | 0.531 | 0.706 |
| recall@10 | 0.561 | 0.754 |
| precision@5 | 0.232 | 0.295 |
| mrr | 0.684 | 0.833 |
| ndcg@10 | 0.550 | 0.711 |
| ladder-level accuracy | 0.579 | 0.684 |
| conflicts A/C/E/F precision | 1.000 | 1.000 |
| conflicts A/C/E/F recall | 0.714 | 0.857 |
| clean-control false flags | 0 | 0 |
| touchpoints passed | 4 | 5 |

## Leakage (pass bar: zero)

**0 disclosures in 1126 checks — PASS**

| Path | Checks | Disclosures |
|---|---:|---:|
| question → retrieved set | 208 | 0 |
| question → evidence package | 208 | 0 |
| file check → pre-send evidence | 11 | 0 |
| exact ID + graph | 224 | 0 |
| keyword (L2) by subject | 224 | 0 |
| count / list-all (L1) | 8 | 0 |
| reference lookup (existence) | 232 | 0 |
| pre-send report | 11 | 0 |

## Retrieval (golden questions)

| Metric | Value |
|---|---:|
| answerable_questions | 19 |
| recall@5 | 0.706 |
| recall@10 | 0.754 |
| precision@5 | 0.295 |
| mrr | 0.833 |
| ndcg@10 | 0.711 |
| full_recall_questions | 11 |
| ladder_level_accuracy | 0.684 |
| ladder_level_questions | 19 |
| no_answer_questions | 5 |
| no_answer_with_forbidden_docs | 0 |
| no_answer_retrieved_nothing | 0 |
| answer_status_accuracy | not measurable yet — needs Gemini generation (GCP) |

| Q | User | Intent | Level (exp → got) | Recall@10 | Missing | Note |
|---|---|---|---|---:|---|---|
| Q01 | U01 | precedent_lookup | L2 → L2 | 1.000 | — |  |
| Q02 | U02 | precedent_lookup | L2 → L2 | 1.000 | — |  |
| Q03 | U01 | current_rule | L1 → L1 | 0.500 | D05 |  |
| Q04 | U07 | current_rule | L1+L3 → L1 | 1.000 | — |  |
| Q05 | U03 | document_status | L0+L3 → L0+L3 | 1.000 | — |  |
| Q06 | U03 | current_rule | L1 → L1 | 0.500 | D16 |  |
| Q07 | U01 | file_check | L0+L1+L3 → L3 | 0.500 | D09, D11, D26 | draft D27 |
| Q08 | U03 | file_check | L0+L3 → L0+L3 | 0.333 | D14, D25 | draft D28 |
| Q09 | U01 | file_check | L0+L3 → L0+L3 | 0.500 | D06 | draft D29 |
| Q10 | U01 | precedent_lookup | — → L2 | — | — |  |
| Q11 | U01 | decision_history | L1 → L1 | 1.000 | — |  |
| Q12 | U03 | precedent_lookup | — → L2 | — | — |  |
| Q13 | U02 | precedent_lookup | L2 → L2 | 1.000 | — |  |
| Q14 | U05 | precedent_lookup | — → L2 | — | — |  |
| Q15 | U06 | precedent_lookup | L2 → L2 | 1.000 | — |  |
| Q16 | U07 | precedent_lookup | — → L2 | — | — |  |
| Q17 | U01 | clause_lookup | L0 → L0 | 1.000 | — |  |
| Q18 | U01 | clause_lookup | L0 → L0 | 0.500 | D04 |  |
| Q19 | U03 | precedent_lookup | L2 → — | 0.000 | D14, D16 |  |
| Q20 | U01 | current_rule | L1+L3 → L1 | 1.000 | — |  |
| Q21 | U01 | current_rule | L3 → L1 | 0.500 | D04 |  |
| Q22 | U03 | precedent_lookup | L0 → L2 | 1.000 | — |  |
| Q23 | U01 | precedent_lookup | — → — | — | — |  |
| Q24 | U02 | current_rule | L1 → L1 | 1.000 | — |  |

## Conflicts (pre-send, touchpoint 11)

Deterministic types A/C/E/F: TP 6 · FP 0 · FN 1 · precision 1.000 · recall 0.857 · F1 0.923. Clean controls: 0 false flags. with the mock rule file (ADR-0010) no control can be 'clear' — 'review_needed' is the correct outcome.

| Type | TP | FP | FN | Precision | Recall | Status |
|---|---:|---:|---:|---:|---:|---|
| A | 1 | 0 | 0 | 1.000 | 1.000 | implemented |
| B | 0 | 0 | 1 | — | 0.000 | needs grounded Gemini judgment (GCP) — not implemented yet |
| C | 3 | 0 | 0 | 1.000 | 1.000 | implemented |
| D | 0 | 0 | 2 | — | 0.000 | needs grounded Gemini judgment (GCP) — not implemented yet |
| E | 1 | 0 | 0 | 1.000 | 1.000 | implemented |
| F | 1 | 0 | 1 | 1.000 | 0.500 | implemented |
| G | 0 | 0 | 1 | — | 0.000 | needs grounded Gemini judgment (GCP) — not implemented yet |

| Draft | User | Outcome | Expected | Flagged | Missed | False | Status unconfirmed |
|---|---|---|---|---|---|---|---|
| D27 | U01 | conflicts_found | A,B,C,D,E,F | A,C,E | B,D,F | — | — |
| D28 | U03 | conflicts_found | C,D,G | C | D,G | — | D13 |
| D29 | U01 | conflicts_found | C,F | C,F | — | — | — |
| D19 (control) | U01 | review_needed | — | — | — | — | D04 |
| D24 (control) | U03 | review_needed | — | — | — | — | D13 |
| D25 (control) | U06 | review_needed | — | — | — | — | — |

## Touchpoint scenarios

6 of 17 run here, 5 passed; the rest need the sandbox screen flow (P8).

| Scenario | Touchpoint | Result |
|---|---|---|
| TP02-a | Receipt inbox | not run — needs the sandbox screen flow (P8) |
| TP02-b | Receipt inbox | not run — needs the sandbox screen flow (P8) |
| TP03 | Put in a file | not run — needs the sandbox screen flow (P8) |
| TP04 | Received letters (other dept) | not run — needs the sandbox screen flow (P8) |
| TP06 | Writing a note (Yellow Note) | not run — needs the sandbox screen flow (P8) |
| TP07 | Referencing in a note | not run — needs the sandbox screen flow (P8) |
| TP08 | Catching up on a long file | not run — needs the sandbox screen flow (P8) |
| TP09 | Link file | not run — needs the sandbox screen flow (P8) |
| TP10 | Local reference | not run — needs the sandbox screen flow (P8) |
| TP11-a | Before Send | FAIL |
| TP11-b | Before Send | PASS |
| TP11-c | Before Send | PASS |
| TP13 | Senior opens a file | not run — needs the sandbox screen flow (P8) |
| TP14 | Draft (DFA) | not run — needs the sandbox screen flow (P8) |
| TP15-a | Advance search | PASS |
| TP15-b | Advance search | PASS |
| TP20 | Search privilege respected | PASS |
