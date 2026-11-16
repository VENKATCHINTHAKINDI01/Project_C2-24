# ADR-0022 — Conflict type D (precedent inconsistency): a deterministic, review-only check

- **Date:** 14 Nov 2026 · **Status:** Accepted for the sandbox (values and wording [To confirm]) · **Plan:** §6.2, §6.4, §11.5 touchpoint 11

## Context
Type D was the last conflict type with no check (0 of 16 on set v2). The plan lists it as "review only". On set v2
more than half of all files share a subject with an earlier file of the same section, so "an earlier file exists"
cannot be the signal. The set's own type D files were also too thin to detect: the earlier file recorded no
disposal, and 4 of the 16 pointed to an earlier file that was not in the set.

## Decision
- **Check (`app/precedent/consistency.py`, in the pre-send check):** raise type D only when (1) earlier e-Files on
  the same matter (same subject line) that the officer may see record a proposed disposal — allow or refuse — in
  their own words, (2) this note proposes the opposite of what MOST of them proposed, and (3) this note does not
  refer to those files. One vote per earlier file (its latest note). Evenly divided earlier files → no flag.
- **Never a verdict:** uncertain, "Review recommended: compare the cases"; it does not say which disposal is right.
- **Authorisation:** candidates come from the scoped L1 filter and each is re-checked; the flag names only files
  the officer may see. No model call.
- **Nothing inferred:** a note with no clear disposal sentence, or with both, gives no flag.
- **Set v2 made detectable (not easier to pass):** clean files and each type D file's earlier file now state the
  section's usual disposal for the subject; the type D file states the opposite. A type D file whose earlier file
  was trimmed is pointed to another earlier file on the same matter, or becomes a clean file when none exists
  (1 case: D 16 → 15, clean 40 → 41, planted 163 → 162).

## Consequences / limits
- "Same matter" is the same subject line; real sections word subjects loosely, so this will miss precedents on
  real data. The upgrade path is the scoped precedent search plus a grounded comparison (Gemini), as for B / G.
- Disposal is read from fixed verbs ("may be allowed / rejected …"). Set v2 writes exactly such sentences, so
  15 of 15 found on it shows the check is wired correctly, not that it would read real notes well.
- A single stray earlier case is not treated as practice (majority rule).
