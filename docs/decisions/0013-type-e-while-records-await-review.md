# ADR-0013: Type E while records await review

- **Date:** 2026-11-04
- **Status:** Accepted (owner: "fix the bugs", on the proposal in the checkpoint review)
- **Plan section:** §6.2 (type E), §5.3 (extraction-confidence gate), §5.6 (no hints about hidden records)

## Context
The checkpoint evaluation without the OCR stand-in (`evaluation/reports/2026-11-04-checkpoint-review.md`)
showed the pre-send check telling the Works SO that the 2023 Works circular was "not found in the
records available to you". This happened on D28 and on the clean test draft D24. The circular exists
and he may see it. It is a photo that waits in the review queue until Document AI reads it, so it is
not indexed. Until OCR is available, every officer would see this false statement.

A held scan carries only its source-system tags (department, section, classification, file number;
ADR-0011). Its number, date and subject are unknown until it is read.

## Decision
When a cited order is not found, and the officer may see (full `check()`) at least one held record
of the cited order's department, the type E flag:
- is kept, but marked **uncertain**;
- says the order "was not found among your indexed records … some records of this department that
  you may see are still awaiting review … it may be among them";
- puts the citation in `awaiting_review` on the pre-send report and the approval brief.

The held record is never named. Held records the officer may not see are ignored. The pipeline
keeps `IngestionStores.awaiting` (source doc id → tags) and removes a record once it is indexed.

## Alternatives considered
| Option | Why not |
|---|---|
| Remove the E flag and list the citation only as "awaiting review" | Department is the only signal, so a truly missing order is indistinguishable. D27's planted non-existent G.O.Ms.104/2026 would lose its E flag while the Finance scans wait (TP11 test caught this) |
| Match the held record by number or year | Unknown before OCR; mock filenames encode IDs but real e-Office filenames don't |
| Leave as is | A false, definite statement to the officer |

## Consequences
- The wording is now true. The evaluation numbers do not change, because the harness counts
  uncertain flags as flags. Without OCR, D24 still shows one (uncertain) E.
- While a department has held scans that an officer may see, every missing-authority flag on that
  department's orders is uncertain, including truly missing ones like 104/2026. It is still flagged.
- The real fix is Document AI plus review. Once scans are indexed, `awaiting` empties and flags are
  certain again.
- Revisit if the e-Office supplies per-document metadata (letter number or date) for uploads.

## Mentor input (if any)
None.
