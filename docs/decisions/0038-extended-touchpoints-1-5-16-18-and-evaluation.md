# ADR-0038: Extended touchpoints 1, 5, 16, 18, and all 20 touchpoints evaluated end to end

- **Date:** 2026-11-15
- **Status:** Accepted (owner: "build all touch points and then evaluate all of them at once",
  15 Nov 2026)
- **Plan section:** §11.5 touchpoints 1, 5, 16, 18; §11.6 ("ground truth for every touchpoint
  scenario"); §13.2; CLAUDE.md §2.4, §4, §5, §9.3
- **Builds on:** ADR-0017 (OCR), ADR-0037 (touchpoints 12, 17, 19)

## Decision
All four are deterministic, without a model call. The assistant suggests and the officer acts.

1. **Touchpoint 1 — diarising a receipt** (`POST /assist/diarise`, `app/ingestion/diarise.py`).
   - **What it fills:** the diary fields, read from the letter attached to the receipt: letter
     reference, date, subject, category (document type) and sender (signing post and the issuing
     department, without the wing).
   - **Reader and text:** it uses the same reader as ingestion (`extract_metadata`). For a native
     letter it reads the indexed text. For a scan it reads the OCR draft, and the card says it has
     not been reviewed.
   - **Evidence and gaps:** each field shows the line it was read from. A field the letter does not
     give stays empty; nothing is guessed.
   - **Saving and access:** nothing is saved. Access follows the receipt and the letter's tags; a
     hidden receipt gets the same 404 as an unknown one.
   - **Connector change:** `ReceiptContext.attachment_uri` (the uploaded letter).
2. **Touchpoint 5 — creating a file** (`POST /assist/previous-references`, plus the sandbox
   "Create file" at `POST /sandbox/files`):
   - earlier files on the same subject come from the scoped precedent ladder (the touchpoint 9
     engine), offered only when the officer can open the file (`file_computer_no`);
   - the officer ticks the files to enter as references, and the sandbox keeps only files they can
     reach;
   - the new file number is synthetic.
3. **Touchpoint 16 — closing a file** (`POST /assist/closing-remarks`, plus the sandbox "Close file"
   at `POST /sandbox/files/{no}/close`):
   - **The suggestion:** it quotes the last direction (note number, post, date and the note's own
     words) and lists papers issued after it. Wording is neutral ("the last direction on the file
     is …"): the assistant does not call anything a decision.
   - **Blockers:** shown, never hidden: the file is not with you, Yellow Notes are unconfirmed, the
     file is already closed, or no direction is recorded (then there is no text).
   - **Who can close:** only the holder, or a section officer when no holder is recorded. Anyone
     else gets 404.
   - **Joining the precedent index:** the officer's remarks become the last Green Note. The notes
     typed in the sandbox go to ingestion as a closing note sheet (`FILE_CLOSED` event, now synced),
     so the decided file joins the precedent index with the file's own classification.
4. **Touchpoint 18 — migrated old files:** this was already built (OCR, then the review queue, then
   confirmation, then the normal pipeline). It is now evaluated end to end:
   - before review, the scan is not evidence;
   - after the reviewer confirms, the old decision is found by a cleared officer and joins the
     file's note chain (#6–#8);
   - an officer without clearance sees neither the scan nor its review item.
5. **Screens:**
   - receipt page: "Pre-fill diary details" (field, the line it was read from, whether it matches
     the diary entry);
   - file list: "Create a file" (subject, suggested references with checkboxes, Create);
   - Assist panel: "Closing remarks" (editable text, blockers, Close file).
6. **Evaluation — all 20 touchpoints at once:**
   - **Answer key:** seven scenarios added to `touchpoint_scenarios.json` (TP01, TP05, TP12, TP16,
     TP17, TP18, TP19). Expectations come from the seed, `documents_index.csv` and
     `relations.csv`, not from running the code. They are marked draft, owner review.
   - **Harness:** `evaluation/harness/sandbox_flow.py` runs each one over HTTP against a fresh
     sandbox, as the screens call it.
   - **Run:** `run_eval.py` now covers 24 scenarios across touchpoints 1–20.

## Results (`evaluation/reports/2026-11-15-touchpoints-all.md`)
- Touchpoint scenarios: **24/24 passed**. TP01: 50/50 diary fields equal the diary entry (3 letters
  read by OCR; dashes the OCR dropped are ignored). TP05: all 3 expected files offered among 5.
- Unchanged against the 15 Nov baseline: leakage 0 disclosures out of 1,142 checks, recall@10 0.754,
  MRR 0.833, conflicts A/C/E/F P 1.000 R 1.000, opposite scenarios 20/20.

## Known gaps
- **Revision IDs:** a reviewed second note sheet of the same file is indexed with a collision suffix
  (`…-C01`), while the manifest names D22 `…-R1` (note revision). The pipeline has no note-revision
  rule yet, and that rule is the owner's to set (ADR-0007 suffix slot). The closing note sheet gets
  `-C01` the same way.
- **TP05 precision:** 3 of the 5 files offered are on the subject. The ranking is TP09's and is not
  calibrated.
- **Scenario sign-off:** the seven new scenarios are a draft answer key for the owner to review.

## Consequences
- The connector carries metadata only: an attachment URI, file numbers and Computer Nos.
- `FILE_CLOSED` events now reach ingestion.
- The sandbox gained two officer actions, Create file and Close file. Both are simulated clicks.

## Addendum — owner review, 15 Nov 2026
The owner's review found the TP19 answer key incomplete: open file 2881930 (note D29) cites
G.O.Rt.No.1184/2025 (D08), which expired on 31-03-2026, before the as-of date. The application
already listed it, but the key named only D03.

The scenario passed anyway because the harness checked that the expected items were a subset of
the output. Changes:
- **TP19 key corrected:** D08 is added, and each entry now states its change (superseded / expired).
- **Exact checks:** TP19 now compares files in hand, decisions and orders no longer in force
  exactly; TP17 compares its changes exactly. The old TP19 key now fails, so a missing or extra
  item is caught.
- **TP05 keeps a subset check:** a ranked suggestion list may include more files than the key.
- **Re-run:** `evaluation/reports/2026-11-15-touchpoints-reviewed`, 24/24, all other metrics
  unchanged.

