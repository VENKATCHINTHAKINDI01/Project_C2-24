# ADR-0015: Citation highlights in notes, with click-to-open

- **Date:** 2026-11-10
- **Status:** Accepted (owner request, 10 Nov 2026). Two design points below are open for owner review
- **Plan section:** §6.2 (conflict types A/E/F), §8.2 (citations), §11.5 (touchpoints 10–11), §5.4 (indirect leakage); builds on ADR-0014 (preview and download), ADR-0013 (held records)

## Context
The owner asked that the orders a note cites be highlighted in the note itself: which ones are in
conflict, which are fine, and a click on a highlight opens that order's stored file. Until now
conflicts were visible only in the pre-send panel, as a list, after the officer pressed "Send".

## Decision
1. **Where the citations are.** The same citation patterns ingestion uses (`extract_metadata`) are run
   over the note's text, and each one is located by its offsets in the original text
   (`citation_spans`). This works even when a citation wraps across lines.
2. **One state per citation.** Each state comes from the same deterministic A/E/F review as the
   pre-send check (`review_citations`), run only over the officer's visible records:
   - *conflict*: a certain A or F flag;
   - *review*: uncertain flags only;
   - *unconfirmed*: the order's status can't be confirmed (owner coverage rule, 3 Nov);
   - *not found*: type E;
   - *ok*: none of the above.

   Every flag stays advisory ("Potential conflict … Review recommended").
3. **Links only to what the officer may open.** An order gets a `canonical_id`, and so a link, only
   when it is among the officer's visible records. Opening it goes through ADR-0014: access is
   re-checked on every request, a 404 looks the same as for an order that doesn't exist, the
   exact stored bytes are served, and each request is audited.
4. **Not found names the order only in the note's own words.** The order is never shown by an ID
   resolved from the text. That ID would read like a record C2-24 holds, and it would make a
   hidden order look different from one that does not exist. This was found by opposite scenario
   OPP-19, written before the run.
5. **e-File citations** are marked and become a link only if the file is in the officer's own
   e-Office file list. The check happens on the e-Office side, so the core adds no new reach.
6. **Fail closed.** If the officer has no valid scope, the highlight call returns the same 404 as
   "File not available." (now the guiding message, ADR-0016) If the highlight call fails, the note is shown as written, without marks.

## Points for owner review
- **As of which date?** Highlights are checked against **today's** records, so an old Green Note
  shows what has changed since it was written, such as "superseded by 31/2025". The pre-send check
  still uses the note's own date. Alternative: check each note as of its own date ("was it valid
  when written?").
- **Office files** (docx/xlsx) download only. They are not rendered in the browser.

## Alternatives considered
| Option | Why not |
|---|---|
| Highlights only in the pre-send panel | The officer can't see where in the note the problem is |
| Link every citation, let the preview 404 | A link that works for some citations and not others hints at which records exist |
| Signed URL per highlight | Same objections as in ADR-0014; one access path is easier to prove |

## Consequences
- Adds `POST /assist/highlights` and `GET /assist/documents/{id}`, `…/preview` and `…/download`.
- The leakage matrix grows by three paths (highlights, document details, document file), and the
  opposite scenarios grow by four (OPP-16 to OPP-19).
- "Opened at the cited page" (ADR-0014 rule 3) waits for page locations. A cited paragraph has no
  page until Document AI layout gives one, so the preview opens at page 1 for now.

## Mentor / department input
None for the sandbox. The department must confirm before real files are served (as in ADR-0014).
