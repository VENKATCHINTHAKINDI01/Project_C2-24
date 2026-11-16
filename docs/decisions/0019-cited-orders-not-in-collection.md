# ADR-0019: Cited orders C2-24 does not hold — one shared message, gap list for admins only

- **Date:** 2026-11-12
- **Status:** Accepted (owner, 12 Nov 2026). Part 2 (admin coverage page) not yet built
- **Plan section:** §5.4, §5.9 (fail-closed messages), §6.2 (type E), §11.5; CLAUDE.md §4.7

## Context
The public corpus will never be complete. After three collection rounds (12 Nov 2026), some cited orders remain out of reach:
- 9 in-scope G.O.s that the Internet Archive mirror does not carry;
- 7 that the mirror lists without a usable PDF;
- the 1965–2006 orders cited by in-scope orders ("tier 2"). The mirror has none of these.

GOIR forbids automated collection (`Disallow: /`), and hand downloads were judged impractical.

The owner asked that officers be told when such a file "doesn't exist in our database". But C2-24 already shows one answer for "not held" and "held but not allowed" (ADR-0016). A separate "not in our database" message would let an officer learn that a cited order they get the other message for exists and is restricted, which breaks CLAUDE.md §4.7.

## Decision
1. **One shared, honest message** for every cited order the officer cannot open, whether C2-24 does not hold it or the officer may not see it: "Not found in the records available to you. It may not be in C2-24's collection yet, or you may need access. If you need it for your work, please request access or approval from the competent authority through e-Office (your section / controlling officer)." It is used in:
   - the type E explanation;
   - the highlight tooltip (`not_found`);
   - reference lookup with no match (`NO_MATCH`);
   - the approval brief;
   - the document 404 (`DOCUMENT_NOT_AVAILABLE`).

   The text lives in `app/auth/messages.py` (`NOT_IN_COLLECTION`, `CITED_NOT_FOUND`) and the same words are in `Citations.tsx`; a test keeps them equal. e-Office file, receipt and review-item messages are unchanged: those are not collection gaps.
2. **The list of collection gaps** (public orders cited but not collected, with the reason) is shown only on an **admin / data-steward coverage page**, never to officers. **Not built yet.** The planned design:
   - computed from unresolved citations;
   - counted only over the documents the admin may see, so no citation text from a restricted document reaches the page;
   - the admin role is a mock, `[To confirm]` with the department.

## Alternatives considered
| Option | Why not |
|---|---|
| Separate "not in our database" text | Shows which cited orders are restricted (existence leak); needs a rule change and department sign-off |
| Keep "Not found in your records" | Owner wanted officers told the collection may be incomplete |
| No gap list at all | The owner and data stewards need to see what is missing in order to fill it |

## Consequences
- Officers are told honestly that the collection may be incomplete, without learning anything about restricted records.
- Unresolved citations stay type E advisory flags. Nothing is guessed (CLAUDE.md §5.6).
- A gap list must never be offered to officers. If an "admin" role is added, it needs its own access rules.

## Mentor input
None yet.
