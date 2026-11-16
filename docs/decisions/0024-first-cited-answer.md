# ADR-0024 — First cited answer: the model writes, the citation check decides

- **Date:** 14 Nov 2026 · **Status:** Accepted for the sandbox (prompt wording and sizes [To confirm]) · **Plan:** §3.3, §5.5, §8.1–§8.3 · **Milestone:** M4

## Context
Retrieval, the evidence package and the citation verifier existed but nothing joined them: no path produced an
answer in words. M4 asks for "Has this been decided before?" answered with cited precedent from the evidence
package.

## Decision
- **One path (`app/agents/answer.py`, `POST /assist/ask`):** question → scoped ladder (plain-language search)
  → up to 6 records, 2 passages each (the passages sharing most words with the question) → evidence package
  (every passage re-checked for this officer) → model → citation verifier → response.
- **The model sees only the package**, fenced as untrusted data, with each record's status on the as-of date.
  Prompt `answer_cited.v1`: use only the passages; every statement cites passage ids and gives an exact quote;
  an empty list is a correct answer; superseded records must be called superseded; no advice.
- **The model's text is never shown as is.** A statement is shown only if the verifier confirms it: it cites
  passages that are in the package and still authorised, and its quote and every number or date are found in
  the cited passage. An invented id, an invented quote or a missing citation removes the statement. The
  response reports how many were removed, never their text.
- **No evidence → the model is not asked** and the defined no-answer is returned.
- **Model off or failing → `not_run`:** the officer gets the authorised records found and a plain message. No
  silent fallback to an uncited answer. The failover chain of ADR-0021 applies; the response names the engine.
- **Audit:** request id, officer, outcome and record ids only — never the question or the answer text.

## Consequences / limits
- The verifier proves a quote is in the cited passage and numbers match. It does not prove the sentence means
  what the quote means. Meaning is left to the officer, who sees the quote beside the statement.
- Passage choice is by word overlap, a stand-in for Vertex AI Search extractive segments (plan §3.2 L2).
- Page and paragraph numbers are not yet carried into citations (the sandbox text store has no page map).
- Only the plain-language search path is wired. Intent routing (status, supersession chain, clause lookup) and
  LangGraph orchestration (M6) come later; this is the single-turn base they will call.
- Quality on real questions is unmeasured until the live run on the golden questions
  (`evaluation/ask_golden.py --live`, owner, billed).

## Addendum — 15 Nov 2026: answer quality after the first live run
First live run on the 24 golden questions (owner, `2026-11-15-ask-golden-cloud.md`): 11 of 19 answered with a
checked citation, 7 citing an expected record, all 5 no-answer questions kept, 0 forbidden records, 10 statements
removed by the citation check. Causes found and changed (no answer key, threshold or verifier rule was edited):
- **Only plain-language search fed the package.** Records the question names now come first, found
  deterministically within the officer's scope: order references (`reference_candidates`, every department
  reading of an unnamed one, each looked up at L0), the papers of an e-File number it names, and what those
  records cite or what replaced them (L3, two hops). Search results fill the rest (up to 8 records).
- **A named record could get no passage** when its wording differed from the question ("para 2(v) of GO Ms
  88/2022"). A paragraph marker or number from the question found verbatim now counts three times, and a named
  record gets one more window and its opening window if nothing else matches.
- **As-of questions** ("as on 01-01-2021") are answered for that date: statuses in the package are computed for
  it and the prompt says so.
- **Saved answers could never replay**: the prompt carried request-bound evidence IDs. The model now sees
  EV-1, EV-2 … (mapped back before the citation check), so the same evidence gives the same prompt.
- **Statements removed for reformatted numbers** ("08-06-2022" written as "June 8, 2022"): prompt
  `answer_cited.v2` asks for numbers and dates copied character for character, with examples; count/list
  questions are answered item by item with citations.
- **Held scans:** the evaluation now confirms held scans through the review endpoints with a simulated reviewer
  and the recorded OCR unchanged, as the main harness already did (labelled in the report).
Effect on the evidence package (no model call): an expected record is in the package for 18 of 19 answerable
questions (was 13). The miss is the Telugu question, which keyword search cannot match to English text: it needs
the L2 embeddings. Answer quality must be measured again live (prompt v2 changes every request).

## Addendum 2 — 15 Nov 2026: after live run 2
Live run 2 (owner, prompt v2, `2026-11-15-ask-golden-v2.md`): 15 of 19 answered with a checked citation, 12 on
key, 5/5 no-answers kept, 0 forbidden records, 10 statements removed. Tracing the 10 removals with the saved
answers (no new model calls):
- **9 named the cited order by its own number or date** ("G.O.Ms.No.27, dated 06-08-2024 … Government only")
  while quoting a line of its body, which does not repeat the number. The citation check now also accepts the
  numbers that identify the cited record itself, taken from the evidence package's own fields: the digits of its
  canonical ID and its issue / effective dates (plan §7.2 fields; `issue_date` added to the evidence item, not to
  the prompt). Any other number is still checked against the cited text, and the quote must still be found
  verbatim. This is a change to citation logic (CLAUDE.md §9.5): the v1 harness is unchanged (0 / 1,142,
  recall@10 0.754, MRR 0.833, A/C/E/F 1.000) and a test pins that another order's number is still rejected.
- **1 quoted a date the source breaks across a line** ("18-09-\n2026"): the comparison now drops spaces around
  a hyphen, as the B/G excerpt check already did.
- **Status questions are answered from the order records.** "Is X still valid?" got no answer when the
  passages did not say so. The temporal engine's status on the as-of date (and the order that replaced it) is
  now given as a statement marked `source: "order records"`, for orders the question names and the officer may
  see, and only when the coverage rule lets the status be reported to that officer (owner, 3 Nov 2026). No model
  is involved, so it is given even when the model is off or failing.
- **Named orders are looked up by L0 exact ID** (base ID finds the dated version: Circular Memo
  USD01-WRKS0/9/2023 is indexed as …-D20230711, and the earlier re-check by full ID missed it).
Re-scored on the same saved answers (`2026-11-15-ask-golden-v2-rescored.md`): 16 of 19 answered with a checked
citation, 15 on key, 0 statements removed, 0 forbidden records; Q05's prompt changed (its order is now in the
package), so it needs one new live call.
