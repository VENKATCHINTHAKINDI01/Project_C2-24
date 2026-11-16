# ADR-0027 — Better-sourced mock: instrument hierarchy and classification grades

- **Date:** 14 Nov 2026 · **Status:** Accepted as MOCK (owner, 14 Nov 2026: "let them be mock … build good mock of
  them"). Nothing here is confirmed by the department · **Plan:** §4.5, §5.1 · **Milestone:** M1

## What changed
**`data/ontology/hierarchy.yaml`** (status `mock`, version `2026-11-14-mock`)
- A tenth level: **Proceedings of a Head of Department / competent authority**, placed below Standing Orders and
  above Circulars and Memos. Source: the AP training note on forms of communication (after the District Office
  Manual): proceedings are "the final order" of a competent authority for a specific sanction, while a memo is
  "not for conveying any order of the govt" and a circular is a memo-style communication.
- Labels widened where the source supports it: Act **or Ordinance**; Statutory Rules **/ Regulations (published
  by Notification)**; Circular / Memo **/ U.O. Note**.
- Every level now carries a `basis`: the source, or the word `assumption`.
- Still assumptions, stated in the file: G.O. (Ms) above G.O. (Rt) (office practice, not law: both are Government
  orders); where Standing Orders sit; notings at the bottom.
- No document type maps to the new level yet (`Rc.` numbers stay Circular / Memo): telling a proceedings from a
  circular needs the department's numbering rules. The level is there so the table is right when they arrive.

**`data/ontology/classification.yaml`** (status `mock`, version `2026-11-14-mock`)
- Grades unchanged (Unclassified, Restricted, Confidential, Secret), each now with its `basis`. Confidential
  and Secret are from the Central Secretariat Manual of Office Procedure; Restricted is an assumption (the Home
  Ministry's Departmental Security Instructions are not public).
- **Top Secret is deliberately not listed.** Tried and reverted: a listed grade that no officer may hold made
  every officer unable to confirm an order's current status, because the strict status rule (owner, 3 Nov 2026)
  needs the scope to cover the department up to the highest listed grade. Unlisted, a paper so marked is an
  unknown classification and is outside every scope — the safe outcome.

**Access policy:** unchanged. The manual's handling rule (confidential papers carried by an officer not below
Section Officer; secret by one not below Under Secretary with a Joint Secretary's written authority, para 57) is
about carrying papers out of the office, not about who may read a file; turning it into a reading rule would be
inventing a department fact (CLAUDE.md §15). Recorded here as the nearest public anchor for a future
"minimum rank per grade" rule, to be asked of the department.

## Checks
All unit tests pass with the new files (one test updated for ten levels and `mock`). The v1 harness is unchanged:
0 disclosures / 1,142 checks, recall@10 0.754, MRR 0.833, conflicts A/C/E/F P = R = 1.000.

## Sources (read 14 Nov 2026)
- AP training note "Forms of communication": etcsrikalahasti.ap.gov.in/assets/pdf/Commn.pdf
- Central Secretariat Manual of Office Procedure (definitions; paras 28, 56, 57): dor.gov.in/files/inline-documents/CSMOP.pdf
- Constitution of India, Arts. 162, 166, 309 (general position on Acts, rules and executive orders)

## Still to confirm with the department
The real list of grades; whether Ms outranks Rt for conflict purposes; where Standing Orders and proceedings
sit; whether a minimum rank per grade applies in e-Office.
