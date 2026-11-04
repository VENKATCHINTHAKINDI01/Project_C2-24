# ADR-0011: Department from the source system's tag when the text names none

- **Date:** 2026-11-04
- **Status:** Accepted (owner, 4 Nov 2026)
- **Plan section:** §4.3, §4.4, §5.1; CLAUDE.md §5.5–§5.6

## Context
The 4 Nov 2026 evaluation baseline found that Standing Order No.2/2020 (D11) never gets indexed. Its text names no department anywhere, so its own reference cannot be turned into a canonical ID ("never guess"), and ingestion holds it. The source system that holds the file already records its department. That tag is the same department that feeds `compute_scope`, so a document without a department can't be scoped properly either.

## Decision
Ingestion may use the source system's department tag, under three conditions:
1. **Only to fill a gap.** The tag is used only when the text names no department. If the text names one, the text wins.
2. **Provenance is recorded.** `DocumentMetadata.department_source` is `text` or `source_system`, so a department read from the page can always be told apart from one taken from the tag.
3. **Disagreement goes to review.** If the text names a department that differs from the tag, the document is held (`ReviewKind.DEPARTMENT_MISMATCH`) and not indexed until an officer decides.

## Alternatives considered
| Option | Why not |
|---|---|
| Keep the document held for an officer to fill the department | Correct, but a routine, recorded fact from the system holding the file would cost a manual review for every such document |
| Always use the tag | The text is the primary evidence; a mis-tagged upload would then be silently mis-scoped |

## Consequences
- This is not a guess: the tag is recorded metadata from the system of record. The rule against inferring a department from content still holds.
- D11 now resolves to `AP-USD01-SO-2-2020`, marked `department_source: source_system`.
- When real e-Office or department data arrives, confirm that its department field is reliable before relying on this rule (the officer hierarchy and data facts are still `[To confirm]`).
- To reverse it: drop `source_department` from the `extract_metadata` call in `pipeline.ingest`. Affected documents then go back to the review queue.

## Mentor input (if any)
None yet.
