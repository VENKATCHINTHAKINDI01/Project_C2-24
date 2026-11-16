# ADR-0018: OCR review screen: who may confirm OCR text, and how

- **Date:** 2026-11-11
- **Status:** Accepted for the sandbox (owner request, 11 Nov 2026). Who may confirm OCR text in the
  department is **[To confirm]**
- **Plan section:** §4.2 (confidence gate, human review), §9.1 checkpoint 5, §11 (sandbox); CLAUDE.md §4.7, §8; ADR-0014 rule 4, ADR-0016, ADR-0017

## Context
OCR'd scans wait in the review queue, because the confidence gate stays uncalibrated (owner
decision, 11 Nov 2026). Until now, nobody could confirm them except from code. A scan whose OCR
misread a key field (D16: the Telugu marker ఆర్.సి.నెం. read as "5.2.3.") can only be fixed by a
person.

## Decision
1. **A sandbox screen "OCR review".** It shows the scan beside the OCR text (whole document, native
   pages plus OCR pages, as it would be indexed), per-page confidence and the languages detected. The
   reviewer can:
   - **confirm** the text;
   - **confirm a corrected text**;
   - **reject** it ("needs re-scan").
   A reason is required, and the reviewer, time, reason and decision are recorded on the review item
   (CLAUDE.md §8).
2. **Who may review a scan: any officer who may open that file** (the same `can_access` check as
   every other path). The queue lists only those scans. A hidden item answers exactly like an unknown
   one (404, the ADR-0016 guiding message). The scan itself is served only to such an officer
   (ADR-0014 rule 4). Whether the department wants a narrower group (e.g. the dealing section, or a
   minimum rank) is **[To confirm]**. A narrower rule can be added as a config check without changing
   the screen.
3. **Confirming does not index directly.** The file runs through the pipeline again
   (`confirm_extraction`). It is indexed only if every other check passes; otherwise it stays held
   and the screen says why (e.g. an unresolved reference). It is indexed under the scan's own
   version, so preview serves the scan.
4. **The sandbox replays recorded Document AI output** (`sandbox.yaml: ocr.provider: recorded`,
   model pinned per ADR-0017). No GCP calls are made, and only synthetic scans are used.

## Alternatives
| Option | Why not |
|---|---|
| Reviewer role separate from file access | No department fact to base it on yet; can be added later |
| Index on confirm without re-running the checks | Skips the department, classification, ID and collision checks |
| Allow editing per page only | Reviewers fix fields that span OCR and native text; one text box is simpler |

## Consequences
- New endpoints: `GET /assist/review/ocr`, `GET /assist/review/ocr/{id}`, `GET …/scan`, `POST …/confirm`, `POST …/reject`.
- Review decisions are evaluation data in the PoC. They never change thresholds or policy silently.
