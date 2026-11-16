# Checkpoint review — 6 Nov 2026

**SYNTHETIC mock corpus v1 · reference stack (not GCP) · keyword stand-in for Vertex AI Search ·
uncalibrated test thresholds · type-C rules are mock.** Second checkpoint, after touchpoints 6, 7,
10 and 14 were built and the held-scan type-E fix (ADR-0013). Adds the **opposite scenarios**: for
each touchpoint, the case where the right output is the reverse.

| Report | What it measures |
|---|---|
| `2026-11-06-checkpoint` | today's stack **with** the OCR stand-in, compared with `2026-11-04-checkpoint` |
| `2026-11-06-checkpoint-no-ocr` | **without** it (scans stay in review, as the app runs today), compared with `2026-11-04-checkpoint-no-ocr` |
| opposite scenarios (in both reports) | 16 cases run through the sandbox HTTP API (`ground_truth/opposite_scenarios.json`, draft — owner review) |

Reproduce:

```
cd backend && uv run python ../evaluation/run_eval.py --label checkpoint --compare ../evaluation/reports/2026-11-04-checkpoint.json
cd backend && uv run python ../evaluation/run_eval.py --label checkpoint-no-ocr --no-ocr-stand-in --compare ../evaluation/reports/2026-11-04-checkpoint-no-ocr.json
```
(On a re-run the reports save as `…-checkpoint-2`; nothing is overwritten.)

## 1. Headline

| Metric | 4 Nov (stand-in) | 6 Nov (stand-in) | 4 Nov (no OCR) | 6 Nov (no OCR) |
|---|---:|---:|---:|---:|
| Leakage disclosures / checks | 0 / 1142 | **0 / 1142** | 0 / 1014 | **0 / 1014** |
| Recall@10 · MRR | 0.754 · 0.833 | 0.754 · 0.833 | 0.544 · 0.632 | 0.544 · 0.632 |
| Ladder-level accuracy | 0.684 | 0.684 | 0.579 | 0.579 |
| Conflicts A/C/E/F precision · recall | 1.0 · 1.0 | 1.0 · 1.0 | 0.778 · 1.0 | 0.778 · 1.0 |
| Clean-control false flags | 0 | 0 | 1 | 1 (now uncertain, see §3) |
| Touchpoint scenarios run · passed (of 17) | 13 · 13 | **17 · 17** | 13 · 11 | **17 · 13** |
| Opposite scenarios passed | — | **16 / 16** | — | **16 / 16** |

Retrieval and conflict numbers are unchanged: the four new touchpoints and the type-E fix did not
move them. Every touchpoint scenario now runs.

## 2. Opposite scenarios — 16 / 16

Written before the first run, each from a named corpus fact (access matrix, conflicts.json, seed).
Run through the sandbox API as the officer sees it.

| Kind | Scenarios | What was checked |
|---|---|---|
| No access → same answer as a record that does not exist | OPP-02 (receipt), OPP-06a (first-cut), OPP-07c (note reference), OPP-08 (file so far), OPP-10b (hidden Standing Order vs a non-existent one) | status code and body identical to the unknown-record call |
| Lower clearance on the same file | OPP-13 (Estt.I SO's brief has no D20, which the Secretary's has), OPP-09 (Estt.I SO's links: D17–D19, never Works / Vigilance / D20), OPP-15 (Estt.I SO searching "that 2023 drain case" gets no Works record) | named documents |
| Nothing to find | OPP-07a (unrelated request → no suggestion), OPP-07b (date before the first note → none), OPP-04 (Works SO gets no notice when 31/2025 arrives) | empty lists |
| Nothing wrong | OPP-11a (D19, 2025 approval inside its window → no flag), OPP-11b (D24 clean control → no *certain* flag), OPP-06b (Works first-cut: no "in place of", no A, no Estt.I record), OPP-14 (outsourcing DFA: G.O.Rt.1184 listed, transfer orders not, nothing "in place of") | flags, list contents |
| An order in force | OPP-10a (31/2025 para 2(v): not superseded, no successor, its own paragraph quoted) | status fields |

**One expectation was revised after the first run, and is marked in the file (`revised`).** OPP-11a
first also expected the outcome "clear". The run returned no flags but "review needed", for two
reasons that are owner decisions, not faults: the officer's records cannot confirm 31/2025 is still
current (coverage rule, 3 Nov), and the type-C rules are mock, so the approving authority is never
confirmed. Under those rules "clear" is not reachable; the opposite of TP11-a is "no conflict
flagged", which holds. A harness self-test (`test_opposite_harness.py`) shows every kind of check
fails on a response that breaks it, so 16 / 16 is not a harness that cannot fail.

## 3. Without OCR (the app as it runs today)

- **4 touchpoints fail: TP06, TP08, TP13, TP14** — each needs a scan's text (D09, D11, D13). The
  screens say records are awaiting review.
- **Clean control D24 still shows one flag, now honest:** type E on the 2023 Works circular (a held
  scan) is uncertain and says the order may be awaiting review (ADR-0013). The harness counts
  uncertain flags as flags, so precision stays 0.778.
- **Softened while scans wait:** D27's E on the non-existent 104/2026 is uncertain too (Finance
  scans are held). It is still flagged.
- Retrieval loses about 0.2 recall@10.

## 4. Known gaps (unchanged since 4 Nov unless stated)

- Retrieval misses: L1 does not expand to clarifications / successors on current-rule questions
  (owner: set aside for now); Telugu text with the keyword stand-in; B / D / G evidence.
- No-answer questions still retrieve unrelated documents (none forbidden).
- Drafts (DFA, first-cut note) list canonical IDs, not the printed references.
- TP10 passes with "current version not claimed" — the scenario expects it; the coverage rule
  withholds it (owner decision).
- Not measured: faithfulness / citation correctness of model text, OCR accuracy, B / D / G, prompt
  injection with a model, latency, cost.

## 5. Where these numbers may be generous

Intent slots are hand-filled (`slots_v1.json`); thresholds set on this corpus; one author for
documents, answer keys and the opposite scenarios; scenarios test deterministic outputs, not
wording; type-C precision is against mock rules; opposite scenarios are draft — owner review.

## 6. Checks run

Backend: ruff ✅ · format ✅ · mypy strict (120 files) ✅ · `pytest -q` 1216 passed ✅ (incl. the HTTP
endpoint × officer sweep, 0 disclosures). Frontend: `tsc` ✅ · Vitest 18 passed ✅ · build ✅ ·
`npm audit` 0 ✅.
