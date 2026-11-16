# ADR-0034: Officer conveniences — references, cited-paragraph preview, suggestions, shortcuts, digest

- **Date:** 2026-11-15
- **Status:** Accepted (owner chose these from the suggested list, 15 Nov 2026)
- **Plan section:** §8.1 (cited answers), §11.5 touchpoints 7, 4, 12 (reused), §11 sandbox UI

## Context
Officers read an answer, check its source, and paste it into a note. Each step meant leaving the file
or retyping a canonical ID. Officers also had no single place to see what waits with them and which
orders their open files cite that are no longer in force.

## Decision
- **Reference form:** every citation carries `reference`, the order as written in a note ("G.O.Ms.No.31,
  Finance Department, dated 12-05-2025, para 2(v)"), built only from the canonical ID, the department
  table and the record's own date (`app/identifiers/display.py`). Notes, rules and gazettes keep their ID.
  Nothing is guessed. A "Copy" button copies a statement with its references.
- **Cited paragraph on hover:** `GET /assist/documents/{id}/context?quote=` returns only the paragraph that
  holds the quote (matched like the citation check), with the quote's range; same record check and same
  404 as the document routes. The screen fetches it once per citation and marks the words.
- **Suggested questions:** built in the screen from the file's subject ("Has a <matter> been decided
  before?", "What are the current rules on <matter>?") and the orders the notes cite that the check
  marked ("Is <order as written> still in force?"), plus "Draft the noting using that precedent."
- **Shortcuts:** Ctrl/⌘+K ask; Ctrl/⌘+Enter insert the latest first-cut as a Yellow Note (a draft, as
  the button does); J/K next/previous pre-send flag; ? shows the list. Never while typing.
- **Digest:** `GET /assist/digest?days=7` — files waiting with the officer (oldest first, overdue marked)
  and orders cited in their open files that are superseded/repealed/expired, those that changed within
  the window marked new. Files come from the connector (`officer_files`: assigned, created, or in the
  movement trail; open; within reach) and each is re-checked with the same file check as every file
  route; cited orders come from the graph (scoped walk) and their status from the temporal engine.

## Alternatives considered
| Option | Why not |
|---|---|
| Format references in the browser | The department names and record dates live on the server; one formatter for all screens |
| Return the whole order text for the preview | More than the officer asked to see; one paragraph is enough and keeps the response small |
| Email a weekly digest | No mail in the sandbox; the digest shows on the file list instead |

## Consequences
- The digest uses the sandbox clock (`as_of`); on seed v2 the files are years old, so "days waiting" is large.
- Seed v1 open files have no movements: a file is "with" the officer who opened it until it is sent.

## Mentor input (if any)
None. The reference wording follows G.O. headers; confirm the department's preferred form.
