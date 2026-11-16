# ADR-0009: Access control (store + rank + search scope), shared answer cache, e-Office connector contract

- **Date:** 2026-11-02
- **Status:** Accepted by the owner, 2026-11-03 (both open questions decided; see 'Owner decisions')
- **Plan section:** §5.1, §5.2, §5.9, §10.2, §11.3, §11.4

## Context
P0 asks for an authorization spike (`compute_scope` + `can_access` passing the mock access matrix) and the mock
e-Office data model + `EOfficeConnector` interface. Both can be built as pure Python without GCP or real data.

## Decision
1. **Policy parameters live in config** (`data/ontology/access_policy.yaml`, `status: mock`): public classification
   (UNCLASSIFIED) and the department-wide rank threshold (3 = Deputy Secretary or above). The rule itself is the one
   the mock corpus was generated with (`data/synthetic/mock_v1/README.md`). Real rules are `[To confirm]`.
2. **Two independent code paths**: `compute_scope` builds a filter object (`Scope.admits`, later rendered as
   BigQuery / Vertex AI Search filters); `can_access` re-checks each candidate. A test proves they agree on every
   officer × document, and both fail closed (unknown clearance/classification → deny; any error → deny).
3. **Scope signature** = SHA-256 of the scope's permission fields + policy version, *without* the user ID, so two
   officers with identical permissions share cached answers (plan §10.2 key `hash(canonical_query + scope_signature)`).
   Any change in clearance, section, assignments, rank or policy version changes the signature.
4. **Connector contract** (`backend/app/connectors/eoffice.py`): `officer_context`, `file_context` (unknown and
   unreachable files raise the same neutral error), `events_since`, `create_draft` (only Yellow Note / DFA draft /
   suggested reference, only when `officer_clicked`). Core modules never import `app.eoffice_mock` (test-enforced).
5. ~~Memo date tag off by default~~ — superseded 2026-11-03 (ADR-0007 accepted; now on, with `lookup_keys` fallback). Originally: the mock corpus IDs
   have no `-D<yyyymmdd>` tag; switch on when ADR-0007 is accepted (the collector already writes it).

## Owner decisions (2026-11-03)
- **Rank AND search scope.** "Include the rank of the officer in the restriction." Department-wide reach needs
  `role_rank >= 3` *and* a Department/Global e-Office search scope; same-section reach needs a Section-or-wider scope;
  Individual / Post-hierarchy scope gives file-level reach only (assigned or handled files) until the reporting tree is
  confirmed (ADR-0008).
- **Real access control, enforced during retrieval** (problem-statement expectation: "use real access controls, rather
  than simply storing permissions as document metadata, and enforce those permissions during retrieval"):
  grants live in an access store as relationship tuples (`app/auth/store.py`; Cloud SQL `data/schemas/authz.sql`),
  read on every request; documents carry only location tags; every retriever requires a `Scope`
  (`app/retrieval/scoped.py`) and survivors are re-checked against the store; revocations apply on the next request.
  Tier-2 row-level security policy drafted in the same DDL.
- **Shared answer cache** for identical permissions (many offices draft similar notings): key =
  `hash(canonical_query + scope_signature)`, signature excludes the user ID (`app/cache/answers.py`).
- **ADR-0007 accepted** the same day: memo/Rc date tag on by default.

## Questions as originally posed
- **Search scope in policy:** e-Office search privilege (Global / Department / Section …) is carried in
  `OfficerContext` and enforced by the connector on file open, but is not yet an input to `compute_scope`.
  Option A: keep rank-based policy (matches the mock matrix). Option B: derive "department-wide" from a
  Department/Global search scope instead of rank. Plan §11.4 implies B for the demo.
- **Shared cache across identical scopes** (point 3) vs per-user keys (safer, lower hit rate).

## Alternatives considered
| Option | Why not (for now) |
|---|---|
| Postgres tuples first | Needs a running DB; pure functions prove the policy and stay as the reference implementation |
| One code path for scope and re-check | Would make the "both layers agree" test meaningless |
| Include user ID in the scope signature | Safe but no cross-user cache reuse; left as an open question |

## Consequences
Cloud SQL tables (users, documents, file_assignments, policy) must carry the same fields as `Principal` and
`DocumentAccessTags`. Retrievers must take a `Scope` argument. Revisit after the hierarchy re-check (ADR-0008).

## Mentor input (if any)
—

## Addendum — papers inside an e-File are never "public" (13 Nov 2026; security fix, reported to the owner)
- **Found:** on synthetic set v2, 102 of 203 files are marked UNCLASSIFIED. The policy's public shortcut made their
  note sheets, drafts and correspondence readable by every officer: 4,182 officer × document disclosures against the
  v2 access matrix (e.g. an open-file notice named two Cabinet.II files to a Finance ASO). mock_v1 has no UNCLASSIFIED
  file papers, so the v1 leakage harness could not see it.
- **Rule now:** the public shortcut applies only to a published instrument (`file_no` is empty). A paper inside an
  e-File follows the file's reach (department, clearance, section / scope, assignment, movement), whatever its marking.
  Same rule in `policy.check` and in the pushed-down filter `Scope.admits`. Policy version `2026-11-13-mock` (cached
  answers keyed by the old version are not reused).
- **Why without waiting for a decision:** CLAUDE.md §2.4 ("never more than the officer's e-Office search scope
  allows") and §4.7; the change only narrows access (fails closed). [To confirm] with the department like the rest of
  the access model.
- **Tests:** `test_eoffice_seed_v2.py`: every v2 file paper × every officer against the access matrix (0 disclosures;
  the test fails with 4,182 on the old rule), and the scope filter agrees. v1 leakage harness unchanged (0 / 1,142).

