# Checkpoint review — 4 Nov 2026

**SYNTHETIC mock corpus v1 · reference stack (not GCP) · keyword stand-in for Vertex AI Search ·
uncalibrated test thresholds · type-C rules are mock.** This is a checkpoint before new building.
It does not claim results on real department data.

Runs used (both written by `evaluation/run_eval.py`, nothing overwritten):

| Report | What it measures |
|---|---|
| `2026-11-04-baseline` | first harness run, before any fixes |
| `2026-11-04-checkpoint` | today's stack, **with** the OCR stand-in (scans indexed from hand transcriptions) |
| `2026-11-04-checkpoint-no-ocr` | today's stack, **without** the stand-in: scans stay in review, as the app runs today |

Reproduce:

```
make eval                                   # or the two lines below
cd backend && uv run python ../evaluation/run_eval.py --label checkpoint --compare ../evaluation/reports/2026-11-04-baseline.json
cd backend && uv run python ../evaluation/run_eval.py --label checkpoint-no-ocr --no-ocr-stand-in --compare ../evaluation/reports/2026-11-04-checkpoint.json
```

## 1. Headline

| Metric | Baseline | Checkpoint (OCR stand-in) | Checkpoint (no OCR) |
|---|---:|---:|---:|
| Leakage disclosures / checks | 0 / — | **0 / 1142** | **0 / 1014** |
| Recall@5 | — | 0.706 | 0.500 |
| Recall@10 | — | 0.754 | 0.544 |
| Precision@5 | — | 0.295 | 0.211 |
| MRR | — | 0.833 | 0.632 |
| NDCG@10 | — | 0.714 | 0.521 |
| Ladder-level accuracy | — | 0.684 | 0.579 |
| Questions with full recall (of 19) | 7 | 11 | 7 |
| Conflicts A/C/E/F precision | 1.000 | 1.000 | **0.778** |
| Conflicts A/C/E/F recall | 0.714 | 1.000 | 1.000 |
| Clean-control false flags | 0 | 0 | **1** |
| Touchpoints passed / run (of 17) | 4 / 6 | 13 / 13 | 11 / 13 |

(Baseline retrieval values are in `2026-11-04-baseline.md`; the compare tables in each report
give every before/after pair.)

## 2. Findings, most important first

1. **Without OCR, a held scan causes false type-E flags.** D13 (2023 Works circular) is a scan
   awaiting Document AI, so it sits in the review queue. The pre-send check then reports its
   citation as "not found in the records available to you" (type E) on D28, and on the **clean
   control D24**. The record does exist and the officer may see it; it is just not indexed yet.
   This is the only new false positive, and it is what the app would show today.
   *Proposed fix (not built):* when the officer can see documents of the cited department that are
   held for review, mark the E flag **uncertain** with "a record of this department is awaiting
   review; this citation may be among them", without naming the held record.
2. **Leakage holds on both runs: 0 disclosures** over 8 paths × 8 officers (1142 / 1014 checks),
   including existence, count, keyword, graph and pre-send paths.
3. **The OCR stand-in is worth about 0.2 recall.** 8 of 29 documents are scans (D01, D02, D09, D11,
   D13, D15, D16, D22). Retrieval numbers with the stand-in describe the stack *after* Document AI
   and a reviewer have confirmed the text — not today's app.
4. **Deterministic conflict types are complete on this corpus (with the stand-in):** A, C, E, F at
   precision 1.0 / recall 1.0 (7 of 7 flags). C runs on mock rules and is shown as uncertain with a
   caveat. B, D, G (5 expected flags on D27/D28) wait for Gemini.

## 3. Retrieval misses (with the OCR stand-in) and likely causes

| Q | Missing | Likely cause | Fix belongs to |
|---|---|---|---|
| Q03 current transfer guidelines | D05 | L1 returns the order (D04) but not its clarification; L3 not reached from L1 | ladder (L1 → L3 for CLARIFIES) |
| Q21 station-period computation | D04 | same, in reverse: L1 finds the clarification D05, not the order it clarifies | ladder |
| Q18 para 2(v) of 88/2022 | D04 | L0 finds the superseded order but does not add its superseder (status tool *does* say "superseded"; TP10 expects the current provision too) | ladder (L0 → L3 for SUPERSEDED_BY) |
| Q06 emergency work Rs.1.30 cr | D16 | L1 returns the 2023 circular (D13) instead of its amendment D16 | ladder / status-aware L1 |
| Q19 (Telugu question) | D14, D16 | keyword stand-in has no Telugu vocabulary overlap; nothing retrieved | Vertex AI Search embeddings (GCP) |
| Q07, Q08, Q09 file checks | D09, D11, D26 · D14, D25 · D06 | mostly documents that are evidence only for B/D/G checks | Gemini (GCP) |
| Q22 drain cost break-up | — (level only) | right document first, but routed L2 instead of L0 | intent classifier stand-in (`slots_v1.json`) |

No-answer questions (5): none returned a forbidden document, but none returned *nothing* either —
the keyword stand-in always finds something. Answer-status accuracy needs Gemini and is not
measured.

## 4. Touchpoints

Run here: TP02-a/b, TP03, TP04, TP08, TP09, TP11-a/b/c, TP13, TP15-a/b, TP20 — all pass with the
stand-in. Without it, **TP08 (file so far) and TP13 (approval brief) fail**: both need D13's text,
which is in review. That is expected and the screens say the record is awaiting review.

Not run: TP06 (Yellow Note), TP07 (referencing), TP14 (DFA) — drafting; TP10 (local reference) —
the harness has no handler yet. TP10's answer key expects the current provision (31/2025 para 2(v))
to be offered; the status lookup today says "superseded by 31/2025" but deliberately does not say
"current" (owner decision: keep TP10 and TP11 as they are).

## 5. Where these numbers may be generous

- Intent and slots come from `slots_v1.json`, a hand-filled stand-in for the intent classifier;
  real classification errors are not measured.
- Thresholds (10 / 1.0 / 2) were set on this same corpus; they are labelled uncalibrated.
- One corpus, one author: the same person wrote the documents and the answer keys.
- Touchpoint checks test the deterministic outputs (documents, flags, notices), not screens or
  wording.
- Type-C precision is measured against mock authority rules.

## 6. Not measured yet

RAG faithfulness / citation correctness (needs Gemini) · OCR accuracy and the confidence gate on
real scans (needs Document AI) · prompt-injection suite end to end with a model · cache
invalidation under real permission changes · B / D / G conflict types · latency and cost.

## 7. Checks run for this checkpoint

Backend: ruff ✅ · format ✅ · mypy strict (108 files) ✅ · `pytest -q` 1156 passed ✅ · HTTP sweep over
every endpoint × officer: 0 disclosures ✅. Frontend: `tsc` ✅ · Vitest 13 passed ✅ · build ✅ ·
`npm audit` 0 ✅.
