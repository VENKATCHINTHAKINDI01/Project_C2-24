# C2-24 — Progress Tracker

Tracks build progress against [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) (Final / v5, 13 Oct 2026). Update this file at the end of every work session.

**Last updated:** 4 Nov 2026
**Current phase:** P0 — Foundation & design
**Overall status:** 🟡 Planning done · build starting on synthetic data · real department data not yet received

Legend: ✅ done · 🟡 in progress · ⬜ not started · ⛔ blocked

---

## 1. Phase status

| Phase | Focus | Status | Notes |
|---|---|---|---|
| P0 | Foundation & design | 🟡 | Local foundation, authz spike, e-Office data model + connector done; GCP access pending; Cloud SQL schema, seed data, touchpoint scenarios open |
| P1 | Ingestion & extraction | 🟡 | Idempotent ingestion job over detection, native extraction, gate, metadata, canonical IDs + collisions, index/graph/temporal writes, pending-edge reconciliation, cache invalidation; OCR (Document AI) waits for GCP |
| P2 | Authorization core | 🟡 | Access store (tuples) + rank AND search-scope policy; enforced in L0/L1 reference retrieval with re-check; Cloud SQL DDL drafted (not applied) |
| P3 | Retrieval ladder + RAG + citations | 🟡 | L0/L1 and L3 reference implementations with scope + re-check (in-memory); L2, BigQuery/Spanner backends, evidence package, Gemini not started |
| P4 | Temporal + conflict + reconciliation | 🟡 | Temporal engine (incl. order end dates and action windows read from clauses), deterministic A/C/E/F with facts read from notes, pre-send check (touchpoint 11), reconciliation done; every deterministic planted conflict found on the pipeline stack; B, G, D (grounded Gemini) open |
| P5 | Agents + noting + memory + HITL | 🟡 | Typed AgentState + intent templates done (no LangGraph/Gemini yet) |
| P6 | Verification, audit, tracking | ⬜ | |
| P7 | Evaluation & security harness | 🟡 | Harness on the reference stack: retrieval metrics, A–G conflict P/R, leakage matrix (8 paths, 0 disclosures), 6 of 17 touchpoints; baseline report 4 Nov 2026. RAGAS/faithfulness, answer status, OCR accuracy need GCP |
| P8 | Integration, UI, demo hardening | 🟡 | Slices 1–2 done: sandbox + assist API, and Vite + React + TS screens (sign-in, file list, file inner page with C2-24 Assist, advance search) — TP2, TP3, TP4, TP8, TP9, TP10, TP11, TP15 usable in the browser; remaining core touchpoints next (ADR-0012) |
| P9 | Buffer, dry-run, stretch | ⬜ | |

## 2. Milestones

| # | Milestone | Done when | Status | Date |
|---|---|---|---|---|
| M1 | Foundation ready | GCP + IAM, Cloud SQL + graph store, canonical ID scheme + draft hierarchy, synthetic corpus + manifest, authz approach chosen, decision log opened | 🟡 | |
| M2 | Ingestion + updates | Any format → extracted, classified, canonical IDs, relations → gated → indexed; new doc reconciles supersession | ⬜ | |
| M3 | Permission-aware ladder | Two officers, same query, correctly different candidate sets on every rung | ⬜ | |
| M4 | First cited answer | "Has this been decided before?" → cited precedent from the evidence package | ⬜ | |
| M5 | Temporal + conflict | As-of-date correct; precedence correct; all 7 conflict types flagged with evidence | ⬜ | |
| M6 | Agents + noting + memory + HITL | Multi-turn works; draft noting uses prior precedent; officer approves | ⬜ | |
| M7 | Verified, audited, tracked | Citations pass verifier; every request + human action logged; cache respects scope | ⬜ | |
| M8 | Harness green | Leakage matrix = 0; ladder, ID, injection, memory-scope suites pass | ⬜ | |
| M9 | Demo-ready | Two-officer golden path runs clean inside the mock e-Office sandbox at all core touchpoints | ⬜ | |
| M10 | Locked + rehearsed | Extended touchpoints working; demo rehearsed; masked data validated if it arrived | ⬜ | |

## 3. Current phase checklist — P0

- [x] Problem statement selected and assigned (C2-24)
- [x] Implementation plan v4 written
- [x] Implementation plan Final (v5) — adds mock e-Office integration demo (plan §11); PDF in `docs/`
- [x] Define mock e-Office data model + EOfficeConnector interface (plan §11.2–§11.3) (2 Nov 2026; ADR-0009 proposed)
- [x] Deep Dive exercise submitted (27 Sep 2026)
- [x] Solution Design Document — final version (13 Oct 2026); mentor review: Ready for Development
- [x] Mock corpus v1: 29 documents, manifest, users, access matrix, relations, conflict key, 24 golden questions
- [x] Canonical ID format drafted (used in mock corpus) — confirm against real numbering
- [x] Draft instrument hierarchy (9 levels) — confirm with department
- [x] Repository skeleton in this folder (backend / frontend / data / evaluation / docs): git init, module packages, uv toolchain, ruff/mypy/pytest, Makefile, Dockerfile (22 Oct 2026)
- [x] Copy mock corpus into `data/synthetic/` → `data/synthetic/mock_v1/` (22 Oct 2026)
- [x] Versioned config: `data/ontology/{hierarchy,classification}.yaml`, `backend/config/runtime.yaml` (thresholds uncalibrated) (22 Oct 2026)
- [x] GCP setup kit ready (`infrastructure/gcp/`, dry-run verified; not run against a real project) (22 Oct 2026)
- [ ] Local docker-compose stack verified (Docker daemon not running on 22 Oct 2026)
- [~] Extend mock corpus with e-Office objects (plan §11.6): **done 3 Nov 2026** — profiles (8 + 2 staff posts), 13 e-files, 36 Green notes, 25 movements, 3 correspondence items, 10 receipts (`data/synthetic/mock_v1/eoffice/seed.json`, generator `data/synthetic/tools/build_eoffice_seed.py`); **open** — Yellow-note versions, DFA drafts, file links, Previous/Later References (need touchpoint scenarios to define them)
- [x] Add touchpoint scenarios to the golden dataset (plan §11.5, §13.2): 17 scenarios covering all 13 core touchpoints in `data/synthetic/mock_v1/ground_truth/touchpoint_scenarios.json` (status: draft — owner review), consistency-tested (3 Nov 2026). Extended touchpoints (1,5,12,16–19) not yet
- [x] Decision records written for key decisions (`docs/decisions/0001`–`0004`)
- [x] `.gitignore` added (excludes local env `aenv/`, secrets, caches)
- [ ] GCP project access + IAM + service accounts (⛔ access pending; scripts ready: run `infrastructure/gcp/` per its README)
- [x] Cloud SQL schema for access: `data/schemas/authz.sql` (tuples, audit log, document locations, RLS policy) — syntax-checked, not applied (no GCP) (3 Nov 2026)
- [x] Authorization spike: `compute_scope` + `can_access` passing the mock access matrix (232/232, 2 Nov 2026)
- [x] Decision log opened (`docs/decisions/`) — ADR template added
- [x] Agent harness: CLAUDE.md v2.0 (merged contract), AGENTS.md, docs/LEARNINGS.md
- [x] Requirements freeze — mentor confirmed plan and changes satisfactory (13 Oct 2026)

## 4. Deliverables produced so far

| Date | Deliverable | Status |
|---|---|---|
| Sep 2026 | PS selection note (top 3) | ✅ Submitted |
| 27 Sep 2026 | Deep Dive exercise (C2-24) | ✅ Submitted |
| 1 Oct 2026 | Implementation Plan v4 | ✅ |
| 2 Oct 2026 | Mock corpus v1 + data guide | ✅ |
| 8 Oct 2026 | Solution Design Document (draft) | ✅ Superseded by final |
| 13 Oct 2026 | Solution Design Document — Final (mentor: Ready for Development) | ✅ Ready to submit |
| 13 Oct 2026 | Implementation Plan — Final (v5) with mock e-Office demo | ✅ Ready to submit |

## 5. Blockers & dependencies

| Item | Impact | Status | Workaround |
|---|---|---|---|
| GCP project access | M1 cloud items, any real-service integration test | ⛔ Waiting (22 Oct 2026) | Local foundation + fakes; setup kit ready in `infrastructure/gcp/` |
| Real (masked) department data | Validation on real formats | ⛔ Waiting | Build and measure on synthetic corpus |
| Real classification / access model | Authorization policy details | ⛔ Waiting | Mock model (8 officers, 4 grades) |
| Supersession recording practice | Extract vs infer relations | ⛔ Waiting | Support both; infer → human confirm |
| Mentor review of SDD | Requirements freeze | ✅ Done 13 Oct 2026 — "plan looked good… changes satisfactory" | — |

## 6. Open questions

- [ ] Real classification levels, role hierarchy, who may see which file
- [ ] How supersession is recorded; numbering conventions; instrument hierarchy confirmation
- [ ] Approval authorities for notings and supersession confirmations
- [ ] Volume, Telugu share, how new documents arrive
- [ ] Deployment expectation and any hosting constraints
- [ ] GCP region / data residency: proposed `asia-south1`; Document AI processor locations may force `us`/`eu`. Confirm with CoE/department
- [ ] Accept ADR-0005 (toolchain: Python 3.13, uv, optional cloud extras)
- [ ] ⏰ **Reminder (owner asked, 2 Nov 2026):** before graph / auth / e-Office work relies on `data/ontology/roles.yaml`, re-check the officer hierarchy and research it deeply (department RTI 4(1)(b) disclosures, org charts, department confirmation) — ADR-0008
- [ ] Accept ADR-0006 (public G.O. corpus alongside synthetic data; `data_collection/` folder; corpus stays outside the repo)
- [ ] ⏸ **Owner rule (3 Nov 2026): no crucial decisions from mock data — finalise once real data arrives.** Deferred until then: rank threshold and scope mapping in `access_policy.yaml`, classification levels, officer roles/hierarchy (ADR-0008), instrument precedence, mock_v1 memo-ID migration (left as-is, `lookup_keys` fallback)
- [ ] Owner (when real data arrives): status-coverage ceiling — keep `full_department` (strict: status only for officers who can see the issuing department's records at every classification) or switch to `up_to_document` (assumes an order is only changed by records no more restricted than itself) in `access_policy.yaml`
- [ ] Wire the collision registry into `data_collection/` (collisions currently go to `_review`) — when collection leaves test phase
- [ ] Public corpus: 6 issue dates in `staging/manifests/date_review.csv` to check
- [x] Conflict type C approach — owner chose option A (4 Nov 2026): rules in config from mock orders, swap for real rules later (ADR-0010)
- [ ] Before type-C results are relied on: collect authoritative, current approval rules per department and action (thresholds, effective dates, amendments), set `status: verified`, declare verified + complete coverage with who/when (owner condition, ADR-0010). Until then mock rules are testing only
- [ ] Whether a sandbox or authorised export from the real e-Office can be provided later, and through which path (file export or official API)

## 7. Decisions log (short)

| Date | Decision | Why |
|---|---|---|
| Sep 2026 | Modular monolith (FastAPI on Cloud Run) | PoC scale; module boundaries kept |
| Sep 2026 | Vertex AI Search for hybrid retrieval | Vector + keyword with metadata filters in one product |
| Sep 2026 | Spanner Graph behind GraphRepository | Multi-hop chains; swappable if fewer stores preferred |
| Sep 2026 | Postgres tuples for authz (simple-first) | Same interface; harden to SpiceDB/OpenFGA later |
| 1 Oct 2026 | Retrieval ladder + templates (v4) | Reproducible, cheaper, smaller attack surface |
| 2 Oct 2026 | Classification names follow CSMOP order | Unclassified < Restricted < Confidential < Secret |
| 5 Oct 2026 | Start building on synthetic data | Don't wait for real data |
| 22 Oct 2026 | ADR-0005 (Proposed): Python 3.13 + uv, cloud SDKs as optional extras, gcloud scripts not Terraform | Build locally while GCP access is pending |
| 2 Nov 2026 | ADR-0008 (provisional): officer roles + reporting hierarchy for FIN01/GAD01/ESE01 in `data/ontology/roles.yaml`, grounded in official sources + corpus evidence | Graph, file movement and access scopes need it now; confirm later |
| 22 Oct 2026 | ADR-0006 (Proposed): public G.O. corpus alongside synthetic data; collection code in `data_collection/`, corpus outside the repo | No department data will arrive; start real collection when GCP access arrives |
| 22 Oct 2026 | ADR-0007 (Proposed): memo/gazette ID forms; ID collisions → review; printed date used only when corroborated | Real records showed cases the base ID format and archive dates don't cover |
| 4 Nov 2026 | Status-coverage refinement: what the officer's own records establish may be stated without full coverage (superseded / repealed by a visible order, expired on its own end date); "in force" and "which version is current" still need full coverage (CURRENT_UNCONFIRMED otherwise). Pre-send type A stays as is | Owner, answering the TP10/TP11 question; hidden records still change nothing in any answer |
| 4 Nov 2026 | ADR-0012: P8 API first; Vite + React + TS screens; simulated sign-in header (sandbox only); sandbox.yaml demo thresholds labelled uncalibrated; connector `documents()` added | Owner chose API first and the Vite stack |
| 4 Nov 2026 | Conflict types B, D, G wait for GCP: no deterministic pre-check or mocked judgment before Gemini is available | Owner choice; plan §6.2 has Gemini make these judgments from the authorised evidence |
| 4 Nov 2026 | ADR-0011: ingestion may fill the department from the source system's tag only when the text names none; `department_source` recorded; text/tag disagreement → review (DEPARTMENT_MISMATCH) | Owner: the tag is recorded metadata, not a guess; department feeds compute_scope |
| 4 Nov 2026 | ADR-0010 conditions: mock rules are testing only; three outcomes (conflict / no conflict in a verified complete rule set / review needed); unverified → uncertain flags with caveat; a mock file cannot claim verified coverage | Owner: "no matching rule" must not look like approval when the rule was simply not collected |
| 4 Nov 2026 | ADR-0010: type C from approval-authority rules in config (mock content from corpus orders, clause-cited, date-bounded); deterministic; cites only visible sources | Owner chose option A: build now, swap rules later |
| 3 Nov 2026 | Status coverage: report an order's status only when the officer's scope covers every record that could change it; otherwise "I can't confirm this order's current status from the records available to you. Please check with the section." Decided from the scope only, never from which records exist | Owner: neither "in force from a partial record set" nor a warning that appears only when a hidden successor exists |
| 3 Nov 2026 | Citation outcomes: CONFIRMED (shown) · REVIEW_NEEDED (separate labelled section, never as fact; all-ambiguous → review evidence + caveat) · REJECTED (removed: uncited, invented, unauthorised, wrong record, contradicts native text). A mismatch against OCR'd/incomplete text is REVIEW_NEEDED, not REJECTED | Owner decision with guardrail: an uncertain claim is never presented as confirmed |
| 3 Nov 2026 | Department-less references: look up every department's candidate inside the scope; one → use, several → ask the officer (only visible choices), none → not found | Owner approved; never assume the officer's own department |
| 3 Nov 2026 | ADR-0007 collision rule: section-code suffix when it distinguishes, else persistent registry `-Cnn` tied to source identity; first record keeps the bare ID; bare-ID lookup → ambiguous | Stable, informative IDs; no order-dependent suffixes |
| 3 Nov 2026 | Owner rule: crucial decisions are not taken on mock data; finalise with real data | Mock corpus is synthetic |
| 3 Nov 2026 | ADR-0007 accepted; ADR-0009 accepted with owner decisions: rank AND search scope, grants in an access store read per request, shared cache for identical permissions | Problem statement asks for real access controls enforced during retrieval |
| 2 Nov 2026 | ADR-0009 (Proposed): policy params in `access_policy.yaml` (mock), scope + re-check as two code paths, scope signature without user ID, connector contract, memo date tag off until ADR-0007 | P0 authz spike + connector without GCP |
| 13 Oct 2026 | Demo inside a mock e-Office sandbox via EOfficeConnector | No live e-Office access; shows integration honestly; real adapter can replace mock |

## 8. Session log

| Date | Work done | Next |
|---|---|---|
| 10 Oct 2026 | Project folder set up; plan and progress tracker added | Repo skeleton + mock corpus into `data/synthetic/` |
| 10 Oct 2026 | Agent harness added: CLAUDE.md (rules), AGENTS.md, docs/LEARNINGS.md, ADR template | Repo skeleton + mock corpus into `data/synthetic/` |
| 10 Oct 2026 | CLAUDE.md v2.0: merged owner harness (source priority, forbidden substitutions, cache/session rules, ledger + response format, fresh-repo protocol); task ledger section added | Gap report + smallest P0 slice |
| 13 Oct 2026 | Final implementation plan (v5): mock e-Office sandbox chapter §11 (20 touchpoints, connector, access mapping), sections renumbered 11→16; PDF in docs/; CLAUDE.md §2.4 added | Gap report + smallest P0 slice |
| 13 Oct 2026 | Final Solution Design Document generated with mentor review recorded (Ready for Development; no changes required); PDF in docs/ | Gap report + smallest P0 slice |
| 13 Oct 2026 | Cross-check of all project files against the final plan: CLAUDE.md eval suite + P8 updated, PROGRESS checklist extended (e-Office seed data, touchpoint scenarios), LEARNINGS updated, ADRs 0001–0004 added, .gitignore added | Gap report + smallest P0 slice |

| 22 Oct 2026 | Local foundation while GCP access is pending: git init, module skeleton, uv toolchain (all extras resolve on 3.13), config + tests, mock corpus into data/synthetic, local compose stack, Dockerfile, GCP setup kit + runbook, gap report, ADR-0005 | Mock e-Office data model + EOfficeConnector interface, or Cloud SQL schema + authz spike |
| 22 Oct 2026 | Data-collection tools integrated from `c2-24-data-tools` into `data_collection/` (data root via `local.env`), notes into `docs/data_collection/`, GCS upload script `08_upload_public_corpus.sh`, ADR-0006/0007 | Owner: create `data_collection/.venv`, run `make check`; accept ADR-0006/0007 |

| 2 Nov 2026 | Without GCP/data: authz spike (232/232 matrix), canonical-ID parser + reference resolver, temporal engine (as-of, chain, precedence), e-Office data model + EOfficeConnector + mock adapter, deterministic conflict A/E/F; 13 → 379 tests; ADR-0009 | Owner: ADR-0009 questions, `make check` on the Mac; next: e-Office seed data, Cloud SQL DDL, GraphRepository in-memory |

| 3 Nov 2026 | Owner decisions applied: ADR-0007 accepted (memo date tag on, `lookup_keys` fallback); access store with tuples; rank AND search-scope policy; scoped L0/L1 retrieval with re-check; shared answer cache; Cloud SQL `authz.sql` (parsed OK); 379 → 637 tests | e-Office seed data; owner: collision suffix rule, mock_v1 memo-ID migration |

| 3 Nov 2026 | Collision registry per owner rule (`identifiers/collisions.py`, 26 tests); ADR-0007 updated; mock-data decision freeze recorded; 637 → 663 tests | e-Office seed data; graph store |

| 3 Nov 2026 | e-Office seed from mock corpus v1 (fields per NIC eFile 7.0 manual; authors by post; no answer keys; scanned notes without text), `load_seed`/`adapter_from_seed`; 663 → 675 tests | Touchpoint scenarios (core) → then Yellow notes/drafts/links in the seed; in-memory graph store |

| 3 Nov 2026 | Core touchpoint scenarios (17, all 13 core touchpoints) in ground truth; tested against access matrix, seed, conflicts, golden questions; 675 → 731 tests | Owner review of scenarios; in-memory graph store (L3) |

| 3 Nov 2026 | GraphRepository Protocol + in-memory reference with scope-constrained walk; L3 `expand` (store scope, seed + hit re-check, no guessed hop limit); leakage matrix over every officer × authorised seed; 731 → 813 tests | Evidence package + citation verifier schemas |

| 3 Nov 2026 | Evidence package (re-checked spans, fenced untrusted rendering) + deterministic citation verifier (fabricated/revoked → rejected, unsupported → withheld, none verified → no-answer); 813 → 831 tests | Owner decided: show needs-review claims flagged |

| 3 Nov 2026 | Verifier: needs-review claims shown flagged (owner); ladder orchestration L0→L1→L2→L3 with early exit + trace, `HybridRetriever` Protocol + keyword stand-in; golden ladder levels Q01/Q02/Q03/Q05/Q15 met; 831 → 848 tests | Department-less references (Q18) — cross-department candidates; then agents' AgentState / intent templates |

| 3 Nov 2026 | Verifier rebuilt to owner's CONFIRMED / REVIEW_NEEDED / REJECTED rule; Q18 fixed (cross-department lookup, asks when ambiguous); typed AgentState + 7 intent templates checked against 9 golden questions; 848 → 885 tests | Owner: golden ladder labels for Q04/Q20 (L1+L3) vs Q03 (L1); next: bounded agent tools (plan §5.6) + conversation-memory scope rules |

| 3 Nov 2026 | Six bounded agent tools behind `call_tool` (validated args, re-check inside, absent = forbidden); session memory keyed by (user, session), IDs only, scope re-applied on recall; 885 → 918 tests | Owner: restricted-superseder status rule; next: P1 ingestion pieces that need no GCP (format detection, confidence gate, review queue) |

| 3 Nov 2026 | Ingestion: content-based detection (all 29 corpus files routed as the manifest says), confidence gate (uncalibrated → every OCR extraction to review), review queue with reviewer identity; new dependency pypdf 6.21.4 (lock updated with uv 0.9.28, only pypdf added); 918 → 961 tests | Native extractors (PDF text, DOCX, XLSX) + document-type classification from text |

| 3 Nov 2026 | Status-coverage rule (owner) in `check_document_status` / `get_current_rules`: `Scope.covers_status_domain`, policy `status_coverage` (strict default), generic message; identical outcome with/without a hidden successor for every officer × visible document; 961 → 970 tests | Owner: coverage ceiling with real data; next: native extractors + classification |
| 3 Nov 2026 | Owner verification run (agent-executed): `make setup` (pypdf 6.21.4), `make check` → ruff clean, mypy 71 files clean, 970 passed / 1 warning (Starlette httpx deprecation), 72 files formatted; seed `--check` up to date; `/healthz` ok; 6 targeted suites 682 passed; `data_collection/.venv` created, tools compile OK, venv + `local.env` git-ignored. Note: `make setup` drops the optional extras (`make setup-all` restores) | Nothing committed yet: owner to decide on first commit |

| 3 Nov 2026 | Native extraction + type/metadata/relation extraction: on all 22 readable corpus files, dates 22/22, own IDs 15/15, types 21/22 (D28 has no draft marker), every in-corpus relation found; two real bugs found and fixed (DOCX line breaks lost; a citation could swallow the next reference's date); 970 → 1032 tests | Push to GitHub later (owner); next: ingestion pipeline (detect → extract → gate → metadata → review/index) as one idempotent job |

| 3 Nov 2026 | Ingestion job: whole mock corpus ingested — 21 indexed, 8 held (7 scans/photos + mixed D15 awaiting OCR); IDs match; graph = every explicit in-corpus edge, no extras; temporal status from ingested facts; idempotent re-run, duplicate bytes from a 2nd source = same document, new bytes = new version (old kept), out-of-order supersession attaches later, cache invalidated, classification-mark mismatch held, collision → `-HRIII`; 1032 → 1047 tests | Next: file-index matching for note→file citations; then reconciliation of open files when a superseding order arrives (plan §7.2, touchpoint 4) |

| 3 Nov 2026 | Reconciliation: note→file citations linked by date (D20→D21), inferred supersession (exact subject match, no threshold) → review + unconfirmed edge, open-file notices filtered per officer; TP04 replay passes; seed file state from corpus status (decided → closed); TP04 scenario corrected to plan §7.3 (explicit = set directly); 1047 → 1054 tests | Owner: scenario correction noted; next: conflict type C from approval-authority rules — needs a decision on the rule source (mock vs wait for real data) |

| 4 Nov 2026 | Conflict type C: `authority_rules.yaml` (6 rules, clause-cited) + `check_authority`; answer key met for D27/D28/D29, clean D19/D24/D25; ADR-0010; 1054 → 1073 tests | Next: proposal-fact extraction for C from note text (deterministic patterns), then the evaluation harness |

| 4 Nov 2026 | Type C coverage states per owner conditions: `coverage` in rules file, `AuthorityResult` (CONFLICT / NO_CONFLICT_VERIFIED / REVIEW_NEEDED), caveat on unverified flags, mock cannot claim verified coverage; 1073 → 1082 tests | Next: proposal-fact extraction from note text, then the combined pre-send check A/C/E/F |

| 4 Nov 2026 | Proposal facts from note text (action, post level, amount, proposed authority, concurrences — with evidence and gaps); pre-send check A/C/E/F + status coverage; D27/D28/D29 deterministic conflicts all found (except D27's F, known gap); clean draft = review needed with mock rules, clear only with verified rules; 1082 → 1094 tests | Next: evaluation harness running golden questions + touchpoint scenarios end to end on the reference stack |

| 4 Nov 2026 | Evaluation harness (`evaluation/`): corpus built by the ingestion job, 24 golden questions, pre-send conflicts A–G, leakage matrix over 8 paths × 8 officers, touchpoints; baseline: 0 disclosures / 1062 checks, Recall@10 0.561, MRR 0.684, ladder-level 0.579, A/C/E/F P 1.00 R 0.71; `make eval`; 1094 → 1099 tests | Owner: run `make check` + `make eval` on the Mac; next: fix the pipeline gaps the baseline found (base-ID lookup of dated memos, 'G.O.Ms.No.31 of 2025', missing subjects, validity end dates), re-run and compare |

| 4 Nov 2026 | Baseline gaps fixed (dated-memo lookup by base number, 'G.O.Ms.No.31 of 2025', order end dates from subjects, missing subjects, D11 department via ADR-0011); eval vs baseline: Recall@10 0.561 → 0.754, MRR 0.684 → 0.833, A/C/E/F recall 0.714 → 0.857, leakage still 0; 1099 → 1109 tests | Next: clause-level effective windows for D27's type F, then Telugu metadata (D16) |
| 4 Nov 2026 | First commits + push to GitHub (private repo `VENKATCHINTHAKINDI01/Project_C2-24`, branch `main`): `44c8edb` first commit · `0d48585` repo · `729ee75` docs · `3358551` data · `cce70f7` data_collection · `e05aad0` backend · `89ba0bb` progress; 256 files, no secrets/env/venv staged; checks before commit: `make check` 1109 passed, eval 0/1126 disclosures | Continue from the after-gap-fixes known gaps; commit each task as one logical change |

| 4 Nov 2026 | Action windows read from order clauses (G.O.Ms.31/2025 para 2(i)) → type F on the proposal date; eval: A/C/E/F recall 0.857 → 1.000, touchpoints 6/6 run pass, leakage 0; reports never overwritten; 1109 → 1119 tests | Next: Telugu metadata (D16), then B/D/G approach with the owner |

| 4 Nov 2026 | Committed and pushed: `34a8555` evaluation: never overwrite an existing report · `5162c59` conflict: type F from action windows (incl. `2026-11-04-baseline-2` report); Mac: 1119 passed, eval exit 0, recall A/C/E/F 1.000 | Owner: B/D/G wait for GCP. Next: Telugu metadata (D16) |

| 4 Nov 2026 | Telugu order headers: D16 resolves (Rc.No., date tag, subject, reference to G.O.Ms.27/2024); all 29 corpus documents indexed; leakage 0 / 1142; Q06/Q19 unchanged (Telugu-only subject; keyword stand-in) — needs multilingual retrieval on GCP; 1119 → 1124 tests | Next: owner pending items, or start the sandbox screens (P8) |

| 4 Nov 2026 | P8 slice 1: sandbox + assist API in FastAPI (simulated sign-in, file pages, TP10/TP11/TP15, drafts only, audit); HTTP leakage sweep 0; ADR-0012; 1124 → 1138 tests | Owner: TP10 vs TP11 status-coverage question. Next: React screens (slice 2) |

| 4 Nov 2026 | Sandbox API committed and pushed as `92ae228` (Mac: 1138 passed, curl checks OK). Owner refinement: status lookup states supersession by a visible order without claiming the current version; 1138 → 1139 tests | Next: P8 slice 2, the React screens |

| 4 Nov 2026 | Status fix committed as `7726b23`. P8 slice 2: sandbox screens (Vite + React + TS) — sign-in, file list, file page with C2-24 Assist (pre-send, reference, Insert as Yellow Note), search; checked in a real browser; garbled Telugu subject line fixed; 1139 → 1140 backend tests, 8 frontend tests | Next: TP8 "file so far" and the other core touchpoints |

| 4 Nov 2026 | TP8 "file so far" (deterministic note chain, gaps named, sources) in API, eval (TP08 PASS, 7 touchpoints) and the Assist panel; HTTP sweep found and the fix closed a file-classification gap on assist calls; 1140 → 1149 backend tests, 9 frontend tests | Next: TP9 link file |

| 4 Nov 2026 | TP9 link file: precedent files in scope, grouped by file, "Suggest link" → suggested-reference draft; eval TP09 PASS (8 touchpoints); sweep 0; 1149 → 1150 backend tests, 10 frontend tests | Next: TP2/TP3 receipt inbox and Put in a file |

| 4 Nov 2026 | Screens + TP8 committed as `4febd3d`. Frontend dev tools bumped for npm audit findings: vite 6.4.5, vitest 4.1.12 → 0 vulnerabilities; checks and browser flows re-run | Next: TP2/TP3 |

| 4 Nov 2026 | TP9 + dev-tool upgrade committed as `1d77433`. TP2/TP3: receipt inbox, two-line summary, validity flags (order + what it cites), put-in-a-file never forced; shared citation review; wrapped-date extraction fix; eval 11 touchpoints pass; 1150 → 1154 backend tests, 11 frontend tests | Next: TP4 received letters |

| 4 Nov 2026 | TP4 received letters: connector events → runtime sync → reconciliation → per-officer open-file notices; sandbox replay (`C2_SANDBOX_REPLAY=tp04`) with "Letter arrives"; eval TP04 PASS (12 touchpoints); 1154 → 1155 backend tests, 12 frontend tests | Next: TP13 senior brief |

## 8a. Gap report (CLAUDE.md §14), 22 Oct 2026

| Phase / milestone | Status | Evidence |
|---|---|---|
| P0 / M1 | PARTIAL | Done: plan, ADRs 0001–0005, corpus in `data/synthetic/mock_v1`, canonical ID format + draft hierarchy (config), repo + toolchain, 13 unit tests green. Missing: GCP + IAM (blocked), Cloud SQL schema, authz spike, e-Office data model + EOfficeConnector, e-Office seed data, touchpoint scenarios |
| P1 / M2 | NOT_STARTED | `backend/app/ingestion` etc. are empty packages |
| P2 / M3 | NOT_STARTED | `backend/app/auth` empty |
| P3 / M4 | NOT_STARTED | `retrieval`, `graph`, `citation` empty |
| P4 / M5 | NOT_STARTED | `temporal`, `conflict` empty |
| P5 / M6 | NOT_STARTED | `agents`, `noting`, `memory`, `hitl` empty; langgraph locked as optional extra |
| P6 / M7 | NOT_STARTED | `audit`, `tracking`, `cache` empty |
| P7 / M8 | NOT_STARTED | `evaluation/` placeholder only; eval-integrity guard test exists |
| P8 / M9 | NOT_STARTED | `frontend/` not scaffolded |
| P9 / M10 | NOT_STARTED | — |

Runtime facts: Python 3.13.9 (uv, `backend/.venv`), Node 24.5, uv 0.9.28, Docker installed (daemon off), gcloud not installed. Dependency versions are in `backend/uv.lock`.

## 9. Task ledger

Format per CLAUDE.md §12. Status: `NOT_STARTED` · `IN_PROGRESS` · `BLOCKED` · `DONE`. Newest first.

### 2026-11-04 · P8 / M9 · Touchpoint 4: received letters (order arrives → open-file notices)
- **Status:** DONE
- **Plan section:** §11.3 ("Events in"), §11.5 touchpoint 4, §7.2–§7.3 (reconciliation; explicit supersession applied directly), §5.4 (notices per officer); ADR-0012 update
- **Files changed:** `backend/app/connectors/eoffice.py` (`open_files()`), `backend/app/eoffice_mock/adapter.py` (replay holdback, `letter_pending`, `letter_arrives` → `ORDER_RECEIVED`), `backend/app/eoffice_mock/routes.py` (`POST /sandbox/receipts/{no}/arrive`, `letter_pending`), `backend/app/agents/runtime.py` (ingestion refactored into `_ingest`; `open_files` passed to reconciliation; `sync(connector)` ingests new events; L2 re-indexed), `backend/app/agents/routes.py` (`GET /assist/notices`), `backend/app/config.py` (`sandbox_replay`), `backend/app/main.py` (replay wiring; sandbox event → `runtime.sync`), `backend/config/sandbox.yaml` (`replays.tp04`), new `backend/tests/unit/test_sandbox_replay.py`, `backend/tests/unit/test_sandbox_api.py` (sweep covers notices), `evaluation/harness/{stack,suites}.py` (holdback + arrivals; TP04 scenario), new `evaluation/reports/2026-11-04-received-letters.{md,json}`, frontend `types.ts`, `api.ts`, `components/Receipts.tsx` (notices panel; "Letter arrives (sandbox replay)"), `styles.css`, `render.test.tsx`, `docs/decisions/0012-…md`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** backend: ruff ✅ · mypy strict (107 files) ✅ · `pytest -q` → 1155 passed ✅ · `run_eval.py --label received-letters --compare …receipts.json` → exit 0. Frontend: `tsc` ✅ · Vitest 12 passed ✅ · build ✅. Browser (`C2_SANDBOX_REPLAY=tp04`): U02 → inbox shows no updates → receipt 2/2025/ESTT.I → "Letter arrives" → notice "G.O.Ms.31/2025 supersedes G.O.Ms.88/2022 · open file USD01-12/19/2026-ESTT.I" → inbox shows it → U03 sees no updates; no console errors
- **Acceptance evidence:** TP04 PASS on the eval stack (replay of the scenario's held-back records; notice lists exactly Computer No. 2894562, not the Vigilance file; 88/2022 flips to superseded); **touchpoints passed 11 → 12**; other metrics unchanged; leakage 0 / 1142; HTTP sweep covers notices for every officer → 0. Replay test: nothing before arrival; Works officer cannot trigger the arrival (404); after arrival U01/U02 see the notice, U03/U07 see nothing; status lookup now says superseded by 31/2025; a letter arrives only once
- **Security / temporal:** notices pass through `notices_for` (both orders and each affected file re-checked per officer); explicit supersession is applied directly, inferred ones would wait in the review queue (plan §7.3); ingestion on arrival invalidates cached answers touching the changed order
- **Blocker / decision needed:** none
- **Exact next action:** TP13 senior brief (approval brief: proposal, governing rule, precedent, flags, movement) — deterministic parts from what exists (file so far + pre-send + link suggestions)

### 2026-11-04 · P8 / M9 · Touchpoints 2–3: receipt inbox and Put in a file
- **Status:** DONE
- **Plan section:** §11.2 (Receipt), §11.5 touchpoints 2 and 3, §6.4 (types A/E/F), status-coverage rule; ADR-0012 update
- **Files changed:** new `backend/app/agents/receipts.py` (`review_receipt`), new `backend/app/conflict/citations.py` (`review_citations`, shared with the pre-send check), `backend/app/conflict/presend.py` (uses it; cited IDs still matched only against visible records), `backend/app/agents/routes.py` (`POST /assist/receipt`), `backend/app/connectors/eoffice.py` (`ReceiptContext`, `receipt_context`), `backend/app/eoffice_mock/{adapter,routes}.py` (receipts, inbox, `/sandbox/receipts[/{no}]`), `backend/app/ingestion/metadata.py` (a date broken after its hyphen joins without a space), `backend/app/updates/reconcile.py` (`norm_subject` public), tests `test_sandbox_api.py` (TP02, TP03, inbox, sweep covers receipts), `test_baseline_gap_fixes.py` (wrapped date), `evaluation/harness/suites.py` (TP02-a, TP02-b, TP03), new `evaluation/reports/2026-11-04-receipts.{md,json}`, frontend `types.ts`, `api.ts`, `App.tsx`, `components/{TopBar,Receipts}.tsx`, `styles.css`, `render.test.tsx`, `docs/decisions/0012-…md`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** backend: ruff ✅ · mypy strict (106 files) ✅ · `pytest -q` → 1154 passed ✅ · `run_eval.py --label receipts --compare …link-file.json` → exit 0. Frontend: `tsc` ✅ · Vitest 11 passed ✅ · build ✅. Browser: U01 → Receipt inbox (10 receipts) → G.O.Rt.1184 receipt → F on the order itself and F on the 2024 circular it cites → memo receipt as of 21-05-2025 → no validity flag, "open a new file", 2629410's file listed as related only; no console errors
- **Acceptance evidence:** TP02-a, TP02-b and TP03 PASS on the eval stack (docs, flags exactly as the answer keys; TP03 never forces a match and lists the named file as related); **touchpoints passed 8 → 11**; all other metrics unchanged; leakage 0 / 1142; HTTP sweep now also covers every receipt and receipt page for every officer → 0
- **Bugs found and fixed on the way:** (1) G.O.Rt.1184's PDF wraps a cited date ("Dt.27-" / "03-2024") so the circular lost its date tag — fixed at extraction with a regression test; (2) a receipt's letter reference without a year ("G.O.Rt.No.1184") now uses the diarised letter date — recorded metadata, not a guess; (3) the shared flag wording said "the proposal is dated" — receipts now say "as of"
- **Security:** receipts follow e-Office reach (section / department / global scope); unknown and unreachable receipts give the same 404; the citation review's ID matching stays limited to visible records (checked while extracting it)
- **Blocker / decision needed:** none
- **Exact next action:** TP4 — received letters: an incoming order that supersedes an existing one, the open files citing the old order (reconciliation + notices already exist), queued for confirmation

### 2026-11-04 · P8 · Frontend dev-tool security update (vite 6.4.5, vitest 4.1.12)
- **Status:** DONE
- **Plan section:** CLAUDE.md §11.8 (dependencies), ADR-0012 update
- **Files changed:** `frontend/eoffice/package.json` (vite 5.4.11 → 6.4.5, vitest 2.1.8 → 4.1.12, `overrides: {vite: 6.4.5}`), `frontend/eoffice/package-lock.json` (regenerated), `frontend/eoffice/vite.config.ts` (`defineConfig` from `vitest/config`), `docs/decisions/0012-…md`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Why:** the owner's `npm audit` on the Mac reported 5 advisories (2 critical) in the dev/test tools: dev-server request forgery and `server.fs.deny` bypasses (vite ≤ 6.4.3/6.4.4), esbuild dev server (≤ 0.24.2), tinypool and @vitest/mocker code-execution gadgets (vitest ≤ 4.1.10/4.1.11). Dev-only; the static build ships none of it. `npm audit fix --force` was not used
- **Tests/commands run:** Linux container, Node 22: `npm ci` ✅ · `npm audit` → **0 vulnerabilities** ✅ · `tsc --noEmit` ✅ · Vitest 10 passed ✅ · `vite build` ✅ · browser flows (U03 Link file, U05 File so far) through the vite 6.4.5 dev-server proxy ✅, no console errors
- **Choice of versions:** oldest releases outside every advisory range and at least two weeks old (vite 6.4.5 published 21 Oct 2026; vitest 4.1.12 published 15 Oct 2026). npm's own suggestion (vite 5.4.21, vitest 2.1.9) is still inside the advisory ranges
- **Blocker / decision needed:** none
- **Exact next action:** TP2/TP3 — receipt inbox and Put in a file

### 2026-11-04 · P8 / M9 · Touchpoint 9 "link file"
- **Status:** DONE
- **Plan section:** §11.5 touchpoint 9, §8 (precedent), §11.1 (drafts only)
- **Files changed:** new `backend/app/precedent/links.py` (`suggest_links`: precedent lookup on the open file's subject through the scoped ladder, open file dropped, hits grouped by e-File), `backend/app/precedent/__init__.py`, `backend/app/agents/routes.py` (`POST /assist/link-suggestions`, via `open_file`), `backend/tests/unit/test_sandbox_api.py` (TP09 test; sweep covers link suggestions), `evaluation/harness/suites.py` (TP09 scenario), new `evaluation/reports/2026-11-04-link-file.{md,json}`, `frontend/eoffice/src/{types,api}.ts`, `src/components/{AssistPanel,FilePageView}.tsx` ("Link file", "Suggest link" → suggested-reference draft; drafts labelled by kind), `src/styles.css`, `src/render.test.tsx`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** backend: ruff ✅ · mypy strict (104 files) ✅ · `pytest -q` → 1150 passed ✅ · `run_eval.py --label link-file --compare …file-so-far.json` → exit 0. Frontend: `tsc` ✅ · Vitest 10 passed ✅ · build ✅. Browser: U03 on the 2026 emergency-works file → Link file lists `USD01-WRKS0/52/2024-WORKS` and `USD01-WRKS0/18/2023-WORKS` with their notes, no Vigilance file → Suggest link creates a "Suggested link — draft" on the file page; no console errors
- **Acceptance evidence:** TP09 PASS on the eval stack (files 2003377 and 2447780, docs D24 and D25, none of the forbidden Vigilance files or documents); touchpoints passed 7 → 8; other metrics unchanged; HTTP leakage sweep (now including link suggestions for every officer and file) → 0; U01 on the Works file → 404
- **Finding (relevance, not access):** for the Deputy Secretary and Secretary the same request also lists the Vigilance drain-tender file and some Estt.I transfer files — they may see them, but the keyword stand-in matches on words like "drain". Semantic ranking with reranking (Vertex AI Search, GCP) is expected to fix this; not tuned on mock data
- **Blocker / decision needed:** none
- **Exact next action:** TP2/TP3 — receipt inbox (two-line receipt summary, "relates to file …", stale-circular flag) and Put in a file (existing file for the same subject)

### 2026-11-04 · P8 / M9 · Touchpoint 8 "file so far" + file-level clearance on every assist call
- **Status:** DONE
- **Plan section:** §11.5 touchpoint 8, §11.1 ("same access as e-Office, plus classification"), §5.4, §10.1
- **Files changed:** new `backend/app/noting/chain.py` (`parse_notes`, `file_so_far`: note number, paragraphs, signer, post, date, the note's own words, source; gaps named; last direction), `backend/app/agents/routes.py` (`POST /assist/file-so-far`; `open_file` = connector reach AND C2-24 check on the file's classification for presend, file-so-far and draft), `backend/app/agents/runtime.py` (`held_by_file`), new `backend/tests/unit/test_file_so_far.py`, `backend/tests/unit/test_sandbox_api.py` (TP08, clearance regression, sweep covers file-so-far), `evaluation/harness/suites.py` (TP08 scenario; expected gaps read from the answer key), new `evaluation/reports/2026-11-04-file-so-far.{md,json}`, `frontend/eoffice/src/{types,api}.ts`, `src/components/{AssistPanel,FilePageView}.tsx`, `src/styles.css`, `src/render.test.tsx`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** backend: ruff ✅ · mypy strict (103 files) ✅ · `pytest -q` → 1149 passed ✅ · `run_eval.py --label file-so-far --compare …telugu-headers.json` → exit 0. Frontend: `tsc` ✅ · Vitest 9 passed ✅ · build ✅. Browser: U05 opens the Vigilance file → File so far shows Notes #1–#3 with sources, Note #3 marked last direction, "1 more document … waiting for text review"; no mention of the SECRET report; no console errors
- **Acceptance evidence:** eval stack (scans transcribed): TP08 PASS — sources D21 + D22, gap "Notes #4–#5" named and not filled, last direction Note #8 "Approved. Issue charge memo."; touchpoints passed 6 → 7; all other metrics unchanged; leakage 0 / 1142. App (no OCR): Notes #1–#3 and a count of the one held scan the officer may see
- **Security finding fixed (found by the HTTP sweep):** assist calls on a file checked only e-Office reach, so an officer who could reach a file but was not cleared for its classification got a 200 with the file number (U01 on the CONFIDENTIAL D20 file; U04/U05 on the SECRET report's file). Every assist call on a file now also runs C2-24's access check on the file's classification and location; unknown, out of reach and not cleared give the identical 404. Regression test on all three endpoints. The pre-send check had the same gap (200 "no note to check" instead of 404) — fixed by the same change
- **Note for the owner:** as on the file page, "file so far" quotes an authorised note's own words, which can include another file's number (D20 cites the Vigilance file); the sweep checks what the assistant itself names
- **Blocker / decision needed:** none
- **Exact next action:** TP9 "link file" — precedent files within scope as read-only references (API + Assist panel), then TP2/TP3

### 2026-11-04 · P8 / M9 · Sandbox screens (slice 2): Vite + React + TypeScript
- **Status:** DONE
- **Plan section:** §11.1, §11.2, §11.5 (touchpoints 10, 11, 15; Insert as Yellow Note), Figure 4; ADR-0012
- **Files changed:** new `frontend/eoffice/` (`package.json` with exact versions + `package-lock.json`, `tsconfig.json`, `vite.config.ts` with API proxy, `index.html`, `src/{main,App}.tsx`, `src/{api,types,presend}.ts`, `src/styles.css`, `src/components/{Banner,SignIn,TopBar,FileList,FilePageView,AssistPanel,SearchPage}.tsx`, tests `src/{api.test.ts,render.test.tsx}`), `frontend/README.md`, `Makefile` (`fe-install`, `fe-dev`, `fe-check`), `backend/app/ingestion/metadata.py` (subject leaves out lines with lost glyphs), `backend/tests/unit/test_telugu_metadata.py`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **New dependencies (owner-approved stack, ADR-0012):** react 18.3.1, react-dom 18.3.1; dev: vite 5.4.11, @vitejs/plugin-react 4.3.4, typescript 5.6.3, vitest 2.1.8, @types/react 18.3.12, @types/react-dom 18.3.1 — exact pins, lock file committed
- **Tests/commands run:** frontend (Node 22 in the Linux container): `tsc --noEmit` ✅ · `vitest run` → 8 passed ✅ · `vite build` ✅ (156 kB JS, 4.5 kB CSS). Backend: ruff ✅ · mypy strict (101 files) ✅ · `pytest -q` → 1140 passed ✅ · eval `--no-write --compare …telugu-headers.json` → identical metrics. Browser run (Playwright against `uvicorn` + `vite`): sign in as U01 → open file 2894562 → Pre-send check shows A, E, F (uncertain), C (uncertain) with sources and the mock-rules / uncalibrated caveats → Insert as Yellow Note creates a draft shown in the noting panel → reference "G.O.Ms.No.88/2022" → superseded by G.O.Ms.31/2025, current version not claimed → advance search returns file numbers → sign in as U03 → only the three Works files; no console errors
- **Acceptance evidence:** banner on every screen (render test); the Assist panel shows "uncertain" badges, caveats and "Drafts only. Nothing is saved, signed or sent without the officer."; the Yellow Note body is the flags as numbered points with their sources (deterministic, no model text); "Send" runs only the pre-send check; unbuilt toolbar items are disabled with a tooltip
- **Fix found by looking at the screens:** G.O.Ms.31/2025's subject showed garbled Telugu (pypdf loses glyphs from that PDF's font, leaving NUL characters). Subjects now leave out lines with lost glyphs; regression test added; metrics unchanged
- **Security / temporal / citation implications:** the screens hold no data of their own and add no access logic; everything comes from the API, which enforces scope. Sign-in remains simulated and sandbox-only
- **Blocker / decision needed:** none
- **Exact next action:** remaining core touchpoints in the sandbox, one per slice, each with an API test and a screen: TP8 "file so far" → TP9 link file → TP2/TP3 receipt inbox / put in a file → TP4 received letters → TP13 senior brief → TP6/TP7/TP14 (need Gemini for drafting; build the deterministic parts first)

### 2026-11-04 · P5 / P8 · Status lookup states visible supersession (owner refinement)
- **Status:** DONE
- **Plan section:** §5.4, §6.1, §11.5 (touchpoint 10); owner rules 3 Nov and 4 Nov 2026
- **Files changed:** `backend/app/agents/tools.py` (`check_document_status`: superseded / repealed / expired from visible records is reported with `by`, without `current_version`, message `CURRENT_UNCONFIRMED`; in force without coverage → `STATUS_UNCONFIRMED` as before), `backend/app/agents/routes.py` (`by` in the reference response), `backend/tests/unit/test_agent_tools_and_memory.py`, `backend/tests/unit/test_sandbox_api.py`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv: ruff ✅ · mypy strict (101 files) ✅ · `pytest -q` → 1139 passed ✅
- **Acceptance evidence:** U01 and U06 asking about G.O.Ms.88/2022 → superseded by G.O.Ms.31/2025, no "current version" claimed; U01 asking about 31/2025 itself (in force, no full Finance coverage) → generic message, as before; the hidden-successor test still gives identical answers for every officer and document; HTTP leakage sweep still 0; TP10 and TP11 now agree for 88/2022
- **Security / temporal / citation implications:** only facts from visible records are stated; a hidden later order can't change any answer, so nothing about restricted records leaks
- **Blocker / decision needed:** none
- **Exact next action:** P8 slice 2 — `frontend/eoffice/` Vite + React + TS screens (owner has Node v24.5.0)

### 2026-11-04 · P8 / M9 · Sandbox + assist API (slice 1 of the mock e-Office sandbox)
- **Status:** DONE (API); screens are slice 2
- **Plan section:** §11.1–§11.5 (touchpoints 10, 11, 15; drafts out; access mapping), §10.4 audit; CLAUDE.md §2.4, §4; ADR-0012
- **Files changed:** new `backend/app/agents/{runtime,routes}.py`, new `backend/app/audit/log.py`, new `backend/app/eoffice_mock/{routes,corpus}.py`, `backend/app/eoffice_mock/adapter.py` (notes, correspondence, artefacts; sign-in-able profiles; reachable files), `backend/app/connectors/eoffice.py` (`SourceArtefact`, `documents()`), `backend/app/config.py` (sandbox settings), `backend/app/main.py` (composition root, banner header, lazy runtime), new `backend/config/sandbox.yaml`, new `backend/tests/unit/test_sandbox_api.py`, `backend/tests/unit/test_eoffice_connector.py` (main.py allowed as composition root), new `docs/decisions/0012-…md`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv, from `backend/`: `ruff check . ../evaluation` ✅ · `ruff format` ✅ · `mypy` strict (101 files) ✅ · `pytest -q` → 1138 passed ✅ · eval `--no-write --compare …telugu-headers.json` → identical metrics, 0 disclosures
- **Acceptance evidence:** routes `/sandbox/{profiles,me,files,files/{computer_no}}` and `/assist/{search,reference,presend,draft}`. No / unknown / staff-post sign-in → 401 "Not signed in." everywhere. File lists follow e-Office reach plus clearance (U01: no CONFIDENTIAL Estt.I or Vigilance files; U04 gets its two assigned files; SECRET report file only for the Secretary); unknown and unavailable files return the same 404. TP15: U03 "that 2023 drain case" → `USD01-WRKS0/18/2023-WORKS`, no Vigilance file; U05 never sees the SECRET report. TP10: U01 citing G.O.Ms.88/2022 → generic status-unconfirmed message (owner rule); Secretary citing G.O.Ms.14/2021 → superseded, current `AP-USD01-GOMS-27-2024`. TP11 over HTTP on file 2894562 → A, E, F, C with C uncertain (mock rules) and `calibrated: false`. Insert as Yellow Note → a draft, shown on the file page; another section's officer → 404. Audit holds IDs and outcomes only — no question or note text. Lowering U02's clearance takes effect on the next call. **Leakage sweep over HTTP: 8 officers × 24 golden questions + every corpus reference + pre-send and file page on all 13 files → 0 disclosures**
- **Finding (sweep):** a file page shows a note's own text, which may quote another file's number (D20 cites the Vigilance file). That is the authorised document as written, not a disclosure by the system; the sweep checks what the page itself names. Kept visible here so the owner can decide otherwise
- **Open question for the owner:** TP10 (status lookup) applies the status-coverage rule and returns the generic message for G.O.Ms.88/2022 to the Estt.I SO, while TP11 (pre-send) flags the same order as superseded (type A) from the records the officer can see. Should type A in the pre-send also defer to the status-coverage rule, or is "superseded by an order you can see" acceptable there?
- **Security / temporal / citation implications:** grants are re-read from the connector on every call; core routes never import the sandbox; the sign-in header exists only when the sandbox is enabled (off by default on GCP)
- **Blocker / decision needed:** TP10/TP11 question answered by the owner the same day (see the next entry)
- **Exact next action:** slice 2 — scaffold `frontend/eoffice/` (Vite + React + TS): banner, sign-in picker, file list, file inner page with the Assist panel (pre-send, search, local reference, Insert as Yellow Note)

### 2026-11-04 · P1 / M2 · Telugu order headers (D16)
- **Status:** DONE
- **Plan section:** §4.1 (Telugu/English), §4.3, §4.4
- **Files changed:** `backend/app/identifiers/resolver.py` (`TELUGU_MARKERS` fixed table + `normalise_telugu_markers`; "శాఖ" counts as naming a department), `backend/app/ingestion/metadata.py` (markers normalised before parsing; own Rc/Memo line may have a comma before the date), `data/ontology/departments.yaml` (Telugu alias "పట్టణ సేవల" for the synthetic USD01), new `backend/tests/unit/test_telugu_metadata.py`, new `evaluation/reports/2026-11-04-telugu-headers.{md,json}`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** regression tests written first and run failing (4 of 5); then Linux Python 3.13 venv, from `backend/`: `ruff check . ../evaluation` ✅ · `ruff format` ✅ · `mypy` strict (95 files) ✅ · `pytest -q` → 1124 passed ✅ · `python ../evaluation/run_eval.py --label telugu-headers --compare ../evaluation/reports/2026-11-04-action-windows.json` → exit 0
- **Acceptance evidence:** D16 → `AP-USD01-RC-USD01WRKS0-22-2025-D20250602`, Circular, 02-06-2025, USD01 (from its Rc code, `department_source: text`), Telugu subject kept as written, reference సూచిక → `AP-USD01-GOMS-27-2024` (named via the Telugu department name), no review reasons; a Telugu reference naming an unknown department → unresolved (never defaulted); English headers unchanged. Eval: all 29 corpus documents now indexed (none missing); leakage 0 / 1142 checks; NDCG@10 0.711 → 0.714; other metrics unchanged
- **Finding:** Q06's recall did NOT improve (still 0.5): L1 matches English subject terms and D16's subject is only in Telugu. Q19 (Telugu question) still finds nothing in the keyword stand-in. Both need bilingual subjects or multilingual retrieval — GCP (Vertex AI embeddings); not worth tuning the stand-in
- **Security / temporal / citation implications:** the marker table rewrites only the listed reference markers; a Telugu department name not in the table keeps the reference unresolved (no guessed department)
- **Blocker / decision needed:** none. Telugu marker table and Telugu department names are `[To confirm]` against real Telugu orders
- **Exact next action:** remaining non-GCP items — owner pending list (ADR-0005/0006 acceptance, 17 touchpoint scenarios, 6 date reviews, real authority rules); otherwise the sandbox screens for the touchpoints (P8, React) are the largest buildable block without GCP

### 2026-11-04 · P4 / P7 · Action windows from order clauses (type F) + overwrite-safe eval reports
- **Status:** DONE
- **Plan section:** §6.1, §6.2, §6.4 (type F), §11.5 (touchpoint 11), §13
- **Files changed:** new `backend/app/temporal/windows.py` (`ActionWindow`, `windows_from_text`: clause-level ID, dates, the words), new `backend/app/conflict/windows.py` (`check_action_window`), `backend/app/conflict/presend.py` (`windows=` param; action-window F, uncertain without full status coverage), `backend/app/conflict/__init__.py`, `backend/app/ingestion/pipeline.py` (`stores.windows` for order types), `evaluation/harness/suites.py` (passes the stack's windows), `evaluation/run_eval.py` (`free_name`: a report is never overwritten), new `backend/tests/unit/test_action_windows.py`, `backend/tests/unit/test_presend.py` (windows passed; D27 known gap removed), `backend/tests/unit/test_eval_harness.py`, new `evaluation/reports/2026-11-04-action-windows.{md,json}`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv, from `backend/`: `ruff check . ../evaluation` ✅ · `ruff format --check` ✅ · `mypy` strict (94 files) ✅ · `pytest -q` → 1119 passed ✅ · `python ../evaluation/run_eval.py --label action-windows --compare ../evaluation/reports/2026-11-04-after-gap-fixes.json` → exit 0
- **Acceptance evidence:** windows read: G.O.Ms.62/2019 para 2(i) 15–30 Jun 2019, G.O.Ms.88/2022 para 2(i) 8–30 Jun 2022, G.O.Ms.31/2025 para 2(i) 15–31 May 2025; Standing Order 2/2020 (mentions relaxation, opens none) → none. D27 (22-09-2026) → F citing `AP-FIN01-GOMS-31-2025#para-2.i`, uncertain for the Estt.I SO (cannot see every Finance order on transfers); D19 (27-05-2025) and D17 (20-06-2022) inside their windows → no flag; 2 Sep 2023 → F citing 88/2022 (the order then in force); works / outsourcing → no basis, no flag; amended source order → uncertain. Eval vs after-gap-fixes: conflicts A/C/E/F recall 0.857 → **1.000** (precision 1.000), touchpoints 5 → **6 of 6 run**, leakage 0 / 1126, retrieval unchanged
- **Security / temporal / citation implications:** only windows from orders the officer may see and that are in force on the proposal date count; a window is never inferred from a sentence that doesn't match the fixed pattern; "no later period" is stated only about the orders available to the officer
- **Blocker / decision needed:** none
- **Exact next action:** Telugu metadata for D16 (Rc. No. / తేది / విషయం). B/D/G wait for GCP (owner, 4 Nov 2026)

### 2026-11-04 · P1 / P3 / P4 · Fix the gaps the baseline found + ADR-0011
- **Status:** DONE (findings 1, 2, 3, 4, 6); 5 (Telugu Rc D16) and 7 (Telugu question) open
- **Plan section:** §3.2 (L0), §4.3–§4.4, §6.4 (type F); ADR-0007, ADR-0011
- **Files changed:** `backend/app/retrieval/scoped.py` (a reference printed without its date finds the dated record in scope; several → AMBIGUOUS), `backend/app/identifiers/resolver.py` ("G.O.Ms.No.31 of 2025"), `backend/app/ingestion/metadata.py` (`valid_until` from the order's own subject; subject when the abstract has no rule line; report / statement title as subject; `source_department` + `department_source`), `backend/app/ingestion/pipeline.py` (passes the source department; DEPARTMENT_MISMATCH → held; `valid_until` into temporal facts), `backend/app/hitl/queue.py` (DEPARTMENT_MISMATCH), new `backend/tests/unit/test_baseline_gap_fixes.py`, `evaluation/run_eval.py` (`--label`, `--compare`), new `evaluation/reports/2026-11-04-after-gap-fixes.{md,json}`, new `docs/decisions/0011-department-from-source-system-tag.md`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv, from `backend/`: `ruff check . ../evaluation` ✅ · `ruff format --check` ✅ · `mypy` strict ✅ · `pytest -q` → 1109 passed ✅ · `python ../evaluation/run_eval.py --label after-gap-fixes --compare ../evaluation/reports/2026-11-04-baseline.json` → exit 0. Note: the regression tests were written alongside the fixes, not before them; the baseline run is the failing evidence
- **Acceptance evidence (measured vs baseline, same slots and thresholds):** leakage 0 / 1126 checks (was 0 / 1062); Recall@5 0.531 → 0.706, Recall@10 0.561 → 0.754, P@5 0.232 → 0.295, MRR 0.684 → 0.833, NDCG@10 0.550 → 0.711, ladder-level 0.579 → 0.684; conflicts A/C/E/F recall 0.714 → 0.857 (D29's F now found from G.O.Rt.1184's "for the period … to 31-03-2026"), precision 1.000, 0 false flags on clean notes; touchpoints 4 → 5 passed (TP11-c). Q05, Q17 now L0 with full recall; Q04 full recall; D11 indexed as `AP-USD01-SO-2-2020` (`department_source: source_system`); every indexed document has a subject; end dates read: D07 31-03-2025, D08 31-03-2026 (both equal the corpus index); no corpus document triggers a department mismatch
- **Security / temporal / citation implications:** the base-ID match runs only over in-scope documents, so it can't reveal a hidden dated record (tested with a SECRET Vigilance record). End dates come from the order's own subject only, never from body text quoting other orders. A text/tag department disagreement holds the document out of the index
- **Still open:** D27's type F (clause-level transfer window in G.O.Ms.31/2025); D16 (Telugu Rc: document type not recognised); Q19 (Telugu question, needs multilingual retrieval on GCP); B, D, G
- **Blocker / decision needed:** none
- **Exact next action:** clause-level effective windows (e.g. "ban relaxed from 15-05-2025 to 31-05-2025", para 2.i of G.O.Ms.31/2025) so type F covers D27; then Telugu metadata for D16

### 2026-11-04 · P7 / M8 · Evaluation harness + first baseline (plan §13)
- **Status:** DONE (harness + baseline); suites needing Gemini / Document AI / sandbox screens reported as not run
- **Plan section:** §13.1–§13.3, §11.5; CLAUDE.md §9
- **Files changed:** new `evaluation/__init__.py`, `evaluation/harness/{__init__,stack,metrics,suites}.py`, `evaluation/slots_v1.json`, `evaluation/run_eval.py`, `evaluation/reports/2026-11-04-baseline.{md,json}`, `evaluation/README.md`; new `backend/tests/unit/test_eval_harness.py`; `backend/pyproject.toml` (pytest `pythonpath` + mypy `files` include `../evaluation`); `Makefile` (`eval` target; lint/format cover `evaluation/`); `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv, from `backend/`: `ruff check . ../evaluation --config pyproject.toml` ✅ · `ruff format --check` (same paths) ✅ · `mypy` strict (90 files) ✅ · `pytest -q` → 1099 passed ✅ · `python ../evaluation/run_eval.py` → exit 0
- **Acceptance evidence (measured, synthetic, reference stack):** stack built by `ingest()` on every corpus file: 21 native indexed; 6 held scans indexed from hand transcriptions (stand-in for Document AI + reviewer, declared in the report); D11, D16 not indexed even then. Leakage: **0 disclosures in 1062 checks** (question → retrieved set, → evidence package, exact ID + graph from every document, L2 by every subject, L1 list-all, reference-lookup existence, pre-send reports) — oracle `access_matrix.csv`. Retrieval (19 answerable): Recall@5 0.531, Recall@10 0.561, P@5 0.232, MRR 0.684, NDCG@10 0.550, 7 with full recall; ladder-level accuracy 0.579 (11/19). No-answer questions: 0 forbidden docs. Conflicts: A 1/1, C 3/3, E 1/1, F 0/2; B, D, G not implemented (Gemini); 0 false flags on clean D19/D24/D25, none reported "clear" (mock rules). Touchpoints: 6 of 17 run, 4 pass (TP11-b, TP15-a/b, TP20); TP11-a, TP11-c fail on type F
- **Findings (pipeline gaps the baseline exposed — not fixed in this slice, so the baseline stands):** (1) L0 `exact()` falls back dated→base but not base→dated, so "Circular Memo No.USD01-WRKS0/9/2023" (stored with `-D20230711`) is NOT_FOUND — Q05; (2) resolver does not read "G.O.Ms.No.31 of 2025" — Q17 unresolved; (3) ingestion never extracts a document's own validity end ("valid up to 31-03-2026"), so D29's F is missed on the pipeline stack (unit tests passed because they use the CSV's dates); (4) Standing Order D11 has no department in its text → unresolved (the source tag knows USD01 — needs an owner decision whether that may be used); (5) Telugu Rc D16 → document type not recognised; (6) empty subjects for D01, D02, D09, D15, D23, D26 → L1 subject filters miss them (Q04); (7) Q19 (Telugu question) gets nothing from the keyword stand-in — expected until multilingual embeddings (GCP); (8) golden labels Q21 "L3" and Q22 "L0" look inconsistent with their questions — left unchanged (mock-data rule)
- **Security / temporal / citation implications:** leakage suite is now a regression gate in `pytest` (any disclosure fails the build; `make eval` exits 1). Ground truth is read only under `evaluation/` and tests; the integrity test still guards `backend/app/`
- **Blocker / decision needed:** finding (4) decided by the owner the same day → ADR-0011
- **Exact next action:** done — see the gap-fix entry above

### 2026-11-04 · P4 / M5 · Proposal facts from notes + pre-send check (touchpoint 11)
- **Status:** DONE (deterministic types); B, D, G need grounded Gemini
- **Plan section:** §6.2, §6.4, §11.5 (touchpoint 11); ADR-0010
- **Files changed:** new `backend/app/conflict/{facts,presend}.py`, `backend/app/conflict/procedural.py` (authority/concurrence aliases), `backend/app/conflict/__init__.py`, `data/ontology/authority_rules.yaml` (aliases), new `backend/tests/unit/test_presend.py`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format --check` ✅ · `mypy` strict (83 files) ✅ · `pytest -q` → 1094 passed ✅
- **Acceptance evidence:** facts read from D27/D28/D29 equal the hand transcription (D27: staff transfer, Deputy Secretary — not the Secretary "on leave"; D28: Rs.1.30 crore, Commissioner — not the earlier rule sentence; D29: approver unknown — "the Department" is not an authority — reported as a gap, with the sentence as evidence); D25 → Government, Rs.1.40 crore. Pre-send: D27 (U01) A+C+E, D28 (U03) C, D29 (U01) C+F — every deterministic planted conflict except D27's F; type C uncertain with mock rules; the 2023 circular cited by D28 is "status unconfirmed" for the Works SO (no full coverage); clean D25 → review needed with mock rules, CLEAR only with a verified rule set and full coverage (Secretary); the Assistant Secretary's pre-send on D20 never names the Vigilance file; unknown user → review needed
- **Known gap:** D27's type F (proposal outside the 2025 relaxation window) needs clause-level effective windows read from G.O.Ms.31/2025's text
- **Security / temporal / citation implications:** CLEAR requires verified rules, complete status coverage and no fact gaps — never reached on mock data
- **Blocker / decision needed:** none
- **Exact next action:** evaluation harness: run the golden questions and touchpoint scenarios end to end on the reference stack and report metrics (plan §13)

### 2026-11-04 · P4 / M5 · Conflict type C — approval authority and concurrence (ADR-0010)
- **Status:** DONE (engine + rules); filling the facts from note text is the next step
- **Plan section:** §6.2, §6.4
- **Files changed:** new `data/ontology/authority_rules.yaml` (mock), new `backend/app/conflict/procedural.py`, `backend/app/conflict/__init__.py`, new `backend/tests/unit/test_conflict_procedural.py`, new `docs/decisions/0010-approval-authority-rules-for-conflict-type-c.md`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format --check` ✅ · `mypy` strict (80 files) ✅ · `pytest -q` → 1073 passed ✅
- **Acceptance evidence:** answer key met — D27 "Deputy Secretary can only recommend; competent authority Secretary" citing G.O.Ms.19/2018, G.O.Ms.31/2025, SO 2/2020; D28 "above Rs.1.00 crore → Government only" citing G.O.Ms.27/2024; D29 "without prior Finance concurrence" citing G.O.Ms.40/2020; no flags for D19, D24 (2023, before the 2024 rule), D25. Above Rs.5 crore also needs Finance concurrence; Assistant Secretary transfer → GAD (Ser.A); a Works officer is not shown the RESTRICTED Standing Order; with no visible source the flag is uncertain and uncited; unknown codes in the rules file are rejected
- **Security / temporal / citation implications:** competence is a rule fact, never an LLM judgment; restricted rule text never quoted to officers who cannot see it; rules date-bounded
- **Blocker / decision needed:** rule content [To confirm] with real data; ⏰ post levels rely on ADR-0008 (hierarchy re-check)
- **Exact next action:** fill `ProposalFacts` from note text (action, post, amount, proposed authority, concurrence) with deterministic patterns and evidence, then run A/C/E/F together as the pre-send check
- **Follow-up (same day, owner conditions):** added rule coverage + three outcomes; with the mock file every result is either an uncertain, caveated conflict or REVIEW_NEEDED; verified branch tested on an in-test VERIFIED copy only; `pytest -q` → 1082 passed, ruff/mypy clean

### 2026-11-03 · P4 / M5 · Relationship reconciliation + open-file notices (touchpoint 4)
- **Status:** DONE on reference stores
- **Plan section:** §7.2, §7.3, §5.4, §11.5 (touchpoint 4)
- **Files changed:** new `backend/app/updates/reconcile.py`, `backend/app/updates/__init__.py`, `backend/app/ingestion/pipeline.py` (calls reconcile; `open_files`, `files`, `pending_files`, `notices`), `backend/app/graph/repository.py` (`edges_to`), new `backend/tests/unit/test_reconcile.py`, `backend/tests/unit/test_ingestion_pipeline.py` (D20→D21 now expected), `data/synthetic/tools/build_eoffice_seed.py` + `seed.json` (file state closed when all its documents are decided), `data/synthetic/mock_v1/ground_truth/touchpoint_scenarios.json` (TP04 expectation corrected), `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format --check` ✅ · `mypy` strict (78 files) ✅ · `pytest -q` → 1054 passed ✅ · seed `--check` up to date ✅
- **Acceptance evidence:** D20 cites the Vigilance file → linked to D21 (earlier) not D22 (later), in either arrival order; whole corpus → zero inferred-supersession items (every real one is explicit); two same-subject orders a year apart → review item + unconfirmed edge, old order stays in force with `pending_review`; different subject or explicit link → nothing inferred. TP04 replay: G.O.Ms.31/2025 arrives → 88/2022 superseded directly; notice lists only open file USD01-12/19/2026-ESTT.I (decided 2022/2023 files are closed); Section Officer (Estt.I) and Assistant Secretary see it, Works and Finance officers see nothing
- **Correction:** my draft TP04 scenario expected an explicit supersession to wait for confirmation; plan §7.3 says explicit → set directly, inferred → confirm. Scenario fixed (still draft — owner review)
- **Security / temporal / citation implications:** notices never name files or orders the officer cannot see; inferred links never change a status without an officer
- **Blocker / decision needed:** none
- **Exact next action:** conflict type C (procedural / wrong authority) — needs approval-authority rules; owner decision pending on the source (open question in §6)

### 2026-11-03 · P1 / M2 · Ingestion job (detect → extract → gate → metadata → ID → review / index + graph)
- **Status:** DONE on reference stores; Document AI OCR and GCP stores wait for access
- **Plan section:** §4.1–§4.6, §7.2 (pending edges), §7.4; CLAUDE.md §5.1–§5.10
- **Files changed:** new `backend/app/ingestion/pipeline.py`, `backend/app/identifiers/canonical.py` (`efile_document_id`), `backend/app/retrieval/scoped.py` (`upsert`, `remove`, `len`), `backend/app/graph/repository.py` (`node_ids`, `edges_from`), `backend/app/hitl/queue.py` (`CLASSIFICATION_MISMATCH`), `backend/app/ingestion/__init__.py`, new `backend/tests/unit/test_ingestion_pipeline.py`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format --check` ✅ · `mypy` strict (76 files) ✅ · `pytest -q` → 1047 passed ✅
- **Acceptance evidence:** whole corpus: 21 indexed, 8 held (7 scans/photos + D15 whose page 2 needs OCR — partial documents are never indexed); every indexed ID matches the corpus; graph holds exactly the explicit in-corpus edges (D20→D21 file citation waits); G.O.Ms.88/2022 superseded by 31/2025 from ingested facts; ingested index stays permission-enforced; re-run → DUPLICATE with no new nodes or review items; same bytes from a second source → same document (no false collision); new bytes → new version, old kept, ID unchanged; D04 before D03 → supersession attaches when D03 arrives; cached answer about 88/2022 invalidated when 31/2025 arrives; text marking RESTRICTED vs source tag UNCLASSIFIED → held; two different G.O.Ms.126/2023 → bare ID + `-HRIII`, bare lookup ambiguous; confirming a scan's review does not index empty text; unsupported bytes → held
- **Fixed while testing:** a reference printed without a date (base ID) now matches a dated stored ID when exactly one has that base (D08 → D07)
- **Security / temporal / citation implications:** permission tags only from the source; classification never changed silently; unconfirmed/partial text never indexed
- **Known gap:** mock D22's hand-made `-R1` differs from the ADR-0007 registry suffix the pipeline would give (`-C01`); not changed (mock-data rule); D22 is a scan, held anyway
- **Blocker / decision needed:** none
- **Exact next action:** file-index matching for note→file citations, then open-file reconciliation when a superseding order arrives (plan §7.2, touchpoint 4)

### 2026-11-03 · P1 / M2 · Native extraction + document type, metadata and relation extraction
- **Status:** DONE for native text; OCR'd pages wait for Document AI (GCP)
- **Plan section:** §4.1, §4.3, §4.4, §13.2 (extraction, canonical IDs)
- **Files changed:** new `backend/app/ingestion/{extract,metadata}.py`, `backend/app/ingestion/__init__.py`, new `backend/tests/unit/test_ingestion_extract_metadata.py`, `PROGRESS.md`, `docs/LEARNINGS.md`. No new dependencies (DOCX/XLSX read with the standard library)
- **Tests/commands run:** Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format --check` ✅ · `mypy` strict (74 files) ✅ · `pytest -q` → 1032 passed ✅
- **Acceptance evidence (all 22 natively readable corpus files):** issue date 22/22; own canonical ID 15/15 orders and memos; document type 21/22; every in-corpus SUPERSEDES / AMENDS / CLARIFIES / REFERENCES / CITES edge found with no wrong extras. Explained differences (tested, not hidden): D28 carries no draft marker so it is "Noting", not "Noting (draft proposal)"; D06 and D27 cite orders outside the corpus (D27's is the planted missing authority); D20 cites the Vigilance file by file number → unresolved file reference until matched to the file index. The 7 scans/photos yield no text (OCR pending)
- **Bugs found and fixed while measuring:** DOCX signature blocks lost their line breaks/tabs (dates not found); "G.O.Ms.No.31 and Circular Memo …, Dt.14-08-2023" let the G.O. take the memo's date — citation spans may no longer cross another reference (regression test)
- **Security / temporal / citation implications:** unknown text → review, never a guessed type or ID; formula cells without cached values are kept as formulas, never invented numbers; relations are explicit only when the text states them
- **Blocker / decision needed:** none
- **Exact next action:** one idempotent ingestion job: detect → extract → gate → metadata → review queue / index + graph (reference stores), re-runnable on the same file without duplicates (plan §4, §7.4; CLAUDE.md §5.10)

### 2026-11-03 · P2 / P5 · Status-coverage rule (owner decision)
- **Status:** DONE
- **Plan section:** §5.4, §5.6, §6.1
- **Files changed:** `backend/app/auth/models.py` (`StatusCoverage`, `AccessPolicy.status_coverage`, `Scope.covers_status_domain`), `data/ontology/access_policy.yaml` (`status_coverage: full_department`), `backend/app/agents/tools.py` (`STATUS_UNCONFIRMED`, coverage check in status/current-rule tools, `status_unconfirmed`, `message`), `backend/tests/unit/test_agent_tools_and_memory.py`, `backend/app/ingestion/__init__.py` (docstring line length), `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format --check` ✅ · `mypy` strict ✅ · `pytest -q` → 970 passed ✅
- **Acceptance evidence:** strict default: the Secretary gets the real status of USD01 orders (G.O.Ms.14/2021 superseded → 27/2024); Section Officer / Deputy Secretary / cross-department requests get the generic message; current-rule tool never claims "current" without coverage; lenient mode gives 31/2025 (as of 2026) and 88/2022 (as of 2023) for public Finance orders but still the generic message for a RESTRICTED order; for all 8 officers × every visible document, the result is identical with or without an injected hidden superseding order
- **Security / temporal / citation implications:** the generic message carries no information about hidden records; an order's status is never inferred from a partial record set
- **Known consequence:** with the strict default, most officers get the generic message for orders of other departments (e.g. Finance G.O.s seen in Urban Services) — intended until the ceiling is decided with real data
- **Blocker / decision needed:** coverage ceiling (deferred to real data)
- **Exact next action:** native extractors (PDF text, DOCX, XLSX) + document-type classification and reference extraction (plan §4.1, §4.3)

### 2026-11-03 · P1 / M2 · Detect-first routing, confidence gate, review queue
- **Status:** DONE (no GCP parts); OCR itself (Document AI) waits for GCP
- **Plan section:** §4.1, §4.2, §9.1 (checkpoint 5); CLAUDE.md §5.1, §5.3, §8, §11.8
- **Files changed:** new `backend/app/ingestion/{detect,gate}.py`, new `backend/app/hitl/queue.py`, package docstrings, new `backend/tests/unit/test_ingestion_detect_gate.py`, `backend/pyproject.toml` (+ `pypdf>=5.0`), `backend/uv.lock` (+ pypdf 6.21.4 only; regenerated with uv 0.9.28 to match the Mac), `PROGRESS.md`, `docs/LEARNINGS.md`
- **New dependency:** pypdf — per-page text-layer detection needs a PDF parser (compressed streams, page trees); pure Python, BSD, supports 3.13, small enough for a Cloud Run job
- **Tests/commands run:** `uv lock` (0.9.28) → only pypdf added ✅ · Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format --check` ✅ · `mypy` strict (71 files) ✅ · `pytest -q` → 961 passed ✅. NOT run: `uv sync` / `make check` on the Mac
- **Acceptance evidence:** all 29 corpus files routed exactly as the manifest's format column (native PDF, scanned, mixed per-page with page 2 OCR, photos, DOCX, XLSX); a JPEG named `.pdf` is detected as JPEG with a mismatch flag; encrypted/corrupt PDF, empty, binary and fake-zip files → unsupported (never an exception); CSV/TXT/HEIC sniffed. Gate: native → index; OCR with the uncalibrated threshold → review; with a test threshold only OCR pages count; missing confidence → hold; held → indexable only after a named reviewer confirms with a reason; rejected or a new version stays out; decisions are final; resubmission idempotent
- **Security / temporal / citation implications:** OCR'd text never becomes citable evidence before human confirmation while the threshold is uncalibrated; text layers on scanned-looking pages are not trusted
- **Blocker / decision needed:** none (threshold calibrated in P1 on real scans)
- **Exact next action:** native extractors (PDF text layer, DOCX, XLSX tables) and document-type classification + reference extraction from text (plan §4.1, §4.3)

### 2026-11-03 · P5 · Bounded agent tools + session-memory scope rules
- **Status:** DONE (reference implementations); LangGraph wiring and Postgres checkpointer wait for GCP
- **Plan section:** §5.4, §5.6, §10.1, §13.2 (conversation-memory scope); CLAUDE.md §4.6, §4.9, §4.11
- **Files changed:** new `backend/app/agents/tools.py`, new `backend/app/memory/session.py`, `backend/app/agents/__init__.py`, `backend/app/memory/__init__.py`, new `backend/tests/unit/test_agent_tools_and_memory.py`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format --check` ✅ · `mypy` strict (67 files) ✅ · `pytest -q` → 918 passed ✅
- **Acceptance evidence:** exactly the six plan §5.6 tools; `get_current_rules` gives G.O.Ms.31/2025 + clarification as of 2026 and 88/2022 as of 2023; status of 88/2022 = superseded → 31/2025, of G.O.Rt.1184 = expired; compare 2023 circular vs G.O.Ms.27/2024 → the G.O. prevails; for all 8 officers every forbidden document gives the same result as an absent one (get / status / compare); search tools return only authorised documents; unknown tools, non-canonical IDs, extra arguments, wrong arity refused; revocation applies on the next call. Memory: newest-first recall, other users refused, revoked entity dropped on the next turn, IDs only, bounded
- **Security / temporal / citation implications:** a restricted superseding order is never named; comparisons with a restricted document return "not available" (a yes/no could leak)
- **Blocker / decision needed:** owner: restricted-superseder status rule (open question above)
- **Exact next action:** P1 pieces that need no GCP: format detection (a .pdf extension is not proof of a text layer), extraction-confidence gate and review queue (plan §4.1–§4.2)

### 2026-11-03 · P3–P5 · Citation outcomes (owner rule), department-less references, AgentState + intent templates
- **Status:** DONE (deterministic parts); LangGraph wiring and Gemini intent classification/drafting wait for GCP
- **Plan section:** §3.2 (templates, canonical query), §3.4, §4.4, §5.6, §8.1–§8.3
- **Files changed:** `backend/app/citation/verifier.py` (rewritten: CONFIRMED / REVIEW_NEEDED / REJECTED, separate `confirmed` and `review_needed` lists, caveat), `backend/app/retrieval/evidence.py` (`TextQuality`, `incomplete`), `backend/app/identifiers/resolver.py` (`reference_candidates`), new `backend/app/retrieval/references.py`, new `backend/app/agents/{state,intents}.py`, package docstrings; tests: `test_evidence_and_citations.py` (verifier section rewritten), new `test_reference_lookup.py`, new `test_agents_state_intents.py`, `test_ladder.py`; `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format --check` ✅ · `mypy` strict (64 files) ✅ · `pytest -q` → 885 passed ✅
- **Acceptance evidence:** confirmed claims and review-needed claims never mixed; 20% vs 15% on native text → removed, same on OCR/incomplete text → review needed; uncited / invented / wrong-record / revoked → removed; all-ambiguous → review evidence + caveat, not the no-answer. Q18 "GO Ms 88/2022" → found in Finance after trying 4 departments; two visible matches → ask with both; a restricted match is never offered; a named department is never widened. Intent templates meet expected/forbidden docs for Q01–Q06, Q17, Q18, Q24 and golden rung labels for all but Q04. AgentState refuses: another user's package, scope mismatch, package IDs not among authorised candidates, citations outside the package, answer status not from verification
- **Security / temporal / citation implications:** slots reject non-canonical IDs, non-word terms (SQL-like input), unknown slots and over-long text — no free-form query reaches retrieval
- **Known gap:** golden labels disagree for the same question shape — Q03 "current rule" expects L1, Q04/Q20 expect L1+L3; templates answer L1 with the right documents. Not changed on mock data (owner rule)
- **Blocker / decision needed:** owner: confirm the golden labels for Q04/Q20 when real questions exist
- **Exact next action:** bounded agent tools over the templates (plan §5.6), then conversation-memory scope rules (plan §10.1)

### 2026-11-03 · P3 / M3–M4 · Retrieval ladder orchestration (L0 → L1 → L2 → L3) + verifier review option
- **Status:** DONE (reference stores); L2 is a keyword stand-in until Vertex AI Search (GCP)
- **Plan section:** §3.2, §8.3, §13.2 (ladder-level accuracy), §13.3
- **Files changed:** new `backend/app/retrieval/ladder.py`, new `backend/tests/unit/test_ladder.py`, `backend/app/citation/verifier.py` (+ `AnswerStatus.NEEDS_REVIEW`, `review_needed`, `REVIEW_NOTE`), `backend/tests/unit/test_evidence_and_citations.py`, package docstrings, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format --check` ✅ · `mypy` strict (59 files) ✅ · `pytest -q` → 848 passed ✅
- **Acceptance evidence:** golden ladder levels and expected/forbidden docs met for Q01 (L2, U01 no D20), Q02 (L2, U02 with D20), Q03 (L1, L2 skipped by early exit), Q05 (L0+L3 via resolver), Q15 (L2, Secretary gets the SECRET report; DS does not); missing reference falls through to L2; every rung is in the trace with its reason; three broad requests for every officer return only authorised documents; unknown user → empty; thresholds uncalibrated → `LadderConfig.from_runtime` raises
- **Security / temporal / citation implications:** every rung (incl. L2 scoring) runs inside the scope and re-checks; no unscoped fallback exists
- **Known gap:** references without a department ("GO Ms 88/2022", Q18) resolve to the officer's own department and miss; needs a cross-department candidate lookup that asks the officer when ambiguous
- **Blocker / decision needed:** none
- **Exact next action:** cross-department candidate lookup for department-less references, then typed `AgentState` + intent templates (plan §3.4, §5.6)

### 2026-11-03 · P3 / M4–M7 · Evidence package + citation verifier
- **Status:** DONE (deterministic); grounded Gemini support check for NEEDS_REVIEW claims waits for GCP
- **Plan section:** §3.3, §5.5, §8.2, §8.3, §13.2 (RAG/citations), §13.3; CLAUDE.md §7
- **Files changed:** new `backend/app/retrieval/evidence.py`, new `backend/app/citation/verifier.py`, `backend/app/citation/__init__.py`, `backend/app/retrieval/__init__.py`, new `backend/tests/unit/test_evidence_and_citations.py`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format --check` ✅ · `mypy` strict (57 files) ✅ · `pytest -q` → 831 passed ✅ (the injection test caught `</evidence_package>` slipping through a tag-name pattern; fixed by neutralising every angle bracket in span text)
- **Acceptance evidence:** for all 8 officers the package holds exactly their authorised canonical IDs; deterministic evidence IDs, dedup, decision refs; hostile span cannot close the fence; supported claims verified; wrong number (20% vs 15%) withheld with the missing token; uncited → withheld; fabricated evidence ID → rejected; wrong quote → withheld; revocation between retrieval and answer → rejected; nothing verified → "No sufficiently supported answer was found in the authorised records."
- **Security / temporal / citation implications:** forbidden documents never enter the package, so they cannot be cited; authorization re-read at verification time
- **Blocker / decision needed:** resolved 3 Nov 2026 — owner chose to show NEEDS_REVIEW claims marked "review needed" (`AnswerStatus.NEEDS_REVIEW`, `review_needed` indexes)
- **Exact next action:** L2 retriever interface + ladder orchestration (L0 → L1 → L2 → L3 with early exit) over the reference stores

### 2026-11-03 · P3 / M3 · GraphRepository + L3 scope-constrained expansion
- **Status:** DONE (in-memory reference); Spanner Graph implementation waits for GCP
- **Plan section:** §3.2 (L3), §3.6, §5.2, §13.3; CLAUDE.md §2.1, §2.3, §4.2
- **Files changed:** new `backend/app/graph/repository.py`, new `backend/app/retrieval/graph_expansion.py`, `backend/app/graph/__init__.py`, `backend/app/retrieval/__init__.py`, new `backend/tests/unit/test_graph_l3.py`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format --check` ✅ · `mypy` strict (54 files) ✅ · `pytest -q` → 813 passed ✅
- **Acceptance evidence:** supersession chain D01 → D03 → D04 by walk; "who cites G.O.Ms.31/2025" gives U01 only D19 but U02 D19 + D20; the walk never passes through a forbidden node (public node behind a SECRET one stays hidden, appears for the Secretary); for all 8 officers × every authorised seed, hits equal an independent BFS over the officer's authorised subgraph; all 106 forbidden seeds ignored; unconfirmed edges (inferred CONFLICTS_WITH) only with explicit review opt-in; revocation applies on the next walk; `l3_max_hops` stays uncalibrated and is not guessed
- **Security / temporal / citation implications:** path existence through restricted documents cannot leak; every hit and every node on its path is re-checked against the store
- **Blocker / decision needed:** none (hop limit to be calibrated in P3/P4 on real data)
- **Exact next action:** evidence package + citation verifier schemas (plan §3.3, §8.2)

### 2026-11-03 · P0 / M1 · Core touchpoint scenarios for the golden dataset (plan §11.5, §13.2)
- **Status:** DONE for core touchpoints (draft — owner review); extended touchpoints NOT_STARTED
- **Plan section:** §11.5, §13.1, §13.2, §13.3
- **Files changed:** new `data/synthetic/mock_v1/ground_truth/touchpoint_scenarios.json` (evaluation only), new `backend/tests/unit/test_touchpoint_scenarios.py`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format --check` ✅ · `mypy` strict (51 files) ✅ · `pytest -q` → 731 passed ✅
- **Acceptance evidence:** every core touchpoint (2,3,4,6,7,8,9,10,11,13,14,15,20) has ≥1 scenario; every referenced user, file, receipt, note, document, clause and golden question exists; every expected document/file is visible to the scenario's officer and every forbidden one is not (access matrix); pre-send scenarios point at planted conflicts; drafts only on click; TP04 replay holds back G.O.Ms.31/2025 with every record that depends on it
- **Security / temporal / citation implications:** 9 scenarios carry forbidden documents/files (leakage checks inside the e-Office flow); TP08 must say notes #4–#5 are missing instead of filling the gap; TP03 is a negative case (do not force a file match)
- **Blocker / decision needed:** owner review of the 17 scenarios (wording and expectations are mine, grounded in the corpus)
- **Exact next action:** in-memory `GraphRepository` with a scope-constrained walk (L3); later the harness that runs these scenarios end to end

### 2026-11-03 · P0 / M1 · Mock e-Office seed data (plan §11.6)
- **Status:** IN_PROGRESS — profiles, files, notes, movements, correspondence, receipts DONE; Yellow-note versions, DFA drafts, links, Previous/Later References not yet seeded
- **Plan section:** §11.2, §11.4, §11.6, §12.2
- **Files changed:** new `data/synthetic/tools/build_eoffice_seed.py` (stdlib only, deterministic, `--check`), new `data/synthetic/mock_v1/eoffice/{seed.json,README.md}`; `backend/app/eoffice_mock/models.py` (Receipt per eFile manual, `TextSource`, note no./post/source, file nature/head, optional creator, `login`, `Seed`), `backend/app/eoffice_mock/adapter.py` (`load_seed`, `adapter_from_seed`); new `backend/tests/unit/test_eoffice_seed.py`; `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** generator run + `--check` ✅ · Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format --check` ✅ · `mypy` strict (50 files) ✅ · `pytest -q` → 675 passed ✅ (the eval-integrity guard caught a docstring naming the answer-key folder; reworded)
- **Acceptance evidence:** seed validates and is reproducible; contains none of planted/conflict/SUPERSEDES/CITES/relations/golden/decision; every actor is a profile; scanned notes have no text; receipt numbers follow `seq/year/section`; Computer Nos unique; no movement across the Vigilance file's missing notes; seeded sandbox: Section Officer (Estt.I) opens own file but gets the neutral error for the Vigilance file; Vigilance file access via store = U04, U05, U06 only
- **Security / temporal / citation implications:** seed refuses to load unless marked synthetic with the banner; staff posts have no login and Individual scope only
- **Blocker / decision needed:** none (assumptions are mock-only, listed in the seed)
- **Exact next action:** core touchpoint scenarios for the golden dataset (plan §11.5, §13.2), which define the Yellow notes / drafts / links still missing from the seed

### 2026-11-03 · P0 / M1 · Canonical-ID collision registry (ADR-0007 suffix rule)
- **Status:** DONE (backend); not yet used by `data_collection/`
- **Plan section:** §4.4; CLAUDE.md §5.5–§5.6
- **Files changed:** new `backend/app/identifiers/collisions.py`, new `backend/tests/unit/test_id_collisions.py`, `backend/app/identifiers/__init__.py`, `docs/decisions/0007-*.md`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format` ✅ · `mypy` strict (49 files) ✅ · `pytest -q` → 663 passed ✅
- **Acceptance evidence:** first record keeps the bare ID; a distinguishing printed section gives `-HRIII`; same or missing section gives `-C01`, `-C02`; the same source always gets the same ID, also after reload from disk; discovery order doesn't change existing IDs; bare-ID lookup of a group → AMBIGUOUS with candidates; exact suffixed ID → FOUND; tampered registry (counter behind, duplicate source/ID) refuses to load; memo date tag stays last (`…-C01-D20240305`); IDs already using the suffix slot go to review
- **Security / temporal / citation implications:** never guesses or reassigns an ID; ambiguity is surfaced for review instead of silently citing the wrong order
- **Blocker / decision needed:** none
- **Exact next action:** e-Office seed data (plan §11.6); later, call the registry from the collectors when collection leaves test phase

### 2026-11-03 · P0/M1 → P2/M3 · Real access control enforced during retrieval; ADR-0007 + ADR-0009 accepted
- **Status:** DONE (reference implementation, in-memory); Cloud SQL store not yet implemented or applied (no GCP)
- **Plan section:** §3.2, §4.4, §5.1, §5.2, §5.4, §5.7, §5.8, §5.9, §10.2, §11.4
- **Files changed:** `backend/app/auth/{models,policy,store}.py`, new `backend/app/retrieval/scoped.py`, new `backend/app/cache/{__init__,answers}.py`, `backend/app/connectors/eoffice.py` (`grants_from_context` replaces `to_principal`; `handled_files`), `backend/app/eoffice_mock/{models,adapter}.py`, `backend/app/identifiers/{canonical,resolver}.py` (`lookup_keys`, date tag default on), `backend/app/retrieval/__init__.py`, `data/ontology/access_policy.yaml`, new `data/schemas/authz.sql`; tests: new `mock_access.py`, `test_retrieval_scoped.py`; updated `test_authz.py`, `test_identifiers.py`, `test_eoffice_connector.py`; ADR-0007, ADR-0009, PROGRESS, LEARNINGS
- **Tests/commands run:** Linux Python 3.13 venv: `ruff check .` ✅ · `ruff format --check .` ✅ · `mypy` strict ✅ · `pytest -q` → 637 passed ✅ · `pglast.parse_sql(authz.sql)` → 15 statements ✅. NOT run: Mac `make check`, any Postgres server
- **Acceptance evidence:** store-backed `check` reproduces 232/232 matrix cells; L1 "everything" query returns exactly each officer's authorised set; L0 exact lookup leaks nothing across all 232 pairs; absent / forbidden / malformed IDs return the same empty result; revoking an assignment removes access and changes the scope signature on the next request; rank without Department scope, and Department scope without rank, both stay section-limited; identical-permission officers share cached answers, different ones never do
- **Security / temporal / citation implications:** permissions are no longer derivable from document metadata alone; unknown/incomplete/contradictory grants → deny; scope/re-check disagreement is logged as an error and never served; cache bypassed when scope is unverifiable; RLS drafted as Tier-2 third layer
- **Known gaps:** L2 (Vertex AI Search) and L3 (graph) not built; Postgres-backed `AuthzStore` waits for Cloud SQL; Post-hierarchy scope needs the confirmed reporting tree (ADR-0008)
- **Blocker / decision needed:** collision suffix rule (ADR-0007); mock_v1 memo-ID migration
- **Exact next action:** e-Office seed data from the synthetic corpus (plan §11.6), then in-memory `GraphRepository` with a scope-constrained walk (L3)

### 2026-11-02 · P0 / M1 (+ early P2, P4) · Build the parts that need neither GCP nor real data
- **Status:** DONE (pure-function scope); not yet wired to stores or the API
- **Plan section:** §3.2 (canonical query), §4.4, §5.1–§5.2, §5.9, §6.1–§6.4, §10.2, §11.2–§11.4
- **Files changed:** new `backend/app/auth/{models,policy}.py`, `backend/app/identifiers/{canonical,resolver}.py`, `backend/app/temporal/engine.py`, `backend/app/conflict/deterministic.py`, `backend/app/connectors/eoffice.py`, `backend/app/eoffice_mock/{models,adapter}.py`; package docstrings of auth, identifiers, temporal, conflict, connectors, eoffice_mock; new `data/ontology/{access_policy,departments}.yaml`; tests `test_authz.py`, `test_identifiers.py`, `test_temporal.py`, `test_eoffice_connector.py`, `test_conflict_deterministic.py`; `docs/decisions/0009-*.md`; `PROGRESS.md`; `docs/LEARNINGS.md`. No new dependencies
- **Tests/commands run:** in a Linux Python 3.13.18 venv with the same tools (not the Mac `uv` env): `ruff check .` ✅ · `ruff format --check .` ✅ · `mypy` strict (41 files) ✅ · `pytest -q` → 379 passed (was 13) ✅. NOT run: `make check` on the Mac, any DB, any cloud call
- **Acceptance evidence:** `can_access` reproduces all 232 cells of `access_matrix.csv`; `compute_scope` and `can_access` agree on every officer × document; all 29 corpus IDs parse and round-trip; every G.O./memo/SO/Rc own reference resolves to its canonical ID; status as of 2026-10-02 matches the corpus for all 16 instruments; as-of-date walks D01→D03→D04 correctly; G.O. prevails over circular (D28 G-pair); A (D27: GOMS-88/2022 superseded by GOMS-31/2025), E (D27: GOMS-104/2026 not found) and F (D29: GORT-1184/2025 expired 31-03-2026) flagged with no false positives on D27/D28/D29
- **Security / temporal / citation implications:** both enforcement layers fail closed; scope signature changes with any permission change; connector gives the same error for "absent" and "not allowed"; drafts only, only on click; core never imports the mock sandbox (test); E-type wording never confirms existence outside the authorised set; unconfirmed supersessions go to review, never change status; ground truth read only by tests (guard test still green)
- **Known gaps:** D27's F (relaxation window inside G.O.Ms.31/2025) needs clause-level effective windows — not detectable from document metadata; type C needs approval-authority rule metadata; search scope not yet a policy input; hierarchy/roles still provisional (ADR-0008 reminder)
- **Blocker / decision needed:** ADR-0009 open questions; ADR-0007 (memo date tag)
- **Exact next action:** e-Office seed data from the synthetic corpus (plan §11.6: profiles for U01–U08 with search scopes, files with movements, receipts, notes) → then Cloud SQL DDL for authz tables, then an in-memory `GraphRepository`

### 2026-10-22 · P0 / M1 · Integrate public-corpus data collection into Project_1
- **Status:** DONE (local scope); owner checks pending (`make check` on the Mac, `.venv` for data_collection)
- **Plan section:** §4.4, §5, §12, §14
- **Files changed:** new `data_collection/` (README, `scope.yaml`, `requirements.txt`, `local.env.example`, 21 tools — copied from `~/Documents/c2-24-data-tools`; only path handling changed: data root from `C2_DC_DATA_ROOT`/`local.env`, `staging` args resolve inside it, `run_batches.sh` calls tools by absolute path), new `docs/data_collection/` (findings 1–73, hand-download list, source checks, plan PDF), `docs/decisions/0006-*.md`, `0007-*.md`, `infrastructure/gcp/08_upload_public_corpus.sh` + README (scope line, run step, P1 OCR step), `.gitignore` (`data_collection/local.env`), `PROGRESS.md`, `docs/LEARNINGS.md`. Not touched: `backend/`, `data/`, `frontend/`, other scripts; the old workspace (fingerprint of its tools/notes/config identical before and after)
- **Tests/commands run:** `py_compile` + import of all 21 tools ✅ · old vs new on the same corpus: `reconcile_dates.py`, `refilter.py`, `find_holdback.py` outputs identical; `validate.py` both "831 documents and 12 e-files: 4 with problems"; `audit_corpus.py` same counts ✅ · missing data root → clear error ✅ · `bash -n` on `run_batches.sh` and `08_upload_public_corpus.sh`; 08 dry run with a throwaway config prints the rsync (831 documents) ✅ · NOT run: `make check` (backend venv is macOS-only; backend files untouched), any gcloud command, any network collection
- **Acceptance evidence:** tools run from Project_1 against the existing corpus with identical results; corpus not duplicated or committed
- **Security / temporal / citation implications:** public records only (UNCLASSIFIED); synthetic e-file ground truth stays eval-only; no secrets (`local.env` holds a folder path, git-ignored); GCS upload never deletes and skips `_review/` and `holdback/`
- **Blocker / decision needed:** accept ADR-0006/0007; collision suffix rule; 6 date reviews; C-type approach
- **Exact next action:** owner: `python3 -m venv data_collection/.venv && data_collection/.venv/bin/pip install -r data_collection/requirements.txt`, then `make check`; on access day `APPLY=1 infrastructure/gcp/08_upload_public_corpus.sh` after `03_storage.sh`

### 2026-10-22 · P0 / M1 · Local foundation while GCP access is pending
- **Status:** DONE (local scope). Cloud items still BLOCKED on access; compose stack and Docker image written but unverified
- **Plan section:** §3.5, §4.5, §12, §14.1, §14.2, §14.6
- **Files changed:** `backend/` (pyproject.toml, uv.lock, .python-version, Dockerfile, app/{__init__,config,main}.py, 19 empty module packages, config/runtime.yaml, prompts/README.md, tests/unit/*), `data/ontology/{hierarchy,classification}.yaml`, `data/synthetic/mock_v1/` (copied corpus, 66 files), `infrastructure/local/docker-compose.yml`, `infrastructure/gcp/*` (lib + 7 scripts + verify + README + config.env.example), `Makefile`, `.env.example`, `.dockerignore`, `frontend/README.md`, `evaluation/README.md`, `docs/decisions/0005-*.md`, `docs/LEARNINGS.md`, `PROGRESS.md`; `git init` (nothing committed)
- **Tests/commands run:** `uv lock` + `uv sync --all-extras` → 116 packages, all extras import on 3.13.9 ✅ · `make check` → ruff clean, ruff format clean, mypy strict clean (28 files), pytest 13 passed ✅ · `bash -n` + dry run of all `infrastructure/gcp/0*.sh` with a dummy config ✅ · `APPLY=1` correctly refuses without gcloud ✅ · NOT run: `docker compose up`, `docker build` (daemon off), any real gcloud command
- **Acceptance evidence:** service boots and `/healthz` reports config versions; config validators reject gaps/duplicates/unknown keys; corpus checks (29 files present, access matrix covers all docs × U01–U08, values fit ontology); guard test that `backend/app` never references ground truth
- **Security / temporal / citation implications:** no secrets in repo (`.env`, `config.env` git-ignored; IAM DB auth, no SA keys); ground-truth isolation enforced by test; thresholds left `null` rather than guessed; hierarchy/classification stay `draft` [To confirm]
- **Blocker / decision needed:** GCP access; region/data-residency confirmation; owner to accept ADR-0005
- **Exact next action:** pick the next P0 item: (a) Cloud SQL schema + `compute_scope`/`can_access` spike against `access_matrix.csv` (runs on local Postgres or pure functions), or (b) mock e-Office data model + `EOfficeConnector` interface (plan §11.2–§11.3). When access arrives: `infrastructure/gcp/README.md` §1

### 2026-10-13 · P0 / M1 · Final implementation plan (v5)
- **Status:** DONE
- **Plan section:** whole plan; new §11 (Mock e-Office Integration)
- **Files changed:** `IMPLEMENTATION_PLAN.md`, `docs/C2-24_Implementation_Plan_Final.pdf`, `docs/images/*`, `CLAUDE.md` (§2.4, module list), `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** none applicable (documentation only)
- **Acceptance evidence:** v4 content unchanged; new §11 + integrated references in §1–§3, §5, §9, §12–§16
- **Security / temporal / citation implications:** sandbox access mirrors e-Office search scope + classification; assistant writes drafts only
- **Blocker / decision needed:** none
- **Next action:** gap report (CLAUDE.md §14), then smallest P0 slice

### 2026-10-10 · P0 / M1 · Agent operating contract (CLAUDE.md v2.0)
- **Status:** DONE
- **Plan section:** §14 (repository, docs, decision records; §13 in v4)
- **Files changed:** `CLAUDE.md`, `AGENTS.md`, `docs/LEARNINGS.md`, `docs/decisions/0000-template.md`, `PROGRESS.md`
- **Tests/commands run:** none applicable (documentation only)
- **Acceptance evidence:** contract merged from owner-supplied harness + v1 rules; file names aligned to existing project files
- **Security / temporal / citation implications:** contract encodes security §4, temporal/conflict §6 and citation §7 rules for all future work
- **Blocker / decision needed:** none
- **Next action:** first-task protocol (CLAUDE.md §14): gap report against P0–P9 / M1–M10, then propose the smallest P0 slice (repo skeleton + mock corpus into `data/synthetic/`)
