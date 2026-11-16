# ADR-0030 — Noting agent: the note's text by the model, every line checked

- **Date:** 15 Nov 2026 · **Status:** Accepted for the sandbox (prompt and checks [To confirm] on a live run) ·
  **Plan:** §8.1 Noting Agent, §9.1 checkpoint 2 · **Milestone:** M6

## Context
Touchpoint 6 returned the cited points for a note (orders, their paragraphs, earlier decisions, open points) and
the words "not drafted (needs Gemini)". Plan §8.1: a first-cut noting in sections, every factual line cited.

## Decision
- **Sources, not records, go to the model.** The first-cut's items become numbered sources S1…Sn (orders,
  paragraphs, precedent decisions, open points) — all already authorised for this officer — fenced as data
  (`noting_draft.v1`). A source carrying text addressed to an AI is marked and can never be cited (ADR-0029).
- **Sections** Background, Precedent, Applicable provisions, Analysis, Potential issues, Proposal, in that order,
  at most 6 lines each. Subject and References are written by code.
- **Every line is checked, deterministically**, and removed if: it cites nothing or a source that does not
  exist; a number or date in it is not in its cited sources; a "Potential issues" line rests on no open point; a
  "Proposal" line states a decision ("is approved / sanctioned / rejected / ordered") — the proposal is a
  submission for the officer. Lines under an unknown heading are removed. The count of removed lines is shown,
  never their text.
- **A draft, watermarked.** "AI FIRST-CUT — draft for the officer; not a note until signed." It enters the file
  only as a Yellow Note on the officer's click (unchanged).
- Model off or failing → the points alone, as before. The conversation's "draft the noting using that precedent"
  uses the same function.

## Consequences / limits
- The check proves sources and numbers, not that a line's meaning follows from them; the officer sees each
  line's references next to it.
- Quality is unmeasured until `evaluation/noting_live.py --live` (4 files, at most 4 Gemini calls).

## Addendum, 15 Nov 2026 — live run 1 and v2
- **Live run 1** (`noting_live.py --live`, 3 Gemini calls): 4 files, 3 notes, 50 lines kept, 1 removed, 0
  forbidden records named. Reading the kept lines, 2 of 50 stated the file's request but cited an order paragraph
  (2.v) — the citation check passed because the paragraph existed and the line had no numbers.
- **v2 (`noting_draft.v2`):** the file's subject is source S1 ("subject"), so a line about the request has a
  true source to cite; and a kept line must share at least half of its content words with its cited sources
  (`MIN_SUPPORT = 0.5`, stop-words ignored). Replayed on run 1's 50 lines, only the 2 misattributed lines fall
  below it. Still not a proof of meaning — a cheap, deterministic catch for the misattribution seen.
- **Why no note is now told apart:** `DraftNote.reason` — `no_sources` (nothing to write from; the model is not
  asked — file 2881930 for U01), `engine_off`, `engine_down`, `all_removed`. Run 1 showed 2881930 as "needs
  Gemini", which was wrong.
- v1 prompt kept for the saved answers of run 1; v2 needs its own live run (≤4 calls).
