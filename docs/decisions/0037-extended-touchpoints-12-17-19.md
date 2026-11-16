# ADR-0037: Extended touchpoints 12, 17, 19 — movement summary, since the decision, section handover

- **Date:** 2026-11-15
- **Status:** Accepted (owner: "proceed with building touch points", 15 Nov 2026)
- **Plan section:** §11.5 touchpoints 12 (Initiate action), 17 (Reopening a file), 19 (Section
  reassignment); §6 temporal; §4 security; CLAUDE.md §2.4, §4.6–4.7, §6.1

## Context
The core touchpoints (17 scenarios) pass. Of the extended ones, 12, 17 and 19 were not built. All three
summarise records C2-24 already holds: e-Office movements and notes, the orders a file cites, and their
status over time.

## Decision
All three are **deterministic**: no model call, no free text from a model. Every line comes from a
record and carries its reference.

1. **Connector:** `FileContext` gains `movements` (seq, from/to user and post, sent at, due, priority,
   remarks, sent back — what e-Office shows on the file page), `state`, `created_on`, `created_by`.
   `OfficerFile` gains `state`. A new connector method, `section_files(user_id)`, lists the files of the
   officer's own dealing section within their reach. The connector still carries metadata only.
2. **Touchpoint 12 — `POST /assist/movements`** (`app/noting/movements.py`):
   - each movement with its remarks and how long the file was held;
   - the note(s) the sender signed between the previous movement and this one (matched by post and
     signature time; the note's own first lines, with its number);
   - where the file is pending, since when, due or overdue, and how often it was sent back;
   - the last direction.
   
   The sentence at the top is a template. A closed file has no holder.
3. **Touchpoint 17 — `POST /assist/since-decision`** (`app/temporal/since_decision.py`):
   - **The decision:** the file's last direction (its own note, number and post). Its date is the
     note's signature; if there is none, the last movement. An open file says "last direction", not
     "decided".
   - **What changed:** for each order the file's papers cite (L3, one hop, scoped), its status today
     (`check_document_status`: superseded, repealed or expired, by which order, from when), plus newer
     orders that amend or clarify it (L3 inbound, scoped).
   - **Grouping:** changes dated after the decision are listed apart from changes already in effect
     when it was taken. "Nothing changed" is said only "in the records available to you".
4. **Touchpoint 19 — `GET /assist/handover`** (`app/precedent/handover.py`), for the officer's own
   dealing section:
   - **files in hand:** pending with whom, days, overdue first, cited orders that changed, last
     direction;
   - **orders the section works under:** cited orders not known to have changed, by number of files.
     "In force" appears only where the officer's access covers every record that could change it;
     otherwise "status not confirmed for your access" (the existing coverage rule);
   - **orders no longer in force:** cited orders that have changed, with what replaced them;
   - **recent decisions:** closed files and their last direction.
   
   Counts are over files the officer can open now (e-Office reach plus C2-24's classification check),
   so a section-mate with wider clearance sees more and the officer sees no hint of the difference.
   No section gives a plain message.
5. **Access:** movements and since-decision use the same `open_file` check and the same 404 for hidden
   and unknown files. The handover skips files the officer cannot open, without saying so.
6. **Screens:** two chips on the file's Assist panel ("Movement summary", "What changed since the
   decision"), and a "Section handover" panel on the file list, loaded on request.

## Found and fixed on the way
- **Note signatures in set v2:** the date comes first and the name and post below it. `parse_notes`
  read the post from the note's last paragraph. Fixed, with a regression test. This also corrects
  "File so far" (touchpoint 8) and the approval brief's "put up by" on set v2.
- **Concurrent first build:** `functools.cache` let every request that arrived before the first sandbox
  build finished start its own build (several builds in parallel, minutes of CPU on a cold instance).
  There is now one build behind a lock and the other requests wait; regression test added. Cloud Run
  with warm start was not affected.

## Alternatives considered
| Option | Why not |
|---|---|
| Gemini writes the summaries | Adds a model to what records already state; every sentence would then need the citation check. The templates say only what the records say |
| A reassignment event (admin moves a section to a new holder) | Plan §11.7 allows section assignment, but who may reassign is department policy (mock). The handover works for whoever holds the section now. The event can come later |
| "Changed since" on reading the clauses (e.g. 20% → 15%) | Needs a comparison of clause text; the records give status and the amending order, which the officer opens with one click |

## Consequences
- Evaluation: 0 disclosures out of 1,142 checks; touchpoints 17/17; opposite scenarios 20/20;
  retrieval metrics unchanged. There are no touchpoint scenarios yet for 12, 17 and 19 in the ground
  truth. Adding them is the owner's call (answer key); the unit and API tests cover them now.
- Synthetic set v2 files are old (2016–2018) with as-of 2025-12-31, so "days pending" runs to thousands.
  That is the data, not a bug.

## Confirmation still needed
Department: which remarks e-Office shows at a movement, whether a handover should also cover parked
files and pending receipts, and who may reassign a section.
