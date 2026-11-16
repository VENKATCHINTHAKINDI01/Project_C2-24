# ADR-0020: Synthetic e-Office set v2 — 200 files on the real corpus, three departments

- **Date:** 2026-11-13
- **Status:** Accepted (owner, 13 Nov 2026); building
- **Plan section:** §11.5 (touchpoints), §11.6 (seed data), §12 (synthetic corpus), §9 (evaluation); ADR-0003, ADR-0006

## Context
The public corpus is complete and in the bucket:
- 1,375 documents: 1,137 G.O.s (FIN01 512, GAD01 386, ESE01 239) and 238 gazettes, 109 of them Rules;
- relations with both ends held, per department: FIN01 SUPERSEDES 11 / AMENDS 29; GAD01 7 / 18; ESE01 3 / 35 (+2 REPEALS); gazettes AMENDS 9.

The sandbox still runs on `mock_v1` (3 departments, 8 officers, invented orders) and on the first generator (`generate_efiles.py`, 12 Finance-only scenarios). The owner asked for more synthetic e-Office files that:
- are built on the new data;
- cover every use case, scenario and department;
- follow actual formats and official layouts.

## Decision
1. **Size and spread:** 200 synthetic e-files, about 67 each for FIN01, GAD01 and ESE01. Every one of the 20 touchpoints (§11.5) appears several times, and conflict types A–G each appear several times per department where real orders support them. About 25% are clean controls (no conflict), so false positives are measured.
2. **Grounding:**
   - every cited order is a real order we hold;
   - every claim a planted conflict depends on is backed by a quoted span from that order, so the answer is provable;
   - conflict types that need facts we do not hold (C: memos / wrong authority) use clearly labelled synthetic memos, never invented G.O.s.
3. **Layouts:**
   - **G.O. / DFA drafts** copy the structure of our real orders: GOVERNMENT OF ANDHRA PRADESH / ABSTRACT / subject / DEPARTMENT (section) / G.O.Ms.No. – Dated / "Read the following" / ORDER / numbered paras / "(BY ORDER AND IN THE NAME OF THE GOVERNOR OF ANDHRA PRADESH)" / signature block / To / Copy to;
   - **note sheets, receipts and movements** follow public NIC e-Office references (Green / Yellow notes, para numbering, signature line with name and designation, diary number and date). Anything not confirmed by a public source is marked `[To confirm]`;
   - every file carries the SYNTHETIC banner.
4. **People:** 18 synthetic officers, 6 per department:
   - an ASO and an SO in each of two sections;
   - a Deputy / Joint Secretary and a Secretary;
   - one officer in a restricted section, for search-scope and leakage scenarios.

   Names are invented; posts and section names follow the real orders' headings.
5. **Location:** inside `data/synthetic/mock_v1/efiles_v2/` (owner: keep mock_v1 and use the same folder). The v1 documents, users and ground truth are untouched, so the existing baselines stay comparable. v2 has its own users, access matrix and ground truth, and the sandbox can load v1, v2 or both.
6. **Ground truth stays evaluation-only:** `efiles_v2/ground_truth/` is never read by `backend/app` (CLAUDE.md §9.2) and is never uploaded to a bucket the API service account can read.

## Alternatives considered
| Option | Why not |
|---|---|
| Replace mock_v1 | Loses comparable baselines; owner chose to keep it |
| Invent orders for missing conflict types | Breaks "every claim backed by a real order"; synthetic memos are labelled instead |
| 100 / 150 files | Owner chose 200 |

## Consequences
- The generator grows from 12 to about 200 scenarios. Scenarios are data (YAML) and the generator renders them, so the scenario list can be reviewed without reading code.
- New evaluation suites run on v2. v1 numbers stay as they are.
- The note-sheet layout is an assumption until a real (redacted) e-Office sample or the AP Secretariat Office Manual 2005 is available: `[To confirm]` with the department.

## Addendum — loading v2 into the sandbox (13 Nov 2026)
- **Setting:** `C2_SANDBOX_SEED=v1|v2|both` (default `v1`, so nothing changes unless asked). v2 and both need
  `C2_SANDBOX_PUBLIC_CORPUS_DIR` (the data root holding the real public orders); without it the app does not start.
- **Seed:** `data/synthetic/tools/build_eoffice_seed_v2.py [--check]` turns the rendered files into
  `efiles_v2/eoffice/seed_v2.json` (same `Seed` schema as v1). It also writes the documents the assistant reads:
  each file's correspondence pages, its note sheet (Green notes) and, for a pending file, the Yellow draft. No scenario
  key, conflict type or cited-order list enters the seed.
- **Public orders:** `data_collection/tools/index_public_cited.py` lists the cited real orders that the corpus holds,
  in `efiles_v2/eoffice/public_index.csv`, with SHA-256. The loader refuses a file whose hash changed, or a path
  outside the data root. The list has 83 orders (55 MB); `--scope sections` adds the other orders of the nine
  sections.
- **Merge (`both`):** `merge_seeds` refuses any clash of officer, file, file number, note or page identifiers. v2 uses
  the printed section codes (HR.I, SER.A, …) as v1 does, so a v1 officer of the same section also reaches v2 files
  of that section.
- **Mapping:**
  - role ranks are on the v1 scale (ASO 0, SO 1, AS 2, JS 4, head 5);
  - departments consulted by U.O. note are staff posts without a login;
  - heads moved from Global to Department scope, because the app never opens another department's non-public papers.
    The access matrix and the app now agree; the test checks that the app never reaches further than the matrix.
- **Known gap:** one section per profile. An Assistant Secretary over two sections reaches the second section's files
  only by having handled them. Today that is every such file, so the test finds 0 differences.

## Addendum — OCR of the real public orders in the sandbox (13 Nov 2026, owner)
- **Recorded OCR:** the corpus OCR (Document AI, pinned v2.1.1, 15-page chunks) is joined per file by
  `data_collection/tools/join_ocr_cache.py` and replayed by the sandbox for v2/both. No new calls.
- **Auto-pass (owner, 14:43 IST: "if the confidence score is above 80 lets just mark them as reviewed and pass
  them"):** `sandbox.yaml` → `ocr.public_auto_pass_min_confidence: 0.80`. In sandbox v2/both only, a real public order
  (`public://`, UNCLASSIFIED) whose lowest OCR page confidence is at least 0.80 is indexed without waiting for a
  reviewer. It is recorded as **auto-passed**, not as reviewed: no reviewer ID is written, and the runtime lists it in
  `auto_passed`. Synthetic scans, classified material, pages with no confidence, and production (runtime.yaml
  uncalibrated) still go to human review. Every assist response keeps `"calibrated": false`.
- **Content check (owner: "if the file content is useless lets not select them"):** all 83 cited orders' text was
  read; each is the real order with readable text, so none was dropped.

## Addendum — clean controls and effective dates (13 Nov 2026, owner OK)
- Four labels corrected by hand (`scenarios/relabel_v2.yaml`, quotes checked against the real order).
- Builder rule: a clean file is clean against ALL verified links (chains.yaml) and the orders' stated effective dates
  (`extract_effective_dates.py`). Otherwise its note date moves into the clean window, or it becomes a planted conflict
  when there is no window. Clean files with a later change are rendered to finish quickly (`close_by`).
- Result: 163 planted conflicts and 38 clean controls (19%, below the ~25% first planned; the real orders change
  often, e.g. the RTE Rules 2010 were amended many times).

## Mentor input
None yet.

## Addendum — demo holdback (13 Nov 2026, owner's choice)
- **Order held back:** G.O.Ms.No.139, GAD (Protocol.A), 23-12-2025 (amends the Warrant of Precedence, G.O.Ms.59/2018).
  Moved to `staging/holdback/` in the data root, listed in `scope.yaml` `demo_holdback`, left out of the bucket upload
  and out of `relations.jsonl`. No planted conflict depends on it.
- **Two open files** (`scenarios/holdback_v2.yaml` → GAD01-CABN0BR/211 and 212/2025, Cabinet.II) apply G.O.Ms.59/2018
  read with 8/2021. Cabinet.II does not own the Warrant of Precedence; the files only apply it. They are appended
  last, so no other file changed (203 files; 163 planted conflicts; 40 clean).
- **Sandbox:** `eoffice/public_holdback.csv` (written by `index_public_cited.py`) lists held-back orders; they are not
  loaded at start. `GET /sandbox/orders/pending`, `POST /sandbox/orders/arrive {id}` lets one arrive: it is ingested by
  the normal pipeline and reconciliation lists the open files citing the changed order (touchpoint 4).
- **Checked locally:** before arrival both files pass the pre-send check with no flag; after arrival G.O.139 is indexed
  with a confirmed AMENDS link and `/assist/notices` lists both files to officers who may see them, and to no one else.

## Addendum — what the sandbox loads, and how type E files cite (14 Nov 2026)
- **Loaded orders:** the cited orders AND the held orders that supersede / amend / repeal / clarify one of them, or
  follow it in a rate series. The list comes from the corpus's own links (`relations.jsonl`, `chains.yaml`), never
  from the ground truth. Reason: with only the cited orders loaded, a superseding order was simply absent and the
  conflict could not be found by any system. 120 orders.
- **Type E files** cite the missing order as a real order of the department printed it (`cite_raw`), on that
  order's subject; no invented citation forms.
- **Stale papers** after a re-render are moved to `Project_1/_to_delete/` (never left in place).

