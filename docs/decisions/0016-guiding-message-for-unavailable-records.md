# ADR-0016: One guiding message for records an officer cannot get

- **Date:** 2026-11-11
- **Status:** Accepted (owner, 11 Nov 2026)
- **Plan section:** §5.4 (indirect leakage: existence), §5.9 (fail closed), §13.3 (leakage matrix); CLAUDE.md §4.4, §4.7

## Context
The owner asked that an officer who is refused a file be told why and how to get it: "you are not
authorised for this file, please get relevant access or approval from authorities". Saying "not
authorised" (or "restricted") for a specific record confirms that the record **exists**. Asking
for record numbers one by one would then map out which vigilance, disciplinary or secret files
exist. That conflicts with CLAUDE.md §4.7 and plan §5.4, and the leakage harness would count it as
a disclosure. Until now the answer was a bare "File not available." / "Document not available.",
which was safe but gave the officer no way forward.

## Options presented to the owner
| Option | Effect |
|---|---|
| **One guiding message (chosen)** | The same text for a hidden record and a missing one, pointing to the competent authority in e-Office. Zero disclosure is kept |
| Say "restricted" only where the officer already knows the record exists (own movement trail / file list) | Reveals the classification of known records; needs per-path care |
| Say "restricted" everywhere | Confirms the existence of any hidden record; breaks the zero-disclosure bar; would need department sign-off |

## Decision
Every "not available" answer uses one message per record kind, identical in words, status (404)
and body whether the record is hidden or does not exist:

> This file isn't available to you. If you need it for your work, please request access or approval
> from the competent authority through e-Office (your section / controlling officer).

The document and receipt messages are the same, with "document" or "receipt" in place of "file".
The text lives in one place, `backend/app/auth/messages.py`. A citation highlighted as "not found"
(ADR-0015) shows the same guidance in its tooltip.

The message never says "restricted", "not authorised", or a classification level. C2-24 grants no
access itself: the route to access is the competent authority through e-Office.

## Consequences
- Every API route that refuses a file, document or receipt uses the new constants, and the frontend
  shows the server's text.
- New regression test: hidden and unknown are byte-identical and carry the guidance, with no
  "restricted / not authorised / classified" words. The 20 opposite scenarios still pass
  (`same_as_unknown`), and the leakage bar is unchanged (0).
- Unchanged: the "status cannot be confirmed from your records" message (owner rule, 3 Nov), and
  the "No sufficiently supported answer was found in the authorised records" message.

## Mentor / department input
Confirm with the department the wording of "competent authority" and the route for access
requests (e-Office section / controlling officer) before real use.
