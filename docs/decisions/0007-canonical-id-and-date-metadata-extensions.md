# ADR-0007: Canonical ID and date metadata extensions for the public corpus

- **Date:** 2026-10-22
- **Status:** Accepted by the owner, 2026-11-03; collision suffix rule decided the same day (below)
- **Plan section:** §4.4, §5, §6

## Context
Real public records showed cases the base format `AP-<DEPT>-<TYPE>-<NUMBER>-<YEAR>` (CLAUDE.md §5.5) does not cover,
and that archive dates sometimes differ from the date printed on the order (about 1% are a day late).

## Decision
1. **Memos / circulars** are numbered by e-File number and one file issues many memos, so their IDs carry the file
   code and an issue-date tag: `AP-FIN01-CIRMEMO-FIN01COOROMISC-93-2023-D20240305`.
2. **Gazettes**: `AP-GAZ-GAZETTE-<PART>-<NO>-<YEAR>` (part from the gazette, e.g. `EI`, `EIVB`); the G.O. a gazette
   republishes is linked (`republishes_id` → REFERENCES), not merged.
3. **ID collisions** (same department, type, number and year but a different order — e.g. two Finance G.O.Ms.126 of
   2023): never guessed or auto-suffixed; the record goes to review.
4. **Dates**: `date` (document date, used for sorting and the ID) becomes the **printed** date only when it equals the
   archive date, a second independent source agrees, or a person verified it; otherwise the archive date is kept and
   the record flagged. Always kept: `printed_date`, `archive_date`, `date_source`, `date_mismatch`,
   `date_verification_status` (auto_agree · corroborated · needs_review · printed_unreadable · verified),
   `date_evidence {method, page, text}`. A change that would alter the year (and so the ID) is refused.
5. **Effective date ≠ issue date**: `effective_from` + `effective_from_source`; today `assumed_issue_date` everywhere
   until extracted ("with effect from …") or verified; extracted/verified values are never overwritten.

## Open question (owner) — resolved 2026-11-03
Suffix rule for genuine collisions: see 'Collision suffix rule' above.

## Alternatives considered
| Option | Why not |
|---|---|
| Always trust the archive date | ~1% are a day late; F-type (temporal) checks depend on dates |
| Always trust the OCR'd printed date | OCR misreads; 100 orders have no reliable printed date |
| Auto-suffix collisions | Guessing IDs is forbidden (CLAUDE.md §5.6) |

## Consequences
Ingestion (`backend/app/ingestion`, `identifiers`) must accept the memo and gazette forms and the date fields.
`CANONICAL_RE` in `data_collection/tools/common.py` already allows the optional file code and up to two suffixes.

## Collision suffix rule (owner decision, 2026-11-03)
1. The first record keeps the **unsuffixed ID**; only the newly discovered colliding record gets a suffix.
2. Suffix = the order's own **official section code**, normalised from the printed label (`HR.III` → `HRIII`,
   e.g. `AP-FIN01-GOMS-126-2023-HRIII`), used only when the order prints it and it distinguishes the record from
   every other member of the group.
3. Otherwise (no reliable code, or the same code) a **persistent registry suffix** `-C01`, `-C02` … from a per-group
   counter that only increases. Never `-A`/`-B` from collection or issue order.
4. Each assignment is tied to the record's **source identity** (e.g. `goir:gid=…`, `sha256:…`) and never reassigned.
5. A lookup by the **bare base ID** of a multi-record group returns **ambiguous** for review — never one of them.
6. The suffix, its evidence (method, page, text), the section code and the collision group are kept in the registry.
7. IDs whose suffix slot is already used (memo e-File suffix `-2`, note revision `-R1`) go to review on collision.
Implemented: `backend/app/identifiers/collisions.py` (`CollisionRegistry`, JSON file persisted atomically now; a
Cloud SQL table can take over later), tests `test_id_collisions.py`. Not yet wired into `data_collection/` (test phase).

## Applied in the backend (2026-11-03)
`resolve_reference(..., memo_date_tag=True)` is now the default for MEMO / CIRMEMO / RC references. Mock corpus v1 IDs
predate this rule (no tag); lookups try the exact ID, then `CanonicalId.base_id` (`lookup_keys`).

## Gazettes (owner decision, 2026-11-13)
e-Gazette numbers repeat within one part and year (Extraordinary Part I No.914 of 2022 was published on 25 Jan 2022 by
Law and on 7 Sep 2022 by General Administration).
- Base ID: `AP-GAZ-GAZETTE-<part code>-<number>-<year>`.
- As in rule 1 above, the first record keeps the base ID. Only a repeat (same base ID, different gazette file) gets
  its **publication date**, memo-style: `AP-GAZ-GAZETTE-EI-914-2022-D20220907`. The date is printed on the gazette
  and listed by the site, so it is evidence, not a guess. The record notes the clash (`id_note`).
- Applied in `data_collection/tools/collect_gazette.py` (`save_row`). The same gazette file is never saved twice.
  Rule 5 (a bare base ID is ambiguous) applies once the backend ingests gazettes.

## Mentor input (if any)
—
