# ADR-0031: Officer actions on drafts and feedback capture

- **Date:** 2026-11-15
- **Status:** Accepted (owner's standing instruction to build the remaining plan blocks; mock e-Office behaviour)
- **Plan section:** §9.1 checkpoint 2, §9.2, §10.4, §11.2; milestones M6 ("officer approves"), M7 ("every human action logged")

## Context
The assistant inserts Yellow Notes and DFA drafts only on the officer's click, but the sandbox could
not take the officer's next steps: edit, confirm as a Green Note, or throw away. Nothing recorded what
officers thought of answers, statements or conflict flags; the query log's `human_action` field was
always empty.

## Decision
1. **The officer's actions are e-Office actions, in the sandbox** (`/sandbox/files/{no}/drafts/{id}/
   save|confirm|discard`). A draft is the author's own until confirmed: other officers who open the file
   do not see it, and touching someone else's draft gives the same 404 as a draft that does not exist.
   Confirm turns a Yellow Note into the file's next Green Note under the officer's name and post (a
   simulated click, no DSC/eSign), drops the assistant's draft markers ("AI FIRST-CUT…", "FIRST-CUT NOTE
   —…", "(C2-24 pre-send check, draft)"), keeps every version, and raises `NOTE_CONFIRMED`. DFA drafts are
   not confirmed here (e-Office's own approval chain is not simulated). `/assist` has no confirm, sign,
   send or approve endpoint (test).
2. **Outcomes reach the core through the connector** as `DraftOutcome` (IDs, outcome, `edit_share`) — no
   text. `edit_share` = 1 − word-level similarity between the AI's first version and the confirmed text,
   draft markers ignored: 0 = confirmed as drafted.
3. **Feedback endpoint** `/assist/feedback`: thumbs on an answer (only a turn of the officer's own
   session), thumbs on a statement (only a record the officer may see now; a clause → its document),
   accept / dismiss on a conflict flag (only on a file the officer can open). Fixed reason codes; no free
   text; extra fields refused. Unknown, hidden and someone else's targets give the same 404 (ADR-0016).
4. **One record per action** (`HumanAction`: user, query_id = the output's request ID, target kind,
   target IDs, action, reason code, flag type, edit share) into `InMemoryActionLog` or BigQuery
   `c2_audit.human_action` (same switch as the query log, `C2_QUERY_LOG=bigquery`). Append-only; the view
   `query_log_actions` fills the plan's `human_action` field with each query's latest action
   (`22_human_action_table.sh`). Every feedback call is also in the audit log.
5. **Evaluation data only** (CLAUDE.md §8): nothing reads these records back to change retrieval,
   rules, prompts or access.

## Alternatives considered
| Option | Why not |
|---|---|
| Update `query_log.human_action` in place | Rows still in BigQuery's streaming buffer cannot be updated; an append-only table plus a view needs no UPDATE and keeps every action |
| Store the officer's edited text to measure edits | Restricted content in a tracking table (CLAUDE.md §4.11); a number is enough for evaluation |
| Free-text feedback reasons | Could carry restricted content; fixed codes cover the plan's signals |
| Confirm through `/assist` | The assistant would be taking the officer's action (CLAUDE.md §2.4, §4.13) |
| Show every officer's drafts to anyone who opens the file | e-Office keeps a Yellow Note the author's own until confirmed; showing it leaks work in progress |

## Consequences
- M6's "officer approves before it is final" and M7's "every human action logged" have code and tests.
- A forged `request_id` on statement / flag feedback can only add noise to evaluation data; it reveals
  nothing (same response) and changes nothing.
- Discarded and confirmed drafts are kept (status), never deleted.
- Confirmed notes join the file's notes through the connector at once (file-so-far, references); they
  are not re-ingested as documents (events of kind `NOTE_CONFIRMED` are not ingested yet).

## Mentor input (if any)
None yet. The reason codes and the "author's own until confirmed" rule are mock e-Office behaviour — confirm with the department.
