# C2-24 — Progress Tracker

Tracks build progress against [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) (Final / v5, 13 Oct 2026). Update this file at the end of every work session.

**Last updated:** 15 Nov 2026
**Current phase:** P0 — Foundation & design
**Overall status:** 🟡 Planning done · build starting on synthetic data · real department data not yet received

Legend: ✅ done · 🟡 in progress · ⬜ not started · ⛔ blocked

---

## 1. Phase status

| Phase | Focus | Status | Notes |
|---|---|---|---|
| P0 | Foundation & design | ✅ | GCP project, IAM (service roles granted 15 Nov), Cloud SQL schema (0001–0003), BigQuery datasets, e-Office data model + connector, seed v1/v2, touchpoint scenarios. Hierarchy, classification and access policy are mock by owner decision [To confirm with department] |
| P1 | Ingestion & extraction | ✅ | Full public corpus on GCP (1,373 orders → 1,290 indexed, 83 held, 1,669 links); OCR via Document AI (recorded); confidence gate + review queue; source path + hash recorded. Open: 53 "type not recognised", 19 ID reads differ from collection metadata |
| P2 | Authorization core | ✅ | compute_scope + re-check on every rung, cache, memory, counts; leakage 0 / 1,142 (v1) and 0 / 64,008 (v2 incl. chat) |
| P3 | Retrieval ladder + RAG + citations | ✅ | L0/L1/L2 on BigQuery, L3 on Cloud SQL, all equal to the reference (601 + 18 questions); evidence package, cited answers, verifier. Open: L2 threshold unset (ADR-0026), Telugu question |
| P4 | Temporal + conflict + reconciliation | 🟡 | All 7 types (set v2: A 21/23, B 9/9, C 12/12, D 15/15, E 18/18, F 57/76, G 8/9; 41 clean files, 0 false flags). Open: F misses (rate series), A 2, G 1 |
| P5 | Agents + noting + memory + HITL | ✅ | LangGraph orchestrator (one AgentState), session memory in Cloud SQL, noting agent v2 (live: 44 lines kept, 0 removed), officer edit / confirm / discard of drafts (ADR-0031) |
| P6 | Verification, audit, tracking | ✅ | Verifier on every answer, audit on every route, query log + human actions live in BigQuery (checked on revision c2-api-00003) |
| P7 | Evaluation & security harness | 🟡 | Retrieval, conflict, leakage, injection, memory/cache scope, ask-golden, cloud ladder check. Open: faithfulness/relevance scoring (RAGAS), OCR accuracy, injection + memory suites as report sections |
| P8 | Integration, UI, demo hardening | 🟡 | All 20 touchpoints built; 24/24 touchpoint scenarios pass (17 core + 7 extended, `evaluation/reports/2026-11-15-touchpoints-all.md`); c2-api and c2-frontend on Cloud Run (IAP grants pending: admin `PART=owner`). Redis (Memorystore) built, ON HOLD until the organisation approves the cost |
| P9 | Buffer, dry-run, stretch | ⬜ | Two-officer rehearsal not yet run |

## 2. Milestones

| # | Milestone | Done when | Status | Date |
|---|---|---|---|---|
| M1 | Foundation ready | GCP + IAM, Cloud SQL + graph store, canonical ID scheme + draft hierarchy, synthetic corpus + manifest, authz approach chosen, decision log opened | 🟡 | 14 Nov: all in place, including the graph tables on Cloud SQL (migration `0002_graph` applied by the owner) and service-account access (bucket roles by script 15, Cloud SQL roles by the project owner). Graph store = Cloud SQL now, Spanner later (ADR-0023). Hierarchy, classification and access policy stay mock by owner decision; hierarchy and classification now cite public sources level by level (ADR-0027) |
| M2 | Ingestion + updates | Any format → extracted, classified, canonical IDs, relations → gated → indexed; new doc reconciles supersession | 🟡 | 14 Nov: pipeline runs on PDF (text and scans), DOCX, XLSX, JPEG, TXT; a new order arriving reconciles supersession (ADR-0020 addendum). FULL-CORPUS RUN ON GCP: job `c2-graph-build` upgraded to `--cpu 2 --memory 8Gi` with periodic GC in `build.py`; all 1,373 public orders ingested → 1,290 nodes, 1,669 edges generated to GCS artifacts bucket; loaded into Cloud SQL and BigQuery `c2_metadata.documents` (1,290 rows) |
| M3 | Permission-aware ladder | Two officers, same query, correctly different candidate sets on every rung | 🟡 | 14 Nov: in memory: v1 harness 0 / 1,142; v2 outsider suite 0 disclosures / 55,482 checks (21 officers × 203 files × 15 paths, 833 control hits). Cloud: L0/L1 on BigQuery built with the scope inside the SQL (ADR-0025); L3 on Cloud SQL equal to the reference. Real cloud check run (`evaluation/cloud_ladder_check.py`): L0 exact (453 asked, 0 diff), L1 filter (27 asked, 0 diff), L3 graph size (1 asked, 0 diff), L3 2-hop walk (120 asked, 0 diff) — SAME on every question across 3 scopes (`evaluation/reports/2026-11-14-cloud-ladder-check.md`). L2: BigQuery in region (ADR-0026), passages table + embeddings pending |
| M4 | First cited answer | "Has this been decided before?" → cited precedent from the evidence package | 🟡 | 15 Nov: live run 2 (owner): 15/19 answered with checked citations, 12 on key, 5/5 no-answers kept, 0 forbidden. After tracing its 10 removed statements (ADR-0024 addendum 2), re-scored on the same saved answers: 16/19 answered, 15 on key, 0 removed, 0 forbidden. Open: one live call for Q05; Q11 (count), Q19 (Telugu, needs L2 embeddings); a fresh live run to confirm |
| M5 | Temporal + conflict | As-of-date correct; precedence correct; all 7 conflict types flagged with evidence | 🟡 | 15 Nov: all 7 types implemented. Set v2 (`presend_v2.py`, 14 Nov): A 21/23, B 9/9, C 12/12, D 15/15, E 18/18, F 57/76, G 8/9, 41 clean files with 0 false flags (B/G Gemini, saved answers). v1 harness: A/C/E/F precision = recall = 1.000. As-of questions answered for the stated date (ADR-0024 addendum). Open: F 19 misses (rate series, links not read), A 2, G 1; D, C, E score in full partly by construction (stated in their reports) |
| M6 | Agents + noting + memory + HITL | Multi-turn works; draft noting uses prior precedent; officer approves | 🟡 | 15 Nov: LangGraph orchestrator over the one typed AgentState, one run per turn (`/assist/chat`, ADR-0029); follow-ups use earlier turns re-checked against current access (mid-session revocation test); sessions never shared; session memory in Cloud SQL (migration 0003, tested on Postgres 16); "draft the noting using that precedent" returns the first-cut points with the conversation's precedents (golden-path test); OCR review queue; drafts only on the officer's click. Noting agent text (ADR-0030): the model writes the sections from the first-cut sources, every line checked (cited, numbers in sources, issues only from open points, proposal never a decision), watermarked draft. Noting live v2 (owner): 3 notes, 44 lines kept, 0 removed, 0 forbidden. Officer approval (ADR-0031): the officer edits their Yellow Note, confirms it as the next Green Note (simulated signature; AI markers dropped) or discards it, in the sandbox; drafts are the author's own until confirmed; `/assist` has no confirm path. Open: rehearsed two-officer run |
| M7 | Verified, audited, tracked | Citations pass verifier; every request + human action logged; cache respects scope | 🟡 | 15 Nov: citation verifier on every answer; audit of ids and outcomes on every route; query log per question (IDs only, BigQuery sink ready: `21_query_log_table.sh`); scoped answer cache in the conversation (scope test); neutral fail-closed. Human actions (ADR-0031): Yellow Note confirmed / edited (edit share) / discarded, thumbs on answers and statements, accept / dismiss on flags → `human_action` records (IDs + fixed codes, no text) and the audit log; BigQuery `c2_audit.human_action` + view `query_log_actions` ready (`22_human_action_table.sh`). c2-api is WRITER on `c2_audit`. Open: run script 22; `C2_QUERY_LOG=bigquery` at the next allowed deploy |
| M8 | Harness green | Leakage matrix = 0; ladder, ID, injection, memory-scope suites pass | 🟡 | 15 Nov: leakage 0 / 1,142 (v1) and v2 suite incl. the conversation paths 0 / 64,008; prompt-injection suite (planted orders through the normal pipeline, a model that obeys them: nothing it writes on instruction survives, 0 disclosures); memory-scope and cache-scope tests (`test_orchestrator.py`); cloud rungs = reference on 601 questions. Open: injection and memory suites as sections of the evaluation report |
| M9 | Demo-ready | Two-officer golden path runs clean inside the mock e-Office sandbox at all core touchpoints | 🟡 | 15 Nov: 17/17 touchpoint scenarios and 20/20 opposite scenarios pass in the sandbox (v1 harness); sandbox API deployed on Cloud Run (IAM-only, revision c2-api-00002-2dz). "Ask C2-24" chat panel in the sandbox file screen (sources per statement, review section, withheld count, first-cut note, insert only on click). Not yet: frontend on Cloud Run, rehearsed two-officer run |
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
| 11 Nov 2026 | ADR-0018 (Accepted for sandbox): OCR review screen; reviewer = any officer who may open the file [To confirm]; confirm re-runs the pipeline | Human review of OCR possible; D16-type misreads fixable |
| 12 Nov 2026 | ADR-0019 (Accepted): a cited order C2-24 does not hold gets the same honest message as one the officer may not see ("…may not be in C2-24's collection yet, or you may need access…"); clickable, no ID; gap list for an admin coverage page only (not built) | Officers know the collection may be incomplete; nothing about restricted records leaks |
| 13 Nov 2026 | ADR-0020 (Accepted): synthetic e-Office set v2 — 200 files on the real corpus, ~67 each FIN01/GAD01/ESE01, all 20 touchpoints and conflict types A–G, ~25% clean controls; G.O./DFA layout from real orders, note sheet/receipt/movement from public NIC e-Office references [To confirm]; 18 officers (6/dept); in `data/synthetic/mock_v1/efiles_v2/`, mock_v1 untouched; ground truth eval-only | Generator v2 work; new eval suites on v2 |
| 14 Nov 2026 | ADR-0021 (Accepted): fallback to a locally hosted open model (Ollama, loopback only) when Gemini is down; circuit breaker returns to Gemini by itself; changes CLAUDE.md §2.1 / ADR-0017 "no fallback" | docs/decisions/0021-llm-failover-to-a-local-model.md |
| 14 Nov 2026 | ADR-0022 (Accepted for the sandbox): type D = opposite disposal to most earlier same-subject files in scope, not referred to; deterministic, review only | docs/decisions/0022-type-d-precedent-check.md |
| 14 Nov 2026 | ADR-0023 (owner): knowledge graph in Cloud SQL now behind `GraphRepository`, Spanner Graph later; built on GCP by Cloud Run Job `c2-graph-build`; scope applied per node in the application, no recursive SQL | docs/decisions/0023-graph-in-cloud-sql-first.md |
| 14 Nov 2026 | ADR-0024 (Accepted for the sandbox): first cited answer — the model sees only the evidence package; a statement is shown only when the citation check confirms its quote and numbers in the cited passage; model off or failing → records listed, no uncited answer | docs/decisions/0024-first-cited-answer.md |
| 14 Nov 2026 | ADR-0025: L0/L1 on BigQuery (fixed templates, scope in the WHERE clause, re-check in code). L2 location OPEN: Vertex AI Search exists only in global / us / eu | docs/decisions/0025-bigquery-rungs-and-l2-location.md |
| 14 Nov 2026 | ADR-0026 (owner: "proceed with option B"): rung L2 on BigQuery in asia-south1 instead of Vertex AI Search — reason: Vertex AI Search has no India location and the global endpoint gives no residency guarantee; same store and same proven scope rule as L0/L1. CLAUDE.md §2.2 and the plan to be amended by the owner | docs/decisions/0026-l2-on-bigquery-in-region.md |
| 14 Nov 2026 | ADR-0027 (mock, owner): hierarchy gets a Proceedings level and a stated basis per level; classification grades keep their four levels with a basis each; Top Secret deliberately unlisted (unknown marking = outside every scope) | docs/decisions/0027-better-sourced-mock-hierarchy-and-classification.md |
| 15 Nov 2026 | ADR-0028: sandbox API on Cloud Run; e-Office papers in memory + public corpus from BigQuery / Cloud SQL behind the same rung interfaces (composite stores, scope applied by each part); L2 judged per store's own threshold | docs/decisions/0028-sandbox-api-on-cloud-run-with-cloud-rungs.md |
| 15 Nov 2026 | ADR-0029: conversation on LangGraph over AgentState (one run per turn); session memory in Cloud SQL instead of a LangGraph checkpointer (no paused graph to checkpoint); query log without question text (hash only); passages addressed to an AI may never be cited | docs/decisions/0029-conversation-orchestrator-memory-query-log.md |
| 15 Nov 2026 | ADR-0030: noting agent writes the note's sections from the first-cut sources; each line checked deterministically and removed if uncited, numbers not in sources, issue without an open point, or a proposal stating a decision | docs/decisions/0030-noting-agent-text.md |
| 15 Nov 2026 | ADR-0038: extended touchpoints 1 (diary pre-fill from the letter), 5 (previous references + sandbox Create file), 16 (closing remarks + sandbox Close file; closing note sheet joins the precedent index), 18 (OCR'd old notings, evaluated end to end); 7 extended scenarios added to the answer key (draft), harness runs them through the sandbox; all 20 touchpoints 24/24 | docs/decisions/0038-extended-touchpoints-1-5-16-18-and-evaluation.md |
| 15 Nov 2026 | ADR-0037: extended touchpoints 12 (movement summary), 17 (what changed since the decision), 19 (section handover) — deterministic from e-Office movements, the file's notes and the cited orders' status / amendments, same 404, counts over the authorised set only | docs/decisions/0037-extended-touchpoints-12-17-19.md |
| 15 Nov 2026 | ADR-0036: unusual-activity alerts for the monitoring officer — fixed signal codes on questions (instruction-like, bulk, order not open, off-topic) + refused requests from the audit trail → per-officer daily alerts with severity, department roll-up and review/escalate (codes only); asker never told; thresholds MOCK | docs/decisions/0036-monitoring-alerts.md |
| 15 Nov 2026 | ADR-0035: a mock monitoring officer has a pad with all activity, questions (words only where cleared as high as the asker), frequent and unanswered questions; Memorystore Redis caches scoped answers and question vectors (cache only, fail-open) |
| 15 Nov 2026 | ADR-0034: written references on citations, cited-paragraph preview, suggested questions, shortcuts, officer digest |
| 15 Nov 2026 | ADR-0033: answers stream as Server-Sent Events, but only statements that already passed the citation check; the final `done` answer is authoritative; the model's raw text is never sent |
| 15 Nov 2026 | ADR-0032: the officer screens run as a second Cloud Run service (c2-frontend) behind IAP, forwarding API paths to the private c2-api with their own ID token; c2-api stays IAM-only |
| 15 Nov 2026 | ADR-0031: the officer's draft actions (save / confirm as Green / discard) are e-Office actions in the sandbox, drafts the author's own until confirmed; feedback (thumbs, flag accept/dismiss, confirm edit share) is one ID-only record per action in `human_action`, evaluation data only, never read back to change behaviour |
| 14 Nov 2026 | Owner: amend CLAUDE.md §2.2 / §2.3 / §3 and the plan's L2 rows to BigQuery in region (ADR-0026). Done on the owner's copy | CLAUDE.md, IMPLEMENTATION_PLAN.md |
| 14 Nov 2026 | Owner: hierarchy and access policy stay mock for the PoC ("we will proceed with those mock only"); improve the mock from public sources | PROGRESS.md |
| 11 Nov 2026 | ADR-0017 point 4 (Accepted, owner): pin Document AI OCR `pretrained-ocr-v2.1.1-2025-01-31` (reads Telugu; recall 0.96 vs 0.84). Gate threshold stays null (owner) | Telugu scans readable; every OCR page still reviewed |
| 11 Nov 2026 | ADR-0017 (Proposed, CoE to confirm region): all regional resources in asia-south1; Gemini `gemini-3.5-flash` (+ `-lite`), the only Gemini IDs available there; no global endpoint | Whole stack stays in India; Document AI OCR available in-region (Layout Parser us/eu only) |
| 11 Nov 2026 | ADR-0016 (Accepted, owner): one guiding message for hidden and non-existent records — points to the competent authority via e-Office; never "restricted"/"not authorised" for a record (confirms existence) | Officers know how to get access; zero disclosure kept |
| 10 Nov 2026 | ADR-0015 (Accepted, owner request): citation highlights in notes — state per cited order from the pre-send A/E/F review, link only to visible orders (opens via ADR-0014), not-found named only in the note's words; open: as-of today vs note date | Officers see where in a note a citation conflicts and open the order |
| 9 Nov 2026 | ADR-0014 (Accepted, owner): document preview and download — same `can_access` re-check per request, hidden = 404 like unknown, private storage streamed by the backend, exact cited version, audited, two new leakage paths | Officers check citations against the original page |
| 4 Nov 2026 | ADR-0013: type E is marked uncertain ("may be awaiting review") when the officer may see held records of the cited order's department; held record never named | Scans wait for Document AI; "not found" was false |
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

| 4 Nov 2026 | TP2–TP4 committed as `b8e41a8`. TP13 approval brief (proposal, orders relied on, flags, precedents, movement — all from scoped parts); eval TP13 PASS (13 touchpoints); 1155 → 1156 backend tests, 13 frontend tests | Next: deterministic parts of TP6/TP7/TP14 |
| 4 Nov 2026 | Checkpoint evaluation (with / without OCR stand-in) + review report; held-scan false type-E found | Owner: fix E-uncertain first? then TP6/TP7/TP14 |
| 4 Nov 2026 | Fixed held-scan false type E (uncertain + "awaiting review"; ADR-0013); tested L3 on current-rule (trade-off, not shipped) | Owner: L3 on current-rule? then TP6/TP7/TP14 |
| 5 Nov 2026 | Owner: skip L3-on-current-rule for now. TP7 referencing in a note (endpoint, screen, harness); touchpoints 14/14 run with stand-in | TP10 harness, then TP14 / TP6 deterministic parts |
| 5 Nov 2026 | TP10 local reference with a paragraph: both paragraphs, supersession date, "current" still only with coverage; 15/15 run pass with stand-in | TP14, then TP6 deterministic parts |
| 5 Nov 2026 | TP14 DFA deterministic parts (Read list, abstract, open points; draft on click); 16/16 run pass with stand-in, 13/16 without | TP6 deterministic parts |
| 6 Nov 2026 | TP6 first-cut note (cited points, precedents vs windows, Yellow Note on click); all 17 touchpoints run — 17/17 with stand-in, 13/17 without | Owner: checkpoint + demo script, or remaining non-GCP gaps |
| 6 Nov 2026 | Checkpoint re-run + 16 opposite scenarios (no access / nothing to find / nothing wrong / in force) — 16/16; metrics unchanged | Owner: review opposites; demo script or remaining gaps |
| 10 Nov 2026 | Citation highlights in notes + click-to-open preview/download (ADR-0014 built, ADR-0015); opposites 20/20, leakage 0 on the new paths | Owner: as-of date for highlights; review OPP-16–19 |
| 11 Nov 2026 | Guiding "not available" message (ADR-0016) in API + highlights; plan §5.4/§5.9 updated | Department: confirm wording / access route |
| 11 Nov 2026 | GCP access day: APIs, 2 buckets, 2 datasets, registry, 3 SAs (no roles) in asia-south1, verified | CoE: Project IAM Admin + region confirmation |
| 11 Nov 2026 | Document AI OCR in ingestion (engine interface, cache, reviewer confirm path) + OCR accuracy suite; 1260 tests | Owner: first live OCR run on 8 synthetic scans |
| 11 Nov 2026 | First live OCR: English scans read well (recall 0.92–1.0, conf ≥0.96); split-header bug fixed → IDs 7/8; Telugu photo D16 not read | Owner: Telugu probe; gate calibration decision |
| 11 Nov 2026 | Evaluation on real OCR (v2.1.1 recorded + simulated reviewer): 17/17 touchpoints, 20/20 opposites, leakage 0/1126, metrics unchanged | Next: OCR reviewer screen or GCP build-out |
| 11 Nov 2026 | OCR review screen (ADR-0018): scan beside OCR text; confirm / correct / reject; queue access-checked; D16 fixed by correction | Department: who may confirm OCR |
| 11 Nov 2026 | GCS document store live: preview byte-identical from the bucket, hidden still 404, 21 objects stored | Next: Cloud SQL or Vertex AI Search |
| 11 Nov 2026 | Old public corpus archived (636 MB, 831 orders → archive/2026-11-11); new data root; Cloud SQL script sized to db-g1-small | Owner: run collection + create Cloud SQL |
| 12 Nov 2026 | Full collection running (Internet Archive mirror); scope 2016–2025, as of 31-12-2025 (owner); GOIR still blocked | After run: 2016–2017 pass, coverage, hand-download list |
| 12 Nov 2026 | Cloud SQL `c2-sql` created (owner). Postgres-backed review queue, confirmed OCR text and append-only audit log behind the existing interfaces; schema 0001 + bootstrap script with least-privilege grants; 1290 tests pass against local Postgres 16 | Done 15:34 IST: tables + grants on `c2-sql`, IAM login checked |
| 12 Nov 2026 | Public corpus collection finished: 1,126 orders (FIN01 507, GAD01 380, ESE01 239), 20 SUPERSEDES / 78 AMENDS with both ends held; audit run; ranked hand-download list (28 tier-1) | Hand downloads (tier 1–2), then upload to `public-go/` |
| 12 Nov 2026 | Collection rounds 2–3 (+11 orders → 1,137); ADR-0019: one shared, clickable "not in the records available to you / may not be in C2-24's collection yet" message; tests green | Gazette batch mode (owner OK), admin coverage page |
| 12 Nov 2026 | GOIR re-check 21:02 IST: robots.txt still `User-agent: * / Disallow: /` (`/` and `/Reports.aspx` disallowed); only robots.txt fetched | Hand downloads stay the GOIR route; re-check before the next collection |
| 13 Nov 2026 | Document AI OCR (`ocr_corpus.py --scans-too --force --apply`, pinned v2.1.1, asia-south1) on 25 named files the sandbox could not read: 25/25 ok, 263 pages (≤ US$0.39 list), exit 0. Mean confidence 0.905–0.993 except AP-ESE01-GOMS-66-2018 at 0.658 (text reads cleanly; OCR review gate, ADR-0018). Old text kept as ocr.archive.txt | `extract_relations.py staging`, `audit_corpus.py`, `reconcile_dates.py`, then re-upload with `08_upload_public_corpus.sh` |
| 13 Nov 2026 | B / G hand check of the live Gemini run; excerpt windows, gazette citations in notes, prompt v2; 1343 passed | Owner re-runs presend_v2 --live |
| 13 Nov 2026 | B / G hand check of the prompt-v2 run (G 7/10); fixes: hyphen spacing in quotes, unnumbered Read entry, inferred supersession no longer skips a pair; replay G 8/10, F 50/76; 1347 passed | Owner runs presend_v2 --live (1 question) |
| 13 Nov 2026 | FIN 106 B found live (B 8/8); --count shows unsaved questions; gazettes 3644/1905 read from the page-1 text layer (82/83 cited orders indexed); gazette ranks as what it notifies; duplicate flags removed; 1352 passed | Owner: 3-question live run; decide FIN 130/137 findings; then type C |
| 13 Nov 2026 | Type C on v2 (rules from 5 real orders, C 10/12, 0 false flags); answer-key fixes FIN 130 / 137; coverage tool reads v2; 1366 passed | Owner: 5-question live run; choose holdback; next slice type D / first cited answer |
| 13 Nov 2026 | Demo holdback (GAD 139/2025, 2 open files, order-arrives replay); SECURITY: file papers no longer public (4,182 v2 disclosures → 0, ADR-0009 addendum); 1369 passed | Owner: re-upload corpus, 5-question live run; then type D |
| 14 Nov 2026 | LLM failover to a local Ollama model with automatic return (ADR-0021); unanswered-question reasons in presend_v2; 1374 passed | Owner: name the Ollama model; then measure it; type D |
| 14 Nov 2026 | Set v2 audit + fixes: sandbox loads orders that change cited ones (120), E files cite as printed, FIN C1/C2 and GAD G3 rewritten; B 9/9, C 12/12, E 18/18, F 57/76; 1376 passed | Owner: OCR 8 scans, 1 Gemini question; then type D |
| 14 Nov 2026 | Public corpus post-OCR checks: extract_relations (4,258 candidate edges, 1,374 orders), audit_corpus (1,374 audited, 0 problems), reconcile_dates --write (1,073 agree, 290 unreadable, 11 verified, 0 mismatches); upload dry-run verified (1,374 staging + 1 holdback GAD 139/2025); 1376 tests passed | Upload to GCS (`APPLY=1 infrastructure/gcp/08_upload_public_corpus.sh`), then presend_v2 live run |
| 14 Nov 2026 | Type D check (ADR-0022) + set v2 type D repair: all seven types found on v2 (D 15/15), clean 0/41; 1381 passed | Owner: 2 Gemini questions, check bucket for held-back order; next M4 cited answer |
| 14 Nov 2026 | Public corpus re-uploaded (`APPLY=1 08_upload_public_corpus.sh`, exit 0) after OCR of 7 FIN scans (94 p, conf 0.984–0.993), `join_ocr_cache.py` (63 joined), `extract_relations.py staging` (4,258 edges), `audit_corpus.py` (no problems), `reconcile_dates.py --write` (1,073 match, 290 unreadable, 11 verified). Bucket `public-go/`: 1,374 order.pdf / ocr.txt / meta.json, 347 ocr_cache, 323 ocr_recorded, relations + provenance manifests = local counts; 0 archive/_review/holdback/partial objects. Gemini presend runs `corpus` and `typed` (0 incomplete, 0 false flags on clean) | Index the bucket for retrieval when P3 work starts |
| 14 Nov 2026 | Knowledge graph for GCP (ADR-0023): `app.graph.build` (whole corpus through the normal pipeline), `PostgresGraphRepository`, migration `0002_graph`, Cloud Build + Cloud Run Job scripts 13 / 14; local proof on 120 orders into Postgres 16 (114 nodes, 176 edges); 1400 passed. Milestones M1–M3 re-assessed | Owner: `12_cloudsql_schema.py`, `13_backend_image.sh`, `14_graph_job.sh` (APPLY=1). Then: API reads the graph from Cloud SQL; first cited answer (M4) |
| 14 Nov 2026 | Owner ran 12 (tables + grants: ok), 13 (image built in asia-south1: ok), 14 (job failed twice at the raw-bucket mount: `c2-ingest` lacks storage access) → `15_graph_job_access.sh` (bucket-level roles + Cloud SQL roles). Build made robust: one failing order is held, not fatal. First cited answer (ADR-0024, `/assist/ask`, `evaluation/ask_golden.py`). v2 outsider leakage suite (`evaluation/leakage_v2.py`) | Owner: 15 then 14; `ask_golden.py --live`. Then: cloud rungs (BigQuery L1, Vertex AI Search L2) fed from the job's output; better mock hierarchy / access policy from public sources |
| 14 Nov 2026 (evening) | Roles granted to c2-api / c2-ingest by the project owner; job ran end to end (50-order trial with its own Cloud SQL load). Sandbox memory fixed (recorded OCR read per file: 3.3 GB → 0.9 GB); full v2 leakage run 0 / 55,482. BigQuery L0/L1 rungs + job load step + `cloud_ladder_check.py` (ADR-0025). Whole-corpus run analysed: 436 text-and-image PDFs need Document AI readings (`ocr_corpus.py --ids-file --cache-only`, new). `detect` no longer fails on inline images without an image library | Owner: OCR the 436 files, join, upload, rebuild image, full job, `cloud_ladder_check.py`, `ask_golden.py --live`; decide L2 location (ADR-0025). Then: trace 3 `InvalidCanonicalIdError`, API on Cloud Run reading the cloud rungs, better-sourced mock hierarchy / access policy |
| 14 Nov 2026 (night) | Rung L2 on BigQuery (ADR-0026): `bigquery_l2.py` (passages, Vertex embeddings in region, fixed hybrid template), job step `--load-passages`, `17_embedding_check.py`, L2 section in `cloud_ladder_check.py`; 1422 passed | Owner: `17_embedding_check.py`, then the commands in the ledger entry. Then: measure L2 ranking on the golden questions; API on Cloud Run on the cloud rungs; trace 3 `InvalidCanonicalIdError`; better-sourced mock hierarchy / access policy |
| 14 Nov 2026 (late) | CLAUDE.md and plan amended for ADR-0026. The 3 `InvalidCanonicalIdError` orders traced by running the pipeline over the whole corpus in the device shell: gazette-folder files with no readable masthead that print a bare G.O. number; the folder tag was borrowed as a department → fixed with a regression test (now held: own reference not resolvable). Mock hierarchy / classification re-sourced (ADR-0027); v1 harness unchanged; 1423 passed | Owner: commands in the final message (embedding check → OCR → upload → image → job → cloud check). Open: API + frontend on Cloud Run (P8: needs the synthetic set in a bucket and a public-corpus path option), runtime reading the cloud rungs, L2 ranking measurement and threshold |
| 15 Nov 2026 | Reconciled the other session (8 GiB job, 1,290 indexed, cloud check 601/601 same, API deployed). Composite rungs + Cloud Run scripts (ADR-0028); M4 rework after live run 1 (package recall 13 → 18 of 19); neutral 503 on store errors; `/reference` via cloud; cloud passages as evidence text; milestones M5–M9 re-assessed with evidence; 1442 passed; leakage v2 0 / 55,482 | Owner: admin grants (bigquery.jobUser, aiplatform.user ×2 accounts); `ask_golden.py --live --label v2`; then job + redeploy with EMBEDDING_MODEL=gemini-embedding-001 |
| 15 Nov 2026 (morning) | Owner: no redeploy now; build the remaining plan blocks while access waits. Built: conversation orchestrator (LangGraph over AgentState), session memory (Cloud SQL), query log, golden-path draft step, injection suite + `addressed_to_ai` hardening (ADR-0029) | Owner: migration 0003 + query-log table later; next: Gemini noting text, frontend chat |
| 15 Nov 2026 | Cloud Run `c2-api` deployed: revision 00001 failed at start (FileNotFoundError, held-back order G.O.Ms.139/2025 GAD not in the bucket). Fix: uploaded only `holdback/AP-GAD01-GOMS-139-2025/order.pdf` to `public-go/holdback/` (SHA-256 = public_holdback.csv); graph/BigQuery build reads `rule-library/` only, so the order stays out of the initial load (ADR-0020 addendum intent kept; `08_upload_public_corpus.sh` still excludes holdback). Revision `c2-api-00002-2dz` serving; unauthenticated → 403 (private); signed-in `/assist/search` 200 (first call 319 s). **Blocker:** SA `c2-api` (and `c2-ingest`) lack `roles/bigquery.jobUser` and `roles/aiplatform.user`; an exact lookup of a BigQuery-only order → HTTP 500 (403 `bigquery.jobs.create`). Developer account cannot set project IAM. Also: 17_embedding_check (gemini-embedding-001 best for Telugu, 0.72), 19_upload_synthetic done, ask_golden live: 11/19 answered with checked citation, 5/5 no-answer kept, 0 forbidden records | Project admin grants the two roles to both SAs; then re-test `GET /assist/documents/AP-GAD01-GOMS-31-2018`; 500 → neutral denial message is a code follow-up |
| 15 Nov 2026 | M4 live run `ask_golden.py --live --label v2` (Q08 retried once: first Gemini call failed, engine unavailable): 15/19 answered with checked citation, 12 on key, 0 not run, 5/5 no-answer kept, 10 statements removed by citation check, **0 forbidden records**; 8 scans confirmed by simulated reviewer. Image rebuilt (`13_backend_image.sh`, Cloud Build SUCCESS 1m32s) → `backend:20261115-0817`, tagged latest; `c2-api` still serves revision 00002 (image 20261115-0331) | Redeploy `20_api_service.sh` when wanted; BigQuery/Vertex roles still pending the admin |
| 15 Nov 2026 | Noting agent live (`noting_live.py --live`, 3 Gemini calls, saved answers 116 → 119): 4 files, 3 notes written, 50 lines kept, 1 removed, 0 forbidden records named (report `evaluation/reports/2026-11-15-noting.md`). File 2881930 as U01 (TP11-c) gets no note by design: its first-cut has no provision/precedent point, so no call is made, but the label wrongly says "not drafted (needs Gemini)" (`agents/routes.py` `_note_fields`); follow-up: a distinct message. Cloud SQL: `APPLY=1 12_cloudsql_schema.py` applied 0001–0003 (0003_sessions new), 15 grants, postgres password reset unseen, developer read check OK. `APPLY=1 21_query_log_table.sh`: `c2_audit.query_log` created (DAY partition on ts, 22 fields); the c2-api write grant FAILED (`bq add-iam-policy-binding` on a dataset: "requires allowlisting"). c2-api is not yet on the `c2_audit` access list. Next: add it as a dataset WRITER (owner action), fix the script to use dataset access, then set `C2_QUERY_LOG=bigquery`. |
| 15 Nov 2026 | `SKIP_TABLE=1 APPLY=1 21_query_log_table.sh` (dry run checked first): c2-api added as WRITER on the `c2_audit` access list only; verified with `bq show`. `C2_QUERY_LOG=bigquery` waits for the next approved c2-api deploy. Noting check with the new prompt (`noting_live.py --live --label v2`, 3 Gemini calls, saved answers 119 → 122): 4 files, 3 notes written (all 6 sections each), 44 lines kept, 0 removed (v1: 50 kept / 1 removed), 0 forbidden records named; 2881930 as U01 now says "not drafted: no order paragraph or earlier decision applies to write from" (report `evaluation/reports/2026-11-15-noting-v2.md`). Still pending: admin roles bigquery.jobUser + aiplatform.user for c2-api and c2-ingest. |
| 15 Nov 2026 | `18_service_access.sh`: admin roles now held (c2-api, c2-ingest: aiplatform.user, bigquery.jobUser, cloudsql.client, cloudsql.instanceUser). `22_human_action_table.sh` (dry run, then APPLY=1): `c2_audit.human_action` (DAY on ts) + view `query_log_actions` created. Image `backend:20261115-1104` built (1m24s), tagged latest. Job `c2-graph-build-z29sb` with EMBEDDING_MODEL=gemini-embedding-001 (~45 min): 1373 given, 1290 indexed, 83 held for review, 1669 edges; passages table 17,696 passages / 1,290 docs, 1,969 embedding requests (768 dims, asia-south1). `cloud_ladder_check.py`: L0 453/0 diff, L1 27/0, L3 size 1/0, L3 walk 120/0, L2 top-10 18/0: SAME on every question. L2 threshold evidence (proposal only, not applied): known-item recall@1 0.45, @10 0.88; known-item best score min 0.743 / p10 0.751; off-domain max 0.561; proposed `C2_L2_CLOUD_MIN_SCORE`=0.656 awaiting owner approval. Not yet done: c2-api redeploy (step 6), retry GET /assist/documents/AP-GAD01-GOMS-31-2018. |
| 15 Nov 2026 | Step 6: `EMBEDDING_MODEL=gemini-embedding-001 APPLY=1 20_api_service.sh` (dry run checked): revision `c2-api-00003-jwb` serving image latest (20261115-1104), private, LLM recorded, C2_QUERY_LOG=bigquery. Checks as V14 (GAD01 Secretary, department scope, SECRET; seed v2 IDs are V01–V21, not U01): (1) GET /assist/documents/AP-GAD01-GOMS-31-2018 → **404 neutral denial** (no 500 any more; 373 s on a cold start); the order IS in `c2_metadata.documents` (GAD01, CABINET-II, UNCLASSIFIED), so the 404 is either the L0+can_access path not seeing it or `run.sources` having no stored file for it: to diagnose. (2) POST /assist/chat → 200 in 17 s, L2, 8 records, status not_run (recorded mode, no saved answer); row 599d6503b08e4798 in `c2_audit.query_log`. (3) POST /assist/feedback thumbs_up → 200; row in `c2_audit.human_action`; view `query_log_actions` joins it. |
| 15 Nov 2026 | Image `backend:20261115-1628` (1m27s). Job `c2-graph-build-f8kkl`: 1373 given, 1290 indexed, 83 held, 1669 edges; passages 17,696 in 52 parts, 0 embedded now, 1290 kept, 0 embedding requests. Redeploy: revision `c2-api-00004-j75`. As V14: GET /assist/documents/AP-GAD01-GOMS-31-2018 → **200** (365 s cold start), media_type application/pdf, version src-f19ceb5fe25a47ec; /preview and /download → 200, application/pdf, 486,408 bytes, 10-page PDF, SHA-256 f19ceb5f…8bbe matches the version ID. `/file` → 404 Not Found: no such route (routes are /preview and /download). Open: 5–6 min cold start (sandbox built at startup), to fix with the frontend deploy. |
| 15 Nov 2026 | Image `backend:20261115-1745`. Job `c2-graph-build-hcvdh` (918 s build): 1290 indexed, 83 held, 1669 edges, 0 embedding requests; saved reads written to `artifacts/graph/pdf_scans/` (1,376 objects). Redeploy: revision `c2-api-00005-cxp`; c2-api given storage.objectViewer on the artifacts bucket. Cold start (rollout instance): instance start 12:37:09 → app startup complete 12:38:21 (≈30 s in the app) → probe OK 12:38:29 (≈80 s total); first call as V14 then 1.9 s, second 1.1 s (was ≈365 s). The log line "sandbox built at start in N s" did not appear. Frontend `23_frontend_service.sh` (IAP_MEMBERS=user:venkat.c@…, dry run checked): IAP API enabled, image `frontend:20261115-1811` built (58 s) + tagged latest; then **FAILED** at `gcloud run services add-iam-policy-binding c2-api … roles/run.invoker`: PERMISSION_DENIED run.services.setIamPolicy (developer holds roles/editor only). c2-frontend NOT deployed. Needs owner/admin: either grant the developer roles/run.admin + roles/iap.admin, or run the three IAM bindings (c2-frontend → run.invoker on c2-api; IAP agent → run.invoker on c2-frontend; user → iap.httpsResourceAccessor) themselves. |
| 15 Nov 2026 | `APPLY=1 25_query_log_columns.sh` (dry run checked): `c2_audit.query_log` now 24 columns (+ question, clearance_rank, NULLABLE). Image `backend:20261115-1834`; redeploy revision `c2-api-00006-c58`. `PART=dev APPLY=1 23_frontend_service.sh` (dry run checked): image `frontend:20261115-1913` (1 m), service `c2-frontend` revision 00001-2fg deployed with --iap (the developer role was allowed), URL https://c2-frontend-820308448289.asia-south1.run.app. Owner part (`PART=owner IAP_MEMBERS=… 23_frontend_service.sh`: c2-frontend → run.invoker on c2-api, IAP agent → run.invoker on c2-frontend, user → iap.httpsResourceAccessor) NOT run: needs Run Admin + IAP Admin. Redis (`24_memorystore.sh`, billed ≈$35–50/month) not run: awaiting explicit owner go-ahead. |
| 15 Nov 2026 | Noting agent v2 (ADR-0030 addendum): subject is source S1, kept lines must share ≥50% content words with cited sources (only run 1's 2 misattributed lines of 50 fall below), distinct no-note reasons (`no_sources` for 2881930 — model not asked; `engine_off`, `engine_down`, `all_removed`); prompt `noting_draft.v2`. Dataset grants now via the dataset access list (`lib.sh` `bq_dataset_grant`, used by `18_service_access.sh` and `21_query_log_table.sh`; `SKIP_TABLE=1` re-runs 21 without `bq mk`). Checks: pytest 1468 passed / 6 skipped, ruff, mypy clean. Next: owner grants c2-api WRITER on `c2_audit`; re-run `noting_live.py --live --label v2`; `C2_QUERY_LOG=bigquery` at the next allowed c2-api deploy. |
| 15 Nov 2026 | HITL block (ADR-0031): sandbox draft actions save / confirm → Green Note / discard (author only; others get the unknown-draft 404; AI draft markers removed on confirm; versions kept; `NOTE_CONFIRMED` event); `DraftOutcome` through the connector; `/assist/feedback` (answer: own session only; statement: visible record only; flag: openable file only; fixed reason codes); `HumanAction` log in memory / BigQuery; `22_human_action_table.sh` (table + `query_log_actions` view, dry run checked). Frontend: Edit / Save / Confirm → Green / Discard on the author's drafts, 👍/👎 on answers and statements, Needs review / Set aside on pre-send flags. Checks: pytest 1479 passed / 6 skipped; ruff, format, mypy clean; frontend tsc, Vitest 33, build OK; browser run (U01: first-cut → insert → edit → save v2 → confirm → Note #2 Green, markers gone, edit kept; flag set aside; no console errors). |
| 15 Nov 2026 | Admin granted bigquery.jobUser + aiplatform.user to c2-api and c2-ingest. Readied the L2 build for a long billed run: `VertexEmbedder` retries quota/overload answers (2→60 s, 6 tries, then fails closed) and drops to one text per call after a refused batch; passages written as resumable part files of 25 orders with manifests (model + text hash), only complete, current parts loaded (list of URIs), `loaded.json`; `14_graph_job.sh` passes the gs:// folder; `cloud_ladder_check.py` reads the loaded parts and adds L2 threshold evidence (known-item recall, off-domain scores, proposal only); `20_api_service.sh` sets `C2_QUERY_LOG=bigquery` (QUERY_LOG=memory to keep it local), embedding dimensions, optional owner-approved `L2_MIN_SCORE`. Checks: pytest 1485 passed / 6 skipped (new `test_embedding_job.py`, 6); ruff, format, mypy clean; dry runs of 14 and 20 checked. |
| 15 Nov 2026 | Reviewed the job and cloud-check results above: accepted. L2 threshold 0.656 NOT set (ADR-0026 addendum): in the ladder it only names the answering rung (`answered_by`); L3 still runs whenever relations are needed, so no answer changes; and the evidence tests off-domain questions, not in-domain wrong-order matches (recall@1 0.45 even with copied words). Revisit with officer-worded public-corpus questions. Follow-up: the 12 % of copied-word questions missing the top 10. Go-ahead for the c2-api redeploy (step 6). |
| 15 Nov 2026 | Fixed the 404 on `GET /assist/documents/AP-GAD01-GOMS-31-2018` (row above). Cause: the service holds files only for the ~120 sandbox orders (`public_index.csv`); this order is BigQuery-only, so the visible record had no stored file. Fix (ADR-0028 addendum): the graph build writes `source_path` + `source_sha256` into `c2_metadata.documents`; `CloudSourceFiles` reads them with the officer's scope in the WHERE clause, reads the mounted corpus, refuses paths outside it and bytes that do not match the hash; the document routes use `AssistRuntime.stored_source` (memory first). New `test_cloud_sources.py` (7). Checks: pytest 1492 passed / 6 skipped; ruff, format, mypy clean. Next: owner rebuilds the image, re-runs the graph job (passages reused: no embedding requests), redeploys, re-tests. Known: first request after a cold start 319–373 s. |
| 15 Nov 2026 | `/file` was my wrong path in the instructions (the routes are `/preview` and `/download`; both 200, hash matches): no change. Cold start (319–373 s): profiled the sandbox build — 99 % ingestion, nearly all pypdf reading the 120 public orders three times. Fixes (ADR-0028 addendum 2): `pdf_scan` reads each PDF once per run; `_has_image` answers like `page.images` without a second parse (whole public corpus 1,374 PDFs / 7,682 pages: 0 different); graph job saves page reads to `graph/pdf_scans/` (`--pdf-scans`), c2-api reads them read-only (same pypdf version only); `C2_SANDBOX_WARM_START` builds at instance start with `--cpu-boost` and a 10-min startup probe. Local build 113.7 s → 43.6 s → 2.4 s, same 343 indexed / 292 held and identical texts. Frontend on Cloud Run (ADR-0032): `frontend/Dockerfile` (built screens + `frontend/server/server.py` pass-through adding c2-frontend's ID token; browser Authorization/cookies/IAP headers dropped), `23_frontend_service.sh` (Cloud Build, run.invoker on c2-api, deploy with `--iap`, IAP agent invoker, `IAP_MEMBERS` accessors). Checks: pytest 1497 passed / 6 skipped (new `test_pdf_scan.py` 3, `test_startup.py` 2); frontend server tests 4; ruff, format, mypy clean; dry runs of 14, 20, 23. |
| 15 Nov 2026 | Streamed answers (ADR-0033): `POST /assist/chat/stream` (SSE) runs the same turn as `/assist/chat` and sends stage events (searching, found N, writing, checking), each statement only after it passes the citation check on its own, then `done` with the full answer (authoritative) or a neutral `error`; the model's raw text is never sent. `stream_json` (Gemini `generate_content_stream`; saved-answer and Ollama clients hand over whole answers), `StatementStream` incremental reader; frontend server passes streams through unbuffered; chat panel shows the stage, reveals checked statements at reading pace, Stop, falls back to `/chat`. Checks: pytest 1503 passed / 6 skipped (new `test_streaming.py` 6); frontend server 5; Vitest 35; tsc, build; ruff, format, mypy clean; browser run through the frontend server (U01, status question: stage → statement → done, no console errors). |
| 15 Nov 2026 | Read the owner's run above: cold start ≈80 s → first call 1.9 s (was ≈365 s). Fixed: the start-up timing line now prints (uvicorn kept app `log.info` hidden). Frontend IAM failure: `23_frontend_service.sh` split into `PART=dev` (build + deploy, editor role) and `PART=owner` (the three IAM bindings, Run Admin + IAP Admin; `SKIP_BUILD=1 TAG=…` reuses an image). Built (ADR-0034): written references on every citation (`app/identifiers/display.py`) + Copy with reference; cited-paragraph hover preview (`GET /assist/documents/{id}/context`, paragraph only, same 404); suggested questions from the file's subject and flagged orders; shortcuts Ctrl/⌘+K, Ctrl/⌘+Enter, J/K, ?; digest `GET /assist/digest` (files waiting, changed cited orders; connector `officer_files`). Built (ADR-0035): mock monitoring officer M01 (sandbox.yaml), monitoring pad `GET /assist/monitor` + screen (KPIs, questions/day, answer time, outcomes, step, activity with filter + CSV, frequent, unanswered, officers, slowest, feedback, cache, live 30 s); question words in the query log (`question`, `clearance_rank`; shown only to a monitor cleared as high as the asker); Redis answer cache + question-embedding cache (scoped keys, invalidation by cited record, TTL, fail-open bypass, stop serving after a failed invalidation); `24_memorystore.sh` (Basic 1 GB, AUTH, Secret Manager), `20_api_service.sh REDIS=1` (Direct VPC egress), `25_query_log_columns.sh`. Checks: pytest 1516 passed / 6 skipped (new `test_officer_tools.py` 7, `test_monitoring.py` 6); frontend server 5; Vitest 40; tsc, build; ruff, format, mypy clean; browser run (U01 digest, chips, status answer, hover preview, copy, shortcuts; M01 lands on the pad with U01's question; no console errors). |
| 15 Nov 2026 | Monitoring alerts (ADR-0036), owner request: signal codes on each question in the query log (`flags`: instruction_like, bulk_request, named_unavailable — hidden and unknown alike — off_topic; patterns and thresholds in `backend/config/monitoring.yaml`, MOCK), refused requests read from the audit trail (`refused_since`), attempts to open the pad now recorded (same 404), alerts per officer per day (pad probe, instruction-like, repeated refusals in 30 min, bulk, volume, off-topic, after hours) with stable IDs, department roll-up, review / escalate route (fixed codes; not counted as feedback). Pad: Alerts tab (department cards, filters, examples with words gated by clearance, actions), open-alerts KPI and banner, flag chips + "Flagged only" in the activity log. Checks: pytest 1523 passed / 6 skipped (new `test_alerts.py` 7); Vitest 42; tsc, build; ruff, format, mypy (app) clean; browser run (U02/U03/U01/U04/U05 activity → 6 alerts, review removes one). After the owner's run above: `flags` is a new query-log column, so `25_query_log_columns.sh` must run again before this image is deployed (rows with an unknown field are rejected). |
| 15 Nov 2026 | After `gcloud auth login` (sign-in had expired): `APPLY=1 25_query_log_columns.sh` → `c2_audit.query_log` 25 columns (+ flags, REPEATED). Image `backend:20261115-1938`; revision `c2-api-00007-bc7`. `PART=dev APPLY=1 23_frontend_service.sh`: frontend image rebuilt (1m03s), revision `c2-frontend-00002-497`. Owner `PART=owner` grants still pending (Run Admin + IAP Admin). |
| 15 Nov 2026 | Extended touchpoints 12, 17, 19 (ADR-0037), owner: "proceed with building touch points": `POST /assist/movements` (remarks at each movement, the note put up before it, where pending / overdue / sent back), `POST /assist/since-decision` (last direction + cited orders' status changes, amendments and clarifications after vs before it), `GET /assist/handover` (own section: files in hand, orders worked under — "in force" only when covered, else "status not confirmed" — orders no longer in force, recent decisions); connector `FileContext.movements/state/created_*`, `section_files`; screens: two Assist chips + Section handover panel. Fixed: set v2 note signatures (date first, name/post below) were read wrongly by `parse_notes` (also fixes File so far / brief on v2); concurrent first requests each built the sandbox (functools.cache) → one build behind a lock. Checks: pytest 1532 passed / 6 skipped (new `test_extended_touchpoints.py` 8, startup +1); eval: leakage 0/1142, touchpoints 17/17, opposites 20/20, metrics unchanged; Vitest 45; tsc, build; ruff, format, mypy clean; browser run on seed v2 as V16 (handover, movement summary, since the last direction; no console errors). Redis: not run (no go-ahead in this message). |
| 15 Nov 2026 | Owner: hold Redis until the organisation approves (24_memorystore.sh not run; code stays off without C2_REDIS_URL). Built extended touchpoints 1, 5, 16, 18 (ADR-0038): `/assist/diarise` (diary fields from the letter's own text, OCR drafts marked, nothing guessed), `/assist/previous-references` + `POST /sandbox/files`, `/assist/closing-remarks` + `POST /sandbox/files/{no}/close` (closing note sheet → ingestion via FILE_CLOSED → precedent index), TP18 = existing OCR review flow; screens: Pre-fill diary details, Create a file, Closing remarks. Evaluated all 20 at once: 7 scenarios added to `touchpoint_scenarios.json` (draft, from seed/index/relations), `evaluation/harness/sandbox_flow.py`; report `2026-11-15-touchpoints-all`: touchpoints 24/24 (TP01 50/50 fields), leakage 0/1142, retrieval/conflict metrics and opposites 20/20 unchanged. Checks: pytest 1558 passed / 6 skipped; Vitest 48; tsc, build; ruff, format, mypy clean; browser run (U01 pre-fill + create file, U06 close file; no console errors). |
| 15 Nov 2026 | Review of the 7 new touchpoint scenarios (TP01, TP05, TP12, TP16, TP17, TP18, TP19; draft, owner review) against seed.json, access_matrix.csv, documents_index.csv, relations.csv: TP01, TP05, TP12, TP16, TP18 match the seed; TP17 matches (D17 cites only D03; D04 supersedes D03 from 12-05-2025; D05 later clarifies D04, optional to mention). **TP19 incomplete:** open file 2881930 (D29) cites D08 G.O.Rt.No.1184/2025, expired (effective to 31-03-2026); the app's /assist/handover for U01 already lists it (2 orders no longer in force) but the scenario expects only D03 → owner to add {cited: D08, change: expired} + D08 in docs. Tests: `pytest tests/unit/test_touchpoint_scenarios.py test_extended_touchpoints.py test_touchpoints_1_5_16_18.py` → 90 passed. Deploy: image `backend:20261115-2247`, revision `c2-api-00008-5ll`; frontend image `frontend:20261115-2250`, revision `c2-frontend-00003-whf`. Owner PART=owner grants still pending. |
| 15 Nov 2026 | Acted on the owner's scenario review: TP19 answer key corrected — G.O.Rt.No.1184/2025 (D08, expired 31-03-2026, cited by D29 in open file 2881930) added to `no_longer_in_force` and `docs`, each entry now carries its change. The harness was too lenient (subset checks), so the gap never failed: TP19 now compares files in hand, decisions and orders no longer in force exactly, TP17 its changes exactly; checked that the old TP19 key now FAILS. Re-run `evaluation/reports/2026-11-15-touchpoints-reviewed`: touchpoints 24/24, leakage 0/1142, other metrics unchanged; pytest 1558 passed / 6 skipped. Deployed by the owner: `c2-api-00008-5ll`, `c2-frontend-00003-whf` (this harness change needs no redeploy). |

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

### 2026-11-15 · P8 / P7 · M9, M10 · Extended touchpoints 1, 5, 16, 18 and all 20 evaluated (ADR-0038)
- **Status:** DONE locally (code, tests, evaluation, browser run); the 7 new scenarios await owner review (answer key)
- **Plan section:** §11.5 (1, 5, 16, 18), §11.6, §13.2; CLAUDE.md §9.3
- **Files changed:** new `backend/app/ingestion/diarise.py`, new `backend/app/noting/closing.py`, `backend/app/connectors/eoffice.py` (`ReceiptContext.attachment_uri`, `file_computer_no`), `backend/app/eoffice_mock/{adapter,routes}.py` (create / close file, closing note sheet, FILE_CLOSED), `backend/app/agents/{runtime,routes}.py` (`letter_text`, FILE_CLOSED sync, 3 routes), new `backend/tests/unit/test_touchpoints_1_5_16_18.py`, `backend/tests/unit/{test_touchpoint_scenarios,test_eval_harness}.py` (20 touchpoints, 24 scenarios), `data/synthetic/mock_v1/ground_truth/touchpoint_scenarios.json` (+7 scenarios, draft), new `evaluation/harness/sandbox_flow.py`, `evaluation/harness/suites.py`, new report `evaluation/reports/2026-11-15-touchpoints-all.{md,json}`, `frontend/eoffice/src/{types.ts,api.ts,styles.css,tools.test.tsx,components/Receipts.tsx,components/AssistPanel.tsx,components/FileList.tsx}`, new `frontend/eoffice/src/components/NewFile.tsx`, new `docs/decisions/0038-…md`, `docs/LEARNINGS.md`
- **Tests/commands run:** `uv run pytest -q` → 1558 passed, 6 skipped ✅ · `uv run python ../evaluation/run_eval.py --label touchpoints-all --compare …baseline.json` → touchpoints 24/24, leakage 0/1142, other metrics unchanged ✅ · ruff (backend + evaluation), format, `mypy app` ✅ · Vitest 48 ✅ · tsc, build ✅ · browser (v1 sandbox): U01 pre-fill + create file, U06 closing remarks + close; no console errors ✅
- **Acceptance evidence:** report rows TP01 (50/50 fields, 3 by OCR, outsider same 404), TP05 (3/3 expected, confidential file never offered), TP12, TP16 (holder closes; non-holder 404; closed notes found by U04, never U01), TP17, TP18 (indexed only after review; never for U01, nor in U01's queue; notes #6–#8 join the chain), TP19
- **Security / temporal / citation implications:** no model; access re-checked on every route; hidden = unknown; sandbox actions are the officer's simulated clicks
- **Known gaps / blockers:** note-revision IDs (`-C01` vs manifest `-R1`) — owner rule; TP05 ranking not calibrated (precision 0.6); Redis on hold (organisation approval)
- **Exact next action:** reviewed by the owner 15 Nov (TP19 corrected, harness checks made exact; report `2026-11-15-touchpoints-reviewed`); deployed `c2-api-00008-5ll` / `c2-frontend-00003-whf`; admin `PART=owner` still pending

### 2026-11-15 · P8 · M10 · Extended touchpoints 12, 17, 19 (ADR-0037)
- **Status:** DONE locally (code, tests, browser run on seed v2); touchpoint scenarios for 12/17/19 not yet in the ground truth (owner's answer key)
- **Plan section:** §11.5 (12, 17, 19), §6, §4
- **Files changed:** `backend/app/connectors/eoffice.py` (`MovementRef`, `FileContext` fields, `OfficerFile.state`, `section_files`), `backend/app/eoffice_mock/adapter.py`, new `backend/app/noting/movements.py`, new `backend/app/temporal/since_decision.py`, new `backend/app/precedent/handover.py`, `backend/app/noting/chain.py` (v2 signature layout), `backend/app/agents/routes.py` (3 routes), `backend/app/main.py` (one build behind a lock), new `backend/tests/unit/test_extended_touchpoints.py`, `backend/tests/unit/test_startup.py`, `frontend/eoffice/src/{types.ts,api.ts,styles.css,tools.test.tsx,components/AssistPanel.tsx,components/FileList.tsx}`, new `frontend/eoffice/src/components/Handover.tsx`, new `docs/decisions/0037-extended-touchpoints-12-17-19.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** `uv run pytest -q` → 1532 passed, 6 skipped ✅ · eval harness vs 2026-11-15 baseline: leakage 0/1142, touchpoints 17/17, opposites 20/20, retrieval/conflict metrics unchanged ✅ · ruff, format, `mypy app` ✅ · Vitest 45 ✅ · tsc, build ✅ · browser (seed v2, V16): handover, movement summary, since the last direction; no console errors ✅
- **Acceptance evidence:** API tests: notes matched to movements, last direction, G.O.Ms.88/2022 superseded by 31/2025 after the decision; hidden (2633187) and unknown files give the same 404 on both file routes; U01's handover excludes the confidential file U02 sees and counts one closed file fewer
- **Security / temporal / citation implications:** no model; only records the officer may see; status "in force" never claimed without coverage; changes split by the decision date
- **Known gaps / blockers:** reassignment event (who may reassign) not built — department policy; ground-truth scenarios for 12/17/19 to add with the owner
- **Exact next action:** owner: image (13) → deploy c2-api (20) → frontend image + 23 `PART=dev` (25 already run, `flags` present); admin `PART=owner`. Build: remaining extended touchpoints 1, 5, 16, 18 or touchpoint scenarios 12/17/19 in the ground truth (owner OK)

### 2026-11-15 · P6 / P8 · M7, M9 · Unusual-activity alerts for the monitoring officer (ADR-0036)
- **Status:** DONE locally (code, tests, browser run); BigQuery column `flags` is the owner's to add (script 25, before deploy)
- **Plan section:** §4, §10.4; CLAUDE.md §4.7, §4.10, §4.11, §4.13, §8
- **Files changed:** new `backend/app/tracking/signals.py`, new `backend/config/monitoring.yaml`, `backend/app/tracking/{query_log,monitor,usage}.py`, `backend/app/agents/{orchestrator,routes}.py`, `backend/app/audit/{log,pg_log}.py`, `backend/app/hitl/feedback.py` (ALERT, REVIEWED, ESCALATED, EXPECTED_ACTIVITY), `backend/app/config.py` (`monitoring_config_path`), `backend/app/main.py`, `data/schemas/bigquery/query_log.json` (`flags`), `infrastructure/gcp/25_query_log_columns.sh` (comment), new `backend/tests/unit/test_alerts.py`, `frontend/eoffice/src/{types.ts,api.ts,styles.css,components/MonitorPad.tsx,api.test.ts,tools.test.tsx}`, new `docs/decisions/0036-monitoring-alerts.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** `uv run pytest -q` → 1523 passed, 6 skipped ✅ · ruff, format, `mypy app` ✅ · `npx vitest run` → 42 passed ✅ · `tsc --noEmit`, `npm run build` ✅ · local browser run: 6 alerts from scripted activity, review clears one, flagged activity filter ✅
- **Acceptance evidence:** tests prove ordinary official phrasing raises no signal; hidden/unknown orders give the same code; burst vs spread refusals; words withheld above the monitor's clearance; review survives a rebuild; the asker's response has the same shape and no alert words; non-monitors get the same 404 on the pad and review routes, and the attempt becomes a `pad_probe` alert
- **Security / temporal / citation implications:** deterministic rules only, no model; no document text or IDs of refused records reach the pad; no automatic action on an officer
- **Known gaps / blockers:** thresholds, patterns and the monitoring policy are MOCK (department to decide, incl. staff notice and retention)
- **Exact next action:** owner: `APPLY=1 bash 25_query_log_columns.sh` again (adds `flags`) → image (13) → deploy c2-api (20) → frontend image + `PART=dev` (23); admin: `PART=owner IAP_MEMBERS=… 23_frontend_service.sh`

### 2026-11-15 · P8 · M9 · Fast cold start + frontend on Cloud Run behind IAP (ADR-0028 addendum 2, ADR-0032)
- **Status:** DONE locally (code, tests, local timing, whole-corpus equivalence); GCP steps are the owner's
- **Plan section:** §2.1, §3.5, §4.1 (detection unchanged), §11
- **Files changed:** `backend/app/ingestion/detect.py` (`pdf_scan`, `_has_image`, saved reads), `backend/app/ingestion/extract.py`, `backend/app/graph/build.py` (`--pdf-scans`), `backend/app/config.py` (`pdf_scan_cache_dir`, `sandbox_warm_start`), `backend/app/main.py` (lifespan warm start), new `backend/tests/unit/test_pdf_scan.py`, `backend/tests/unit/test_startup.py`, `infrastructure/gcp/14_graph_job.sh`, `20_api_service.sh`, new `23_frontend_service.sh`, `cloudbuild.frontend.yaml`, new `frontend/Dockerfile`, `frontend/server/server.py`, `frontend/server/test_server.py`, `docs/decisions/0028-…` (addendum 2), new `docs/decisions/0032-frontend-on-cloud-run-behind-iap.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** `uv run pytest -q` → 1497 passed, 6 skipped ✅ · `uv run pytest ../frontend/server` → 4 passed ✅ · ruff, format, mypy ✅ · local sandbox build (seed v2, recorded OCR): 113.7 s (py-spy) → 43.6 s → 2.4 s with saved reads; same indexed/held/texts ✅ · `_has_image` vs `page.images` over the whole public corpus (device, pypdf 6.21.4): 1,374 PDFs, 7,682 pages, 0 different ✅ · dry runs of 14, 20, 23 ✅ · frontend server run locally: page 200, client routes 200, API unreachable → neutral 502 ✅
- **Acceptance evidence:** as above; Cloud Run timing after the owner's deploy is still to be measured
- **Security / temporal / citation implications:** detection results unchanged (proved on the corpus); saved reads are used only when made by the same pypdf version and are keyed by the file's hash; c2-api gains read-only access to the artifacts bucket (derived text of public orders). c2-api stays IAM-only; c2-frontend is behind IAP and forwards only API paths with its own token
- **Known gaps / blockers:** IAP for accounts outside the organisation needs an External consent screen + OAuth client (console); IAP_MEMBERS is the owner's choice
- **Exact next action:** owner: image (13) → job with `--pdf-scans` (14; passages reused) → redeploy c2-api (20) and time the start → `IAP_MEMBERS=… APPLY=1 bash 23_frontend_service.sh` → open the c2-frontend URL. Build: touchpoints 12, 17, 19

### 2026-11-15 · P5 / P6 / P8 · M6, M7 · Officer approval of drafts and feedback capture (ADR-0031)
- **Status:** DONE locally (code, tests, browser run); BigQuery table/view are the owner's to create (script 22)
- **Plan section:** §9.1 checkpoint 2, §9.2, §10.4, §11.2; CLAUDE.md §2.4, §4.11, §8
- **Files changed:** new `backend/app/hitl/feedback.py` (`HumanAction`, `edit_share`, draft markers, `InMemoryActionLog`, `BigQueryActionLog`, `action_from_outcome`), `backend/app/connectors/eoffice.py` (`DraftOutcome`), `backend/app/eoffice_mock/models.py` (draft owner, `confirmed` / `discarded`), `backend/app/eoffice_mock/adapter.py` (`my_drafts`, `save_draft`, `confirm_yellow_note`, `discard_draft`), `backend/app/eoffice_mock/routes.py` (save / confirm / discard; file page shows only the officer's own drafts), `backend/app/agents/routes.py` (`/assist/feedback`), `backend/app/main.py` (action log wiring), `backend/app/config.py` (comment), new `data/schemas/bigquery/human_action.json`, new `infrastructure/gcp/22_human_action_table.sh`, new `backend/tests/unit/test_feedback.py` (11), frontend `types.ts`, `api.ts`, new `components/Feedback.tsx`, `components/ChatPanel.tsx`, `components/AssistPanel.tsx`, `components/FilePageView.tsx` (`DraftCard`), `styles.css`, `api.test.ts`, `render.test.tsx`, `docs/decisions/0031-officer-actions-and-feedback.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** `uv run pytest -q` → 1479 passed, 6 skipped ✅ · `ruff check .` ✅ · `ruff format --check .` ✅ · `mypy app` ✅ (94 files) · frontend `tsc --noEmit` ✅ · `vitest run` → 33 passed ✅ · `vite build` ✅ · Playwright against uvicorn + vite (U01, file 2894562): first-cut → Insert → Edit → Save (version 2) → Confirm → Note #2 Green under the SO's post, draft markers gone, edit kept, 0 drafts left; pre-send flag "Set aside" → recorded; no console errors · `22_human_action_table.sh` dry run ✅
- **Acceptance evidence:** another officer who opens the same file does not see the draft and gets the same 404 as for a non-existent draft on save / confirm / discard; a second confirm finds nothing; DFA drafts are not confirmed (409); feedback on someone else's session, a made-up session or a request not in the session → identical 404; statement feedback on a hidden record (D20 for U01) and an unknown ID → identical 404; flag feedback on an uncleared file and an unknown file → identical 404; free-text reasons and extra fields refused (422); recorded actions carry no word of the note text; the route table has no confirm path under `/assist` except OCR review, and no sign / send / dispatch / approve anywhere
- **Security / temporal / citation implications:** stricter than before — drafts are no longer shown to every officer who opens the file. Feedback stores IDs and codes only; a forged request ID can only add noise to evaluation data. Feedback changes no retrieval, rule, prompt or access
- **Known gaps / blockers:** confirmed notes are visible through the connector at once but not re-ingested as documents (`NOTE_CONFIRMED` events are not ingested); DFA approval chain not simulated; reason codes and "author's own until confirmed" are mock e-Office behaviour [To confirm]
- **Exact next action:** owner: `22_human_action_table.sh` (dry run, then `APPLY=1`); with the next allowed c2-api deploy set `C2_QUERY_LOG=bigquery`. Build: next plan block (extended touchpoints 12, 17, 19 or frontend on Cloud Run)

### 2026-11-14 · P3 / M3 · Cloud ladder check on BigQuery & Cloud SQL + Full Corpus Ingestion
- **Status:** DONE
- **Plan section:** §3.2, §3.5, §3.6, §4, §5.2, §5.7, §5.8; CLAUDE.md §2.2, §3, §4.2, §5.1
- **Files changed:** `evaluation/cloud_ladder_check.py` (fixed `classification.yaml` path), `infrastructure/gcp/14_graph_job.sh` (upgraded to `--cpu 2 --memory 8Gi`), `backend/app/graph/build.py` (added OCR draft cleanup & periodic `gc.collect()`), `evaluation/reports/2026-11-14-cloud-ladder-check.md` (new), `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:**
  - `APPLY=1 ./08_upload_public_corpus.sh`: synced 1,374 orders, manifests, OCR cache, and provenance to `gs://use-case-24-project-c2-raw/public-go/`
  - Cloud Run Job `c2-graph-build-4bkch` (2 vCPU, 8Gi RAM): ingested all 1,373 orders (0 OOM), wrote `nodes.jsonl` (1,290 nodes), `edges.jsonl` (1,669 edges), `held.jsonl` (83 held) to `gs://use-case-24-project-c2-artifacts/graph/`, loaded 1,290 nodes and 1,669 edges into Cloud SQL `c2-sql`
  - BigQuery: loaded `use-case-24-project.c2_metadata.documents` (1,290 rows) via `load_table` with user ADC (`venkat.c@techbharat.ai`)
  - `evaluation/cloud_ladder_check.py --sql-user venkat.c@techbharat.ai`:
    - L0 exact (BigQuery): 453 queries, 0 differences
    - L1 filter (BigQuery): 27 queries, 0 differences
    - L3 graph size (Cloud SQL): 1 check, 0 differences
    - L3 walk 2-hops (Cloud SQL): 120 walks, 0 differences
    - Result: **SAME on every question** across all 3 scopes (`evaluation/reports/2026-11-14-cloud-ladder-check.md`)
- **Acceptance evidence:** Real BigQuery and Cloud SQL rungs agree 100% with the reference implementation on every query; fixed SQL templates execute identically to in-memory/DuckDB logic; Cloud Run Job ingests the entire public corpus in 8Gi without memory termination.
- **Security / temporal / citation implications:** Scopes enforced within SQL queries and re-checked in code; outsider scope returns only UNCLASSIFIED documents; zero cross-scope data leakage observed. Cloud SQL IAM DB authentication used.
- **Known gaps / blockers:** Service account `c2-ingest` lacks `bigquery.jobs.create` (requires Project IAM Admin role grant); Rung L2 (hybrid search) pending embedding generation for passages table.
- **Exact next action:** Pre-send live evaluation on synthetic set v2 (`presend_v2.py --live`) or passage embedding generation for L2.


### 2026-11-15 · P5 / P6 / P7 · M6, M7, M8 · Conversation orchestrator, session memory, query log, injection suite (ADR-0029)
- **Status:** CODE DONE and tested locally; cloud parts (migration 0003, query-log table) are the owner's to apply
- **Plan section:** §3.4, §5.5, §8.1, §10.1, §10.2, §10.4, §10.6, §13.4
- **Files changed:** `backend/app/agents/orchestrator.py` (new), `backend/app/agents/state.py`, `backend/app/agents/answer.py` (`AskTrace`, recalled entities, status for "that order", notices), `backend/app/agents/routes.py` (`/assist/chat`, first-cut shared), `backend/app/memory/pg_session.py` (new), `backend/app/tracking/query_log.py` (new), `backend/app/retrieval/evidence.py` + `backend/app/citation/verifier.py` (`addressed_to_ai`), `backend/app/main.py`, `backend/app/config.py`, `data/schemas/postgres/0003_sessions.sql`, `data/schemas/bigquery/query_log.json` (new), `infrastructure/gcp/12_cloudsql_schema.py` (grants), `infrastructure/gcp/21_query_log_table.sh` (new), `evaluation/leakage_v2.py` (conversation paths), tests `test_orchestrator.py`, `test_pg_session.py`, `test_prompt_injection.py` (new), `test_pg_state.py`, `.env.example`
- **Tests/commands run:** `pytest -q` → 1466 passed, 6 skipped; frontend `tsc` + `vitest` 30 passed; real Postgres 16 for the session / graph / state tests; `ruff`, `mypy` clean; v1 harness unchanged (0 / 1,142, recall@10 0.754, MRR 0.833, A/C/E/F 1.000); `ask_golden.py` re-score unchanged (16/19, 15 on key, 0 removed, 0 forbidden); injection pattern false positives: 0 in 1,374 public orders + 544 synthetic texts; `leakage_v2.py --label m6` with the conversation paths (chat, follow-up + draft) → 0 disclosures / 64,008 checks, controls 833
- **Acceptance evidence:** follow-up resolves "that order" from turn 1; another officer's session ID gives a fresh session; after access is narrowed mid-session the remembered file paper is neither recalled nor sent to the model; same question twice → cache hit for the same officer, miss for a different scope; query log holds no question words; draft-the-noting returns first-cut points with the conversation's precedents and nothing outside access; with an obedient model none of 4 planted instructions produces a shown statement for any of 8 officers
- **Security / temporal / citation implications:** scope recomputed every turn; memory IDs re-checked; cache scoped; question text never logged; instruction-bearing passages cannot be cited
- **Blocker / decision needed:** none (cloud: apply migration 0003 with `12_cloudsql_schema.py`; `21_query_log_table.sh`)
- **Exact next action:** owner applies 0003 + query-log table when convenient; `noting_live.py --live` (≤4 calls); next build: frontend chat panel
- **Frontend:** `frontend/eoffice/src/components/ChatPanel.tsx` (new), `api.ts`, `types.ts`, `FilePageView.tsx`, `render.test.tsx`
- **Also built in this task (ADR-0030):** `backend/app/noting/drafter.py`, `backend/prompts/noting_draft.v1.md`, `evaluation/noting_live.py`, `tests/unit/test_noting_drafter.py` — a scripted model's 9 lines: 3 kept, 6 removed for the six reasons above

### 2026-11-15 · P3 / P6 · M4 · Citation check refined, status from the order records (ADR-0024 addendum 2)
- **Status:** CODE DONE; one live call (Q05) and a confirming live run are the owner's
- **Plan section:** §6.1-§6.2, §7.2, §8.2-§8.3; CLAUDE.md §7.7, §9.5
- **Files changed:** `backend/app/citation/verifier.py` (record's own numbers / dates; hyphen spacing), `backend/app/retrieval/evidence.py` (`issue_date` on candidates and items; not in the prompt), `backend/app/agents/answer.py` (`named_orders` via L0 exact, `status_statements`, model-off path keeps record statements), tests in `test_cited_answer.py`, `test_evidence_and_citations.py`
- **Tests/commands run:** `pytest -q` → 1447 passed, 5 skipped; `ruff`, `mypy` clean; v1 harness unchanged (0 / 1,142, recall@10 0.754, MRR 0.833, A/C/E/F 1.000); `ask_golden.py` re-scored on saved answers → 16/19 answered, 15 on key, 0 removed, 0 forbidden; `leakage_v2.py --label m4b` → 0 disclosures / 55,482 checks, controls 833
- **Acceptance evidence:** the cited record's own number and date pass while another order's number is rejected; a date broken across a line matches; status facts given only for orders the officer may see (8 officers checked against the independent matrix) and only under the coverage rule
- **Security / temporal / citation implications:** status facts come from the temporal engine, not the model; the verifier still requires the verbatim quote; prompts unchanged so saved answers replay
- **Blocker / decision needed:** none
- **Exact next action:** owner: `ask_golden.py --live --label v3` (sends only Q05; the others replay)

### 2026-11-15 · P3 / P6 · M4, M8 · Cited-answer quality, neutral failure, cloud passages for evidence
- **Status:** CODE DONE; live run 2 is the owner's (billed)
- **Plan section:** §3.2, §6.2, §8.1-§8.3; CLAUDE.md §4.4, §7
- **Files changed:** `backend/app/agents/answer.py` (named records, as-of, passages, aliases), `backend/prompts/answer_cited.v2.md` (new), `backend/app/agents/routes.py` (`/ask` named records + cloud texts; `/reference` via the composite index), `backend/app/agents/runtime.py` (`evidence_texts`), `backend/app/main.py` (neutral 503 handler), `backend/app/retrieval/bigquery_l2.py` (`BigQueryPassageText`, `join_passages`), `backend/app/retrieval/cloud.py`, `evaluation/ask_golden.py` (simulated reviewer, package recall), tests in `test_cited_answer.py`, `test_composite_rungs.py`, `test_bigquery_l2.py`; ADR-0024 / ADR-0028 addenda
- **Tests/commands run:** `pytest -q` → 1442 passed, 5 skipped; `ruff`, `mypy` clean; v1 harness unchanged (0 / 1,142, recall@10 0.754, MRR 0.833, A/C/E/F 1.000); `ask_golden.py` without model: expected record in the evidence package 18/19 (was 13/19); `leakage_v2.py --label m4` → 0 disclosures / 55,482 checks, controls 833 (answer path with named records included)
- **Acceptance evidence:** a named order reaches the prompt although its words differ; an e-File's papers reach the prompt only for officers the independent matrix allows; same evidence → identical prompt; a refusing cloud store → 503 neutral, no store or rule named; a cloud-only order's text reaches the prompt only for officers whose scope admits it and is not even read otherwise
- **Security / temporal / citation implications:** all named-record lookups are L0/L3 within scope with re-check; neutral failure; citation verifier unchanged
- **Blocker / decision needed:** project roles bigquery.jobUser + aiplatform.user for c2-api / c2-ingest (owner's admin)
- **Exact next action:** owner: `ask_golden.py --live --label v2`; after the roles: graph job with `EMBEDDING_MODEL=gemini-embedding-001`, redeploy `c2-api` with the same, `cloud_ladder_check.py`

### 2026-11-15 · P3 / P8 · M3, M8 · Sandbox API reads the cloud rungs; Cloud Run service scripts (ADR-0028)
- **Status:** CODE DONE and tested locally; deployment is the owner's (scripts 18-20 not yet run)
- **Plan section:** §3.2, §3.5, §11; CLAUDE.md §2.1, §3, §4.2
- **Files changed:** `backend/app/retrieval/composite.py`, `backend/app/retrieval/cloud.py` (new), `backend/app/graph/repository.py` (`WalkableGraph`), `backend/app/retrieval/{ladder,graph_expansion}.py`, `backend/app/agents/{tools,runtime}.py`, `backend/app/main.py`, `backend/app/config.py` (`retrieval_backend`, `bq_dataset`, `l2_cloud_min_score`), `backend/tests/unit/test_composite_rungs.py` (new), `infrastructure/gcp/18_service_access.sh`, `19_upload_synthetic.sh`, `20_api_service.sh` (new); reconciled the other session's edits (`build.py` gc / `ocr_drafts` release, job 2 vCPU / 8 GiB, `cloud_ladder_check.py` path fix)
- **Tests/commands run:** `pytest -q` → 1435 passed, 5 skipped; `ruff check`, `mypy app` clean
- **Acceptance evidence:** composite graph = single graph on 6 random graphs × 75 scoped walks; cross-store walk stops at a closed node; composite L0/L1 = single index; sandbox `/assist/search` reaches a cloud-only order for all 8 officers and a confidential cloud-only order for exactly the cleared ones
- **Security / temporal / citation implications:** each store applies the scope; the merge cannot widen; synthetic answer keys are never uploaded where the service could read them; service not public
- **Not yet proven:** nothing deployed; cloud-only orders cannot yet be quoted in a cited answer (passage text from BigQuery is the next step); L2 ranking unmeasured
- **Blocker / decision needed:** project-level roles for c2-ingest / c2-api (bigquery.jobUser, aiplatform.user; c2-api Cloud SQL roles) — project owner (`18_service_access.sh`, lines under OWNER)
- **Exact next action:** owner runs 18 → 19 → 13 → 20, then the proxy check; then L2 passages (embedding check → job with EMBEDDING_MODEL); then evidence text from BigQuery passages

### 2026-11-14 · P3 / M2, M3 · BigQuery rungs L0/L1, first whole-corpus run on GCP, memory fix (ADR-0025)
- **Status:** CODE DONE and tested locally; cloud runs are the owner's
- **Plan section:** §3.2, §3.6, §4, §5.2; CLAUDE.md §2.2, §3, §4.2, §5.1
- **Files changed:** `backend/app/retrieval/bigquery_index.py` (new), `backend/tests/unit/test_bigquery_index.py` (new), `backend/app/graph/build.py` (`--load-bigquery`; each store loaded on its own), `backend/app/ingestion/ocr.py` (`RecordedOcrFiles`), `backend/app/main.py`, `backend/app/ingestion/detect.py`, `backend/pyproject.toml` + `uv.lock` (dev: duckdb), `infrastructure/gcp/14_graph_job.sh`, `evaluation/cloud_ladder_check.py` (new), `data_collection/tools/ocr_corpus.py` (`--ids-file`, `--cache-only`; edited on the Mac), `docs/decisions/0025-…`
- **Tests/commands run:** `pytest -q` → 1415 passed, 5 skipped; `ruff check`, `mypy app` clean; `leakage_v2.py --jobs 2` → 0 disclosures / 55,482 checks, controls 833; owner's job runs: 50-order trial ok (28 indexed), whole corpus 1,373 → 870 indexed / 503 held / 831 relations
- **Acceptance evidence:** BigQuery templates = in-memory reference on 4 random corpora × 5 scopes (60 filters and ~250 exact lookups each), executed on DuckDB; a hostile filter value never reaches the SQL text; scan of the corpus on the owner's machine explains the 435 "no recorded OCR": 427 files have text on every page plus an image, 9 have image-only pages, none has a reading
- **Security / temporal / citation implications:** scope pushed into the SQL and re-checked in code; unknown classification is outside every scope; held orders are not indexed (fail closed); table replace is atomic
- **Not yet proven:** nothing here has run against real BigQuery; the 3 `InvalidCanonicalIdError` orders are not traced; L2 has no in-region store
- **Blocker / decision needed:** none (L2 location decided the same day: BigQuery in region, ADR-0026; built: `backend/app/retrieval/bigquery_l2.py`, `tests/unit/test_bigquery_l2.py`, `infrastructure/gcp/17_embedding_check.py`; suite 1422 passed, 5 skipped)
- **Exact next action:** owner: `ocr_corpus.py --ids-file … --cache-only` (dry run, then `--apply`), `join_ocr_cache.py --all`, `08_upload_public_corpus.sh`, `13`, `14`, `cloud_ladder_check.py`

### 2026-11-14 · P3-P5 / M3, M4 · First cited answer (ADR-0024) and the v2 outsider leakage suite
- **Status:** CODE DONE; live Gemini run is the owner's (billed)
- **Plan section:** §3.3, §5.2, §5.5, §8.1–§8.3, §9.4, §12.4; CLAUDE.md §4, §7, §9.4
- **Files changed:** `backend/app/agents/answer.py` (new), `backend/prompts/answer_cited.v1.md` (new), `backend/app/agents/routes.py` (`POST /assist/ask`), `backend/tests/unit/test_cited_answer.py` (new), `evaluation/ask_golden.py` (new), `evaluation/leakage_v2.py` (new), `backend/app/graph/build.py` (one failing order is held, the run continues), `infrastructure/gcp/15_graph_job_access.sh` (new), `docs/decisions/0024-first-cited-answer.md`
- **Tests/commands run:** `pytest -q` → 1405 passed, 5 skipped (real-Postgres tests skipped in this run); `ruff check`, `mypy app` clean; `leakage_v2.py --users V01` → 0 disclosures / 2,642 checks. The first full 21-officer run was killed at 3 GB per process. Cause found and fixed the same day: the sandbox loaded every recorded OCR response into memory at start (not a per-request leak); `RecordedOcrFiles` reads them one at a time (peak 0.9 GB). Suite after the fix: 1405 passed, 5 skipped
- **Acceptance evidence:** with a scripted model that answers from the prompt it receives: a quoted, cited statement is confirmed; an invented evidence id, an invented quote and a statement with no citation are each removed (no-answer returned); no evidence → the model is not called; model off / failing → `not_run` with the authorised records. Sweep: 24 golden questions × every v1 officer, every record named in the PROMPT and in the RESPONSE checked against the access matrix → 0
- **Security / temporal / citation implications:** the model never filters and never has the last word on a citation; superseded status travels with each passage; audit holds ids and outcome only
- **Not yet proven:** answer quality with Gemini (no live run yet); meaning of a statement vs its quote is not machine-checked (ADR-0024 limits)
- **Blocker / decision needed:** none
- **Exact next action:** owner: `APPLY=1 ./15_graph_job_access.sh`, `APPLY=1 LIMIT=50 RUN=1 ./14_graph_job.sh`; `ask_golden.py --live`

### 2026-11-14 · P1-P3 / M1, M2 · Knowledge graph of the public corpus, built on GCP into Cloud SQL (ADR-0023)
- **Status:** CODE DONE and tested locally; the three GCP steps are the owner's to run (billed, owner's login)
- **Plan section:** §3.5, §3.6, §4, §5.2; CLAUDE.md §2.1, §4.2
- **Files changed:** `backend/app/graph/build.py` (new), `backend/app/graph/postgres.py` (new), `backend/app/graph/repository.py` (`edges()`), `backend/app/ingestion/metadata.py` ("in supersession of … read above" with one Read entry), `data/schemas/postgres/0002_graph.sql` (new), `infrastructure/gcp/12_cloudsql_schema.py` (grants), `infrastructure/gcp/13_backend_image.sh`, `14_graph_job.sh`, `cloudbuild.backend.yaml` (new), `backend/tests/unit/test_graph_build.py`, `test_graph_postgres.py` (new), `test_pg_state.py` (migration list), `docs/decisions/0023-graph-in-cloud-sql-first.md`
- **Tests/commands run:**
  - `pytest -q` with a local Postgres 16 (`C2_TEST_PG_DSN`) → 1400 passed, 0 skipped; `ruff check`, `mypy app` clean
  - contract test: Postgres walk = in-memory walk on 8 random graphs (3 departments, 3 classifications, file papers), 36 scoped walks each; every node on every returned path is inside the scope
  - `python -m app.graph.build --staging-dir <120 cited orders> --load-postgres` on Postgres 16 → 114 nodes, 6 held, 176 edges (REFERENCES 98; AMENDS 37 stated + 5 candidate; SUPERSEDES 8 stated + 28 candidate); run from a copy laid out like the image → works
- **Acceptance evidence:** the same pipeline that serves the sandbox builds the graph; files are written before the database is touched; a second load changes nothing
- **Security / temporal / citation implications:** public orders only; scope is applied to every node of a walk in one place (no second copy of the access rule in SQL); `c2-api` read-only, `c2-ingest` no DELETE; candidate links stay unconfirmed; no keys, no passwords, no model calls
- **Not yet proven:** the Cloud Build and Cloud Run Job scripts have not run (no GCP login here): flags are written from the gcloud reference and may need a correction on first run. Whole-corpus numbers (1,374 orders) do not exist yet
- **Blocker / decision needed:** none
- **Exact next action:** owner runs `APPLY=1 … 12_cloudsql_schema.py`, `APPLY=1 13_backend_image.sh`, `APPLY=1 LIMIT=50 RUN=1 14_graph_job.sh`, then without LIMIT; paste `report.md`

### 2026-11-14 · Data workstream / M2 · Post-OCR corpus metadata reconciliation and audit (1,374 orders + 1 demo holdback)
- **Status:** DONE
- **Plan section:** §4.4, §5.1, §5.7, §12.1; CLAUDE.md §5, §12
- **Files changed:** `staging/manifests/relations.jsonl`, `staging/manifests/missing.txt`, `staging/manifests/audit_report.json`, `staging/manifests/date_review.csv`, `meta.json` files in `staging/rule-library/`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:**
  - `data_collection/.venv/bin/python tools/extract_relations.py staging` -> 4,258 candidate edges from 1,374 documents (REFERENCES: 4,078, SUPERSEDES: 38, AMENDS: 138, REPEALS: 4); 1,921 cited items not yet in corpus -> `missing.txt`
  - `data_collection/.venv/bin/python tools/audit_corpus.py` -> 1,374 orders audited, no problems (1,913 resolved in corpus, 696 not collected, 1,649 unresolved raw kept, 1,372 status unknown to derive at ingestion)
  - `data_collection/.venv/bin/python tools/reconcile_dates.py --write` -> 1,073 printed = archive, 290 unreadable (archive kept), 11 already verified, 0 mismatches; `date_review.csv` written
  - Dry run `infrastructure/gcp/08_upload_public_corpus.sh` -> verified 1,374 staging orders, 1 holdback demo order excluded (GAD 139/2025), 0 `_review` objects; 1,375 total corpus files
  - `backend/.venv/bin/pytest -q` -> 1,376 passed, 4 skipped in 45.15s
- **Acceptance evidence:** metadata on disk reflects the post-OCR corpus; 1,374 staging orders + 1 demo order in `holdback/` accounted for; relations manifest, date reconciliation and audit reports generated clean
- **Security / temporal / citation implications:** public orders only (UNCLASSIFIED); demo holdback order preserved in `holdback/` so open-file notification demo replay is safe; no unverified dates guessed
- **Blocker / decision needed:** none
- **Exact next action:** upload corpus updates to GCS (`APPLY=1 infrastructure/gcp/08_upload_public_corpus.sh`), then continue evaluation/presend_v2 live run

### 2026-11-13 · Data workstream / M2 · Public corpus uploaded; synthetic set v2 planned (ADR-0020)
- **Upload (owner, 11:09 IST):** `gs://use-case-24-project-c2-raw/public-go/` holds 1,375 order.pdf / ocr.txt / meta.json, 300 OCR-cache responses, relations.jsonl and provenance.jsonl. Byte check: FIN 84/2024 md5 matches the Mac copy (`Ikic8OtabzpPcPuuhDpLCQ==`)
  - **problem:** the 8 `_review/…/meta.partial.json` files were uploaded too: the `^_review/` exclude did not match in `gcloud storage rsync`. The script now excludes `_review/` and `holdback/` anywhere in the path, and `meta.partial.json` by name (local preview: 8 left out). Owner to delete the 8 objects (command given; bucket versioning keeps a noncurrent copy)
- **Synthetic set v2 (owner request 11:15 IST → ADR-0020):** 200 files, 3 departments, all touchpoints / conflict types, official layouts. Owner answers: 200 files; keep mock_v1 and use the same folder (→ `data/synthetic/mock_v1/efiles_v2/`); public layout references; 6 officers per department
  - grounding available (both ends held): SUPERSEDES FIN 11 / GAD 7 / ESE 3; AMENDS FIN 29 / GAD 18 / ESE 35; gazette Rules GAD 56 / ESE 30 / FIN 7 / Law 16. Main FIN topics: pension, budget, allowances/DA, contract/outsourcing, transfers; GAD: recruitment, service rules, transfers, reservation; ESE: teachers, recruitment, transfers, service rules
  - relations are `candidate` (some evidence quotes point at a different order), so every edge a scenario relies on is verified against the order text before use
  - public layout references: NIC e-Office FAQ and manuals (Green / Yellow notes, receipt numbering `2345/2015-Admin`, DFA versions 1.0/1.1, movement remarks, Link File, close / reopen)
- **8 `_review` objects deleted from the bucket (owner, 11:34 IST)**
- **Officers (owner: "use the official hierarchy"):** `data/synthetic/mock_v1/efiles_v2/directory/officers.yaml`:
  - **21 synthetic officers, 7 per department:** ASO and SO of section A; SO of section B; SO of a restricted section C; Assistant Secretary; Joint Secretary; department head. That is one more than the earlier 6, so the real chain includes the Assistant Secretary;
  - **public sources:** the A.P. Secretariat Office Manual ch.1 (post ladder and file flow ASO → SO → AS → DS/JS/Addl.S → Secretary; "SO heads a section"); MCR HRD "Structure of Government";
  - **sections and head designations come from our real G.O.s** (section-field counts, signature blocks): FIN PC-TA / HR-III Pension & GPF / Budget-I (restricted); GAD Ser.A / Cabinet.II / SC.F (restricted); ESE Services.II / Prog.II / Exams (restricted);
  - **names are invented, never real officials.** Restricted sections, clearances and scopes are mock `[To confirm]`
- **Grounding inside these sections** (2016–2025 orders, both ends held):
  - orders: FIN PC-TA 49 / HR-III 52 / Budget-I 57; GAD Ser.A 42 / Cabinet.II 73 / SC.F 8; ESE Services.II 31 / Prog.II 62 / Exams 30;
  - explicit SUPERSEDES / AMENDS / REPEALS: FIN 8, GAD 14, ESE 23, plus the 45 DA/DR rate series and the gazette rule amendments. 200 files need several dated variants per chain (before / after a change, conflict / clean), plus types D (precedent between synthetic files), E (cited order not held) and C (labelled synthetic memos)
- **Owner OK: 7 officers per department (11:38 IST)**
- **Stage 1 done:** `data_collection/tools/mine_scenarios_v2.py` writes `efiles_v2/scenarios/candidates.csv` (all edges with verdict and quote) and `chains.yaml` (verified chains, rate series, unresolved citations):
  - 114 candidate SUPERSEDES / AMENDS / REPEALS edges; **103 verified** (the newer order names the older order's number near the verb, with the year or a "read above" reference); 11 unverified (number not near the verb, or supersession only "of the orders read above"), never used for planted conflicts;
  - with the newer order dated 2016–2025: FIN 27 AMENDS + 6 SUPERSEDES; GAD 16 + 5; ESE 40 AMENDS + 1 SUPERSEDES + 2 REPEALS. Rate series: DA 21, DR 19, HRA 18 orders. Unresolved citations from our sections: FIN 31, GAD 20, ESE 14;
  - **caveat:** the check is a heuristic. A spot check of 7 verified edges showed all 7 right, but many rest on "Amendment" in the abstract plus the number in the Read-list. Each planted conflict is read by hand when its scenario is written
- **Proposed spread per department (~67):** A superseded ≈8, F temporal / rate ≈11–15, B contradiction 2 (hand-picked pairs only), C wrong authority 4 (A.P. Business Rules 2018 + labelled synthetic memos), D precedent 4, E unresolvable 5, G hierarchy 4 (gazette Rules vs G.O.), clean ≈22. All 20 touchpoints are spread over these files
- **Sections re-picked (13 Nov):** stage 1 showed the verified chains sit in other sections than first chosen. FIN section A PC-TA → **HR-I (Plg. & Policy)**; ESE section B PROGRAM-II → **PROGRAM-I**. `officers.yaml` and the miner's section patterns were updated. A chain from a section we do not staff is skipped, never moved into another section; DA (PC-TA) rate pairs are dropped, DR (HR-III) kept
- **Stage 2 (builder) done:** `data_collection/tools/build_scenarios_v2.py` writes `efiles_v2/scenarios/scenarios.yaml`, deterministic (seed 20261113):
  - **171 files, 57 per department:** FIN A 8 / F 22 / E 5 / D 4 / clean 18; GAD A 8 / F 15 / E 8 / D 8 / clean 18; ESE A 4 / F 26 / E 5 / D 4 / clean 18. 31.6% clean (some "before the change", some citing the current order);
  - **sections:** FIN HR-I 26 / HR-III 15 / Budget-I 16; GAD Ser.A 25 / Cabinet.II 17 / SC.F 15; ESE Services.II 14 / Prog.I 20 / Exams 23;
  - **all 20 touchpoints** in every department; 18 (migrated) and 19 (reassignment) only 2 per department, to be raised when rendering;
  - **movement** follows the real chain (ASO → SO → AS → JS → head; a restricted section goes SO → JS → head);
  - every A / F conflict carries the quote from the governing order and is dated after it; DR conflicts carry both rates quoted ("from X% … to Y%")
- **B / C / G hand-picked (13 Nov, read against the orders):** `efiles_v2/scenarios/handpicked_bcg.yaml`, 30 entries. The builder copies each quote from the real order and refuses an entry whose anchor does not match; all 30 matched. Grounding:
  - **ESE:**
    - Teachers (Regulation of Transfers) Rules 2017 (G.O.Ms.32: two-year minimum, eight-year compulsory);
    - Teachers' Transfer Rules 2025 (G.O.Ms.22: eight / five years; orders only with the Committee's approval; Committee is the competent authority for HM Gr.II in ZP High Schools);
    - 2020 Guidelines (G.O.Ms.54: half a year counts as a full year);
  - **GAD:**
    - State & Subordinate Service Rules Rule 12 N.B. (G.O.Ms.95/2021: SC/ST age concession in force up to 31.5.2026);
    - Business Rules First Schedule (G.O.Ms.74/2017 Deputy Collector transfers allotted to GAD; G.O.Ms.99/2017 Rajiv Swagruha / Housing Board moved to MA&UD; G.O.Ms.32/2017 tourism / heritage corporate bodies);
    - ACB Service Rules (G.O.Ms.34/2020);
  - **FIN:**
    - pension qualifying service (Gazette 05-01-2024: contract service not counted);
    - APGLI Fund Rules 2024 (enhancement once a year; medical examination above 8%);
    - G.O.Ms.110/2016 (Finance permission for 10,000 vacancies);
    - G.O.Ms.51/2016 (no re-appropriation in the first two quarters; spending pending CBRO)
  - G and B use **labelled synthetic** circulars / memos / proceedings as the lower or same-level instrument; no G.O. is invented
- **Plan complete: 201 files**:
  - **ESE 67:** A 4, B 3, C 3, D 4, E 5, F 26, G 4, clean 18;
  - **FIN 67:** A 8, B 3, C 4, D 4, E 5, F 22, G 3, clean 18;
  - **GAD 67:** A 8, B 2, C 5, D 8, E 8, F 15, G 3, clean 18;
  - clean 27%; every touchpoint at least 3 times per department
- **Stage 3 renderer built:** `data_collection/tools/render_efiles_v2.py`. Per file:
  - `file.json`;
  - `Correspondence/R-001.md` receipt with diary fields (Receipt No. `NNNN/YYYY-SEC`, diary date, delivery mode, type, language, sender, letter ref., main category, subject);
  - `R-002/3.md` labelled SYNTHETIC lower instruments;
  - `Note File1/note-NNN.md`: Green notes in movement order, signed time / NAME / DESIGNATION; a pending file ends with a Yellow note;
  - `Drafts/DFA-001.md` in the real G.O. layout (v1.0, unsigned);
  - `GO/link.json`, `movements.json`, `links.json` (Previous Reference for D)

  Also writes `directory/officers.json`, `access_matrix.csv` (scope + clearance, mock), `ground_truth/efiles_v2_conflicts.json` (eval only) and `manifests/efiles_v2_index.json`
  - **sample:** 9 files (3 per department: one hand-picked, one A/F, one clean) in `efiles_v2/_sample/`; preview `_sample_preview.md` sent to the owner
  - **fixes from reading the sample:**
    - section names printed as in G.O.s (Services.II, Budget.I, Ser.A, SC.F);
    - a G.O. abstract tail ("– Orders – Issued.", "Amendment") is stripped from the receipt subject;
    - C cases carry an explicit `proposal` (handpicked YAML, 12 entries);
    - "in respect of <person>" only for personal matters;
    - the renderer never deletes (connected folders forbid deletion; it overwrites)
- **Owner OK on the layout (12:21 IST) → all 201 rendered** into `data/synthetic/mock_v1/efiles_v2/efiles/` (7.4 MB): 147 planted conflicts + 54 clean; `access_matrix.csv`, `directory/officers.json`, `ground_truth/efiles_v2_conflicts.json` (eval only), `manifests/efiles_v2_index.json`
- **Checks:** `data_collection/tools/check_efiles_v2.py` (read-only, exit 1 on any problem) checks:
  - folder completeness; SYNTHETIC banner on every Markdown file; lower instruments labelled;
  - every cited order held (type E: must NOT be held); every G.O. citation in note 1 parses back to its canonical ID (`parse_reference`);
  - dates 2016..31-12-2025, receipt before note; A / F governing order dated on or before the note; "clean before" dated before the newer order;
  - unique file numbers; ground truth ↔ files ↔ plan; movement officers in the department and ALLOWED by the access matrix;
  - restricted sections CONFIDENTIAL; no ground truth under backend/

  **Result: 201 files, 147 conflicts, 0 problems.** One check bug fixed on the way: two cited G.O.s with the same number in different years; the pattern now includes the year
- **Mentor noting samples (owner, 13 Nov) → note layout updated.** Used for the layout only; nothing from them is copied or stored. Each note sheet now has:
  - "Sub:" and a numbered "Ref:" list ("G.O.Ms.No.X, … Department, dated dd.mm.yyyy.", receipt last), then "* * *";
  - paragraph numbers that run on through the file (dealing hand "N)", officers "N.");
  - "Approval Requested a) b)" and "Submitted for orders."; "Sir, submitted for approval of Para N …";
  - blank forward notes; "Pl discuss." then a resubmission (24 files); "Para N - agreed." / "Approved." / "Approved. Issue orders";
  - signature dd/mm/yyyy hh:mm AM/PM, NAME (", I.A.S" for rank ≥ 5), DESIGNATION; file no. without brackets; pending files end with a Yellow note (56)
- **Old generated folders deleted (owner OK, delete permission for the project folder):** `efiles_v2/{efiles,_sample,_sample_directory,_sample_ground_truth,_sample_manifests,_sample_access_matrix.csv}`. Generated output only; no code. `_sample_preview.md` kept
- **Renderer fixes:** chain length `randint` empty range; note times now only move forward (20 min–5 h per movement, office hours, no Sundays); a leading "Rules -" is stripped from receipt subjects
- **Re-render + checks:** `render_efiles_v2.py` → 201 files, 147 planted conflicts; `check_efiles_v2.py` → **0 problems**
- **Inter-department U.O. notes (owner OK 12:47 IST):**
  - Finance concurrence: a GAD01 / ESE01 file whose matter has a financial implication goes to Finance for concurrence. These are matters that create or fill posts: a new department, direct recruitment to various posts, recruitment tests, school up-gradation, allowances, sanctions, schemes. Restricted sections and pending files are left out
  - the note flow for these files:
    - the head writes "Para N - agreed. Concurrence of Finance Department may be obtained.";
    - Finance's synthetic U.O. note is placed in Correspondence. It comes from Finance (FMU-GAD-I / FMU-SE-I), is signed by designation only, and concurs or concurs subject to a condition;
    - the dealing hand records the U.O. No. and date, the file goes up again, and the head writes "Approved. Issue orders.";
    - `movements.json` gets an `external: true` entry for the Finance round trip (3–10 days); `file.json` gets `finance_concurrence`
  - Finance officers are not given access to the administrative department's file; Finance's part is the U.O. note only. FMU section codes and the U.O. number shape are mock [To confirm]
  - BUDGET-I receipts now arrive as a U.O. Note from an administrative department (19 files)
  - receipt senders now come from a list per section (an ACB letter on APPSC recruitment read wrong)
  - `check_efiles_v2.py` group 10: note times only move forward; each concurrence is in Correspondence, labelled SYNTHETIC, recorded in a note, on a non-Finance, non-restricted file, with dates in order
  - **Result: 201 files, 147 planted conflicts, 10 Finance concurrences, 19 U.O. receipts, 0 problems**
- **Consultations across all three departments (owner OK 12:59 IST):**
  - three kinds, in the order a file goes out:
    - Finance concurrence (FMU) on cost and posts, for GAD01 / ESE01 files;
    - General Administration (Ser.A) views on service and recruitment rules, Public Service Commission matters and age relaxation, for FIN01 / ESE01 files. The reply is no objection, or agreement subject to Law vetting or Gazette notification;
    - the Council of Ministers through General Administration (Cabinet.II), for FIN01 / ESE01 policy matters (Revised Pay Scales, NPS, district restructuring). The reply records the meeting date (never a Sunday) and the item number
  - how a consultation appears in the file:
    - the head orders them all in one note;
    - each goes out by U.O. note and the reply is in Correspondence (signed by designation only);
    - the dealing hand records each reply, then the head approves;
    - `file.json` has `consultations` (replacing `finance_concurrence`), and `movements.json` has one `external: true` entry per round trip
  - a department never consults itself; restricted sections and pending files are left out. GAD's U.O. numbers use 500+ so they cannot clash with synthetic GAD file numbers. Practice and codes are [To confirm]
  - `check_efiles_v2.py` group 10 now covers all three kinds and also checks that they do not overlap
  - **Result: 201 files, 147 planted conflicts, consultations FIN 8 / GAD Ser.A 12 / Cabinet 8, 19 U.O. receipts, 0 problems**
- **Sandbox loading of v2 (owner "next", 13:02 IST) — ADR-0020 addendum:**
  - `data/synthetic/tools/build_eoffice_seed_v2.py [--check]` → `efiles_v2/eoffice/seed_v2.json`: 25 profiles (21 with a login + 4 consulted offices as staff posts), 201 files, 831 notes, 686 movements, 255 pages, 201 receipts. It also writes 504 documents for ingestion (255 correspondence pages, 201 note sheets, 48 Yellow drafts) and `documents_index.csv`. No scenario key or conflict data in the seed (test)
  - `data_collection/tools/index_public_cited.py` → `efiles_v2/eoffice/public_index.csv`: 83 cited real orders held (55 MB, SHA-256 each; the 18 type E references are not held, so not listed)
  - backend:
    - `C2_SANDBOX_SEED=v1|v2|both` (default v1) and `C2_SANDBOX_PUBLIC_CORPUS_DIR` (required for v2/both);
    - `merge_seeds` refuses clashing identifiers;
    - `artefacts_from_index` checks the hash and refuses paths outside the root;
    - `.env.example` lists both settings
  - renderer: a pending file's Yellow note now restates the reference it rests on, so the pre-send check has something to check
  - heads moved from Global to Department scope (`officers.yaml`). The app never opens another department's non-public papers, so the access matrix had them ALLOWED where the app would deny
  - **Tests:** new `test_eoffice_seed_v2.py`, 10 tests:
    - generator up to date; no answer keys; every actor a profile;
    - note and movement times run forward;
    - app reach never exceeds the access matrix (0 differences either way);
    - v1+v2 merge works and clashes are refused;
    - hash / root checks; v2 needs the public dir.

    Full suite: **1298 passed, 4 skipped**; ruff, ruff format, mypy (79 files) clean. Run in the cloud copy with identical files (md5 match); the Mac backend venv points at an interpreter the VM does not have
  - **Smoke run (v2, with the 83 public orders):** startup 0.2 s; the first assist call ingests everything in ~70 s. File lists: SO GAD Ser.A 30 files, JS/head 67 (own department only); `both` adds the v1 files
  - **First pre-send baseline on the 147 planted conflicts.** This was a smoke check, not the evaluation suite: E 13/18, A 2/20, F 1/63, B/C/D/G 0. Why it is low:
    - 42 of the 83 public orders are scans and wait for OCR (provider none), so their supersession links never reach the graph (5 relations in total);
    - all 255 correspondence pages go to the review queue (letters without an own reference).

    B/C/G rest on the synthetic lower instruments, which are in that queue, and D needs the precedent links
- **Known gaps:** one section per profile (an Assistant Secretary reaches a second section only through files they handled; today that is all of them); DFA drafts are not in the seed (the Seed schema has no drafts list)
- **Recorded OCR for v2 (owner OK 13:26 IST):**
  - `data_collection/tools/join_ocr_cache.py` joins the 15-page chunk responses into whole-file `<sha256>.json` (text end to end, anchors shifted; page numbers already absolute; a file with a page gap is skipped, never patched) → data root `staging/ocr_recorded/documentai/<version>/`. 17 cited orders joined (15 MB); no new Document AI calls
  - backend `sandbox_ocr`: for v2/both it also replays that folder (v1 keeps its own recorded scans); new test → `test_eoffice_seed_v2.py` 11 tests; full suite **1299 passed, 4 skipped**; ruff, mypy clean; Mac md5 verified
  - `ocr_corpus.py --force` (only with `--id`): read named files even when their text layer looks readable
  - **Where the 42 held public orders stand:**
    - 17 are now read from the recorded OCR, but held by the uncalibrated confidence gate (as for v1 scans);
    - 19 have no Document AI read: Internet Archive scans with only the archive's OCR;
    - 6 have a text layer, but the own G.O. number was not found
  - **Blocked on the owner:**
    - (1) run `ocr_corpus.py --scans-too --force --id …` for the 25 orders (paid Document AI, owner's credentials), then `join_ocr_cache.py`;
    - (2) decide how the sandbox treats OCR'd public orders: a labelled sandbox TEST confidence threshold vs reviewer confirmation on the review screen
    - **(2) decided 14:26 IST: the owner verifies the OCR'd orders himself on the OCR review screen** (no sandbox test threshold). Confirmations must be kept in Postgres (`C2_STATE_STORE=postgres`, local DSN), because the memory store loses them on restart. The developer's Cloud SQL IAM login is read-only
- **Owner, 14:43–14:46 IST:**
  - **(2) changed:** OCR'd public orders whose lowest page confidence is ≥ 0.80 pass without review, in sandbox v2/both only (`sandbox.yaml` `ocr.public_auto_pass_min_confidence: 0.80`). They are listed as auto-passed, not as reviewed (ADR-0020 addendum). Synthetic or classified scans still wait for a reviewer
  - **Result:** 13 of the 17 auto-passed (lowest page confidence 0.965–0.985). Still held:
    - ESE01 38/2023: own G.O. number not found in the OCR text;
    - 3 gazettes: source tag GAZ ≠ the department named in the text
  - **Content check of all 83 cited orders' text:** each is the real order with readable text, so none was dropped
  - **The 19 never read by Document AI + 6 unresolved → re-run with the chunked OCR** (owner): same `ocr_corpus.py --scans-too --force --id …` command (15-page chunks), then `join_ocr_cache.py`
  - tests: new `test_public_ocr_auto_pass.py` (6); full suite **1305 passed, 4 skipped**; ruff, mypy clean; Mac md5 verified
- **Data collection plan check (owner 15:00) → item 1 "checks after OCR" DONE (15:06–):**
  - owner's Document AI run: 25 of 25 read (263 pages); `join_ocr_cache.py` → 42 whole-file responses
  - hand check of the 25 new texts: all are the real orders with readable text. ESE01 66/2018 averages 0.658 only because page 3 is blank (no text, confidence 0); pages 1–2 are 0.98
  - `reconcile_dates.py` fix: the order's own line is now also read for G.O.(Rt), and for dates written as "10th July, 2023" or "Dated:-14.09.2021". Same rule: only the own line above Read, nothing guessed
    - printed = archive: 1,010 → 1,073; unreadable: 354 → 291 (237 of them are gazettes, which have no G.O. line); 0 mismatches; `--write` done; `date_review.csv` empty
    - the rest: 27 have no own line in the text and 27 have the date off the own line; their archive date is kept
  - `audit_corpus.py`: 1,375 audited, no problems. `validate.py`: only the 2 known cases (GAD 17/2023 document missing, GAD 9/2025 withheld)
  - `extract_relations.py`: 4,221 candidates (+3 references resolved from the new OCR; SUPERSEDES 38 / AMENDS 137 unchanged); 1,982 cited items not held
  - v2 still checks out (201 files, 0 problems; seed up to date)
  - sandbox v2: 24 public orders auto-passed (was 13). Still held:
    - 12 G.O.s whose header the backend parser does not read (e.g. "G.O. Ms. No.:117", no department on the own line);
    - 6 gazettes (tagged GAZ, and the backend has no own-reference rule for gazettes)
- **Sandbox document reader for real headers (owner OK 15:14 IST) — DONE** (`backend/app/ingestion/metadata.py`, plan §4.3/§4.4):
  - own-line forms: "No.:117", "M s.No.141", "Date:", "Dated:-", and dates in words. Read into the strict form, then resolved as before; when two candidates exist, the earlier line wins
  - department headings may have a lower-case section in brackets
  - **gazette rule:** the masthead ("W.No.3 AMARAVATI, … 2022 G.648" + "RULES SUPPLEMENT TO PART I" / "PART I EXTRAORDINARY") → `AP-GAZ-GAZETTE-<E|W><RS?><part>-<G.no>-<year>`, department GAZ, doc type "Gazette Notification". Instrument RULES only when the gazette notifies "… Rules, <year>". No readable part or edition → no ID (review, never guessed)
  - **result:** 15 of the 18 held public orders now resolve to the corpus's own IDs; 80 of 83 are indexed in sandbox v2 (34 of them auto-passed OCR). Still held, by design:
    - ESE01 66/2018: the own line is missing from the PDF text layer;
    - Gazette 3644/2024: no part line on page 1;
    - Gazette ERSI-1905/2023: page 1 has no masthead
  - tests: new `test_metadata_real_headers.py` (15); full suite **1320 passed, 4 skipped**; ruff, mypy (139 files) clean
  - regression harness (CLAUDE.md §9.5): `evaluation/reports/2026-11-13-baseline.md`, identical to 11 Nov (0 disclosures in 1,142 checks; recall@10 0.754; MRR 0.833; A/C/E/F P = R = 1.000)
  - `PIPELINE_VERSION` not bumped (it is part of the confirmed-OCR key; bumping would drop reviewers' confirmations)
  - **v2 pre-send baseline unchanged** (A 3/20, E 13/18, F 0/63, B/C/D/G 0): ingestion is no longer the bottleneck. Only 11 order-to-order links reach the sandbox graph, and effective dates are not extracted → items 2 (effective dates) and 3 (links) of the data collection plan
- **Item 3 — links between orders in the sandbox (owner OK 15:52 IST) — DONE:**
  - why only 11: the reader found "supersedes" only in the form "in supersession of … G.O. 1st read above", and "amends" only by ordinal. Read lists ending in "&&&" / "Ref: 1.G.O…" were not parsed; "GA(SC.F)" / "School Edn." were not known department names; "1 st", "first … eighth read above" were not read; the operative text was split at "BY ORDER AND IN THE NAME …"
  - changes in `metadata.py` (plan §4.3, §7.2):
    - supersession and amendment naming the earlier order by NUMBER, when the number matches exactly one order in the Read list;
    - "hereby make the following amendments to … G.O.Ms.No.N": the first order named after the phrase;
    - amendment / modification by title with exactly one order in the Read list → AMENDS with explicit=False (a candidate, for review);
    - a letter is never "amended";
    - ordinals normalised; Read-list and operative-part boundaries fixed;
    - "No. 34" is no longer a sentence end
  - departments.yaml + data_collection/scope.yaml (kept in step): aliases GA, G.A, School Edn
  - `conflict/deterministic.py`: no type A when the proposal ALSO cites the superseding order ("G.O.57 read with G.O.54" applies the newer order)
  - **result in sandbox v2:**
    - order-to-order links 11 → 43; 25 of the 38 verified chain edges recovered, the rest mostly have the older order outside the Read list;
    - **pre-send on the 147 planted conflicts: A 3/20 → 18/20**, E 13/18, F 0/63 (needs effective dates, item 2), B/C/D/G 0;
    - **clean files flagged: 11 → 6 of 54**
  - **ground-truth finding (needs the owner's decision; NOT edited, CLAUDE.md §9.2):** 4 of those 6 are probably mislabelled as clean. The real G.O.Ms.396/2016 explicitly says "in supersession of the orders issued in G.O.Ms.No.295 … and G.O.Ms.No.381" (GAD 145/2017, 187/2022, 202/2024), and GAD 182/2022 relies on the 396/2016 relaxation, valid only to 30-09-2017. The other 2: an unconfirmed inferred supersession (review prompt), and a citation of ESE 66/2018, still held
  - tests: +5 relation tests, +1 conflict test; full suite **1325 passed, 4 skipped**; ruff, mypy (139) clean
  - harness `evaluation/reports/2026-11-13-baseline-3.md` identical to before (0 / 1,142 disclosures; recall@10 0.754; MRR 0.833; A/C/E/F P = R = 1.000)
  - Mac md5 verified
- **Answer-key fix (owner OK 17:37 IST):** `efiles_v2/scenarios/relabel_v2.yaml`; the builder applies it after the touchpoint draw, so no other file changes. Each entry is checked: the scenario must still have this date and these cited orders, and the anchor must match the governing order's text
  - GAD01-CLEAN-026 / 035 / 038 → type A (governing G.O.Ms.396/2016, "in supersession of the orders issued in G.O.Ms. No. 295 … and G.O.Ms. No. 381");
  - GAD01-CLEAN-039 → type F (G.O.Ms.396/2016 relaxation "up to 30/09/2017", note 2022)
  - keys keep their old names (stable IDs); `relabelled: true` marks them
  - side effects:
    - one hand-picked anchor (FIN G3, gazette 3880/2024) made OCR-tolerant ("self\s*-\s*declaration"), because the gazette's text is now the Document AI read;
    - 8 quotes refreshed from the new OCR text (same orders)
  - re-render: 201 files, **151 planted conflicts**, 0 problems; seed unchanged (note texts identical)
- **Item 2 — effective dates, started (backend):**
  - `metadata.py` reads the order's stated "with effect from" / "shall come into force (with effect) from" date: the subject first, then the operative part. Several different dates, or "immediate effect" → none, never guessed. Stored as `stated_effective_from`
  - `pipeline.py`: an instrument's `effective_from` = max(issue date, stated date). A later commencement makes it not yet effective; a retrospective date never moves it before its issue
  - DR / DA "Revised orders" ("raising … from 12.052% to 15.196%") count as changes
  - `deterministic.py`: **new type F rule**: a cited order amended (effective) before the proposal's date, with the amending order not cited → "check that the amended provisions are applied" (certain only for confirmed links)
  - tests: +2 conflict, +4 effective-date; full suite **1330 passed, 4 skipped**; ruff, mypy clean. Harness `2026-11-13-baseline-2.md` unchanged (0 / 1,142 disclosures; A/C/E/F P = R = 1.000)
  - **v2 pre-send now (151 planted):**
    - A 21/23, F 40/64 (was 0), E 13/18; B/C/D/G 0;
    - **clean flagged 10 of 50**. They are mostly the same class of answer-key gap, systematic this time: "clean" files that cite an order a later verified amendment changed before the note date (32/2017 by 38/2017; 110/2016 by 117/2016; 117 by 136/2016; 34/2020 by 7/2022 / gazette 648; 20/2011 by 38/2023), or that is not yet in force (FIN 31/2022 from 02-04-2022, note 10-03-2022)
  - **decision needed (owner):** builder rule "a clean file must be clean against ALL verified links and effective dates". Proposed: move the note date into the clean window, and relabel only when no window exists. This also needs the corpus side of item 2 (`effective_from` + source in meta.json)
- **Item 2 corpus side + clean rule (owner OK 17:54 IST) — DONE:**
  - `data_collection/tools/extract_effective_dates.py` (same rule as the backend): 147 orders state an effective date, written as `stated_effective_from` + evidence, `effective_from` with source "stated_in_order" (never overwrites extracted or verified values)
    - 121 of them are retrospective; 25 take effect after issue (e.g. FIN 31/2022 from 02-04-2022, FIN 54/2018 from 05-06-2018);
    - 25 state several dates (none taken); 1,203 state none (issue date kept);
    - audit: no problems; reconcile_dates unchanged
  - `build_scenarios_v2.py`: **a clean file must be clean against ALL verified links and stated effective dates.** The cited orders must be in force on the note date (max of issue and stated date), and no verified later order may change a cited one before the file is finished. Otherwise the note date moves into the clean window; with no window, the file becomes a planted conflict (A / F)
  - a clean file with a later change carries `close_by`; the renderer then moves it quickly (minutes, consultations back in a day; same random draws)
  - render: Cabinet meeting date fixed (it could loop when the reply came back in a day)
  - **result:** 201 files, **163 planted conflicts + 38 clean** (19%; was 50 clean); check 0 problems; seed rebuilt
  - **v2 pre-send (sandbox, 163 planted):** A 21/23, **F 48/76**, E 13/18, B/C/D/G 0; **clean files flagged 0 of 38**
  - not reached by pre-send: B/C/G (synthetic circulars wait in the review queue as letters), D (precedent; pre-send does not check it), the rest of F (links not found in the Read list)
- **B / C / G: letters + Gemini (owner 18:14, choices: real-format numbers; build the Gemini check):**
  - renderer: synthetic circulars / memos / proceedings carry real-format numbers ("Circular Memo No.SYNESE01-GEN/41/2020, Dated: 20-10-2020"; the SYN code is never a real number), and the notes cite them that way. 26 of 26 lower instruments are now indexed by the ordinary pipeline. Receipts and U.O. notes stay in review (no own number / another department named)
  - Gemini (ADR-0017 addendum):
    - `app/agents/llm.py` (`GeminiVertexClient`, `CachingLLM`, `RecordedLLM`, `llm_from_settings`);
    - `app/conflict/judgment.py` + `prompts/conflict_contradiction.v1.md`;
    - wired into the pre-send check (`presend.py` `contradictions=`, `routes.py` `contradiction_check`, `runtime.llm`, `main.py`);
    - settings `C2_LLM_PROVIDER=none|vertex|recorded`, `C2_GEMINI_MODEL`, `llm_recorded_dir` (`.env.example` updated)
  - tests: new `test_conflict_judgment.py` (9); full suite **1339 passed, 4 skipped**; ruff, mypy (143) clean. v1 harness unchanged (0 / 1,142 disclosures; A/C/E/F P = R = 1.000)
  - `evaluation/presend_v2.py` (`--count` / `--live` / recorded): needs **29 Gemini questions (~29k input tokens)**
    - without answers: A 21/23, F 48/76, E 13/18; B / C / D / G 0; clean 0/38 flagged;
    - B / G incomplete in 16 files
  - synced to the Mac 21:04 IST after the device link was down 18:30–21:00 (md5 verified, 10 files)
  - **next:** owner runs `presend_v2.py --live` from backend/ (gcloud ADC); then score B / G from the cache. After that, type C authority rules for FIN / GAD / ESE (mock, from the hand-picked procedure orders)
- **B / G live run + hand check + fixes (13 Nov, 21:15–):**
  - live run on the Mac (owner's other session, 29 questions, 0 incomplete): A 21/23, **B 7/8**, C 0/12, D 0/16, E 13/18, F 48/76, **G 2/10**, clean 0/38 flagged. Report `evaluation/reports/2026-11-13-presend-v2.md`; answers cached in `data/synthetic/mock_v1/llm/gemini-3.5-flash/` (29)
  - hand check (recorded replay): 7 B flags right; missed B FIN 106/2019 (judged consistent). Extra G flags on B files: 4 right (SER 39/2020, FIN 78/2016 circ. 21, GAD 183/2022, GAD 203/2024), 2 weak (ESE 49/2023 same rule in other words; FIN 78/2016 circ. 25 quote about another provision)
  - G misses: 5 got "insufficient" (excerpt lacked the rule: OCR text has no paragraph breaks), 3 had no pair (gazette citations not resolved)
  - fixes: `judgment.excerpt` line windows (half-overlapping, word + word-pair overlap, rarer terms weigh more, note only as tie-break, 6,000 chars); `metadata._GAZ_CITE` resolves note citations of gazettes to the masthead ID (edition + part required); prompt `conflict_contradiction.v2.md`; `contradictions(cited, note_text)` in presend / routes
  - diagnostic (evaluation only): the governing clause is now in the excerpt for 9 of 9 G files that get a pair (was 4); FIN 137/2024 still has no pair (gazette 3644 held: no part line)
  - recorded re-run without answers (new prompt → new keys): A/E/F unchanged, clean 0/38. Changes: ESE EXAMS 38/2020 loses an F (now cites the amending gazette); 3 files gain an uncertain E "awaiting review" for held gazettes 3644 / 1905 (FIN 130/2023, FIN 137/2024, ESE PROG 55/2024)
  - tests: +4 (judgment windows, note never sent, gazette citation); full suite **1343 passed, 4 skipped**; ruff, mypy clean; v1 harness unchanged (0 / 1,142; recall@10 0.754; MRR 0.833; A/C/E/F P = R = 1.000)
  - **next:** owner re-runs `presend_v2.py --live` (31 questions); then read gazettes 3644 / 1905 (part line), then type C rules
- **prompt-v2 live run + hand check (13 Nov 22:08–):**
  - live run on the Mac (31 questions, ~47k input tokens, 0 incomplete): A 21/23, B 7/8, C 0/12, D 0/16 (7 other), E 13/18, F 48/76, **G 7/10**, clean 0/38 flagged. Report `evaluation/reports/2026-11-13-presend-v2-prompt-v2.md`; cache now 60 answers (copied here)
  - hand check (recorded replay, all quotes verbatim): the 7 G flags are right (ESE 13/14/67/68: transfer years; FIN 138: premium enhancement once vs twice; GAD 183/203: SC/ST age concession). All B flags right. Extra G flags on B files: ESE 49/2023 "date of TET" vs "date of result" (different start dates: kept, reviewer decides), the rest right; FIN 78/2016 circ. 25 now judged consistent (weak flag gone)
  - remaining problems found: (1) FIN 139/2024: Gemini found it, but its quote "self -declaration" failed the word-for-word check against the OCR "self -\ndeclaration"; (2) GAD 166/2020 (planted D): **false B** between G.O.Rt.2740/2019 and 2657/2019; 2740 amends para 3 of 2657, but the reader missed its unnumbered "Read:-" entry, so no AMENDS link; (3) FIN 106/2019: the two circulars were never asked as a pair, because an unconfirmed supersession inferred from their identical subjects (§7.3) counted as a link; (4) GAD 164/2020: "insufficient" (the synthetic memo says only "a post"; left as is); (5) FIN 137/2024: gazette 3644 still held
  - fixes: `judgment._norm` ignores spacing around hyphens (nothing else); `metadata._read_list` reads a single unnumbered "Read:-" entry (only when it names one order); `judgment.settled_pairs`: an unconfirmed inferred SUPERSEDES no longer exempts a pair (text-stated or confirmed links still do)
  - replay with the 60 answers: **G 8/10, F 50/76** (the Read-list fix links two Cabinet files), D other 6 (false B gone), A/B/C/E unchanged, clean 0/38; 1 file incomplete (FIN 106: 1 new question)
  - tests: +4; full suite **1347 passed, 4 skipped**; ruff, mypy clean; v1 harness unchanged (0 / 1,142; recall@10 0.754; MRR 0.833; A/C/E/F P = R = 1.000)
  - **next:** owner runs `presend_v2.py --live --label prompt-v2b` (1 question); then gazettes 3644 / 1905 part line; then type C rules
- **prompt-v2b live run (owner 22:28) + gazettes 3644 / 1905 (22:30–):**
  - live run (1 new question, FIN 106/2019): B **8/8**, G 8/10, F 50/76, A 21/23, E 13/18, C 0/12, D 0/16 (6 other), clean 0/38. Gemini's answer (Rs.15,000 vs Rs.12,000 per month) checked: right. Report `2026-11-13-presend-v2-prompt-v2b.md`; cache 61 answers (copied here)
  - owner's note: `--count` counted saved questions too (said 31 when 1 was paid). Fixed: it now reports "N questions, M already saved, K not yet saved (only these would be sent and paid)"
  - **gazettes 3644 / 1905:** Document AI lost (3644) or scrambled (1905) the masthead, but page 1's PDF text layer prints it ("PART I EXTRAORDINARY … G.3644"). `metadata.with_printed_masthead` + `extract.pdf_text_layer`: for files filed as gazettes (source tag GAZ) whose OCR text gives no gazette ID, the page-1 text layer is put in front so the masthead rule reads it. A G.O. reprinted in a gazette (e.g. FIN G.O.Ms.82/2023) keeps its G.O. ID: the first try without the GAZ condition took 82/2023's masthead and lost two type A finds; caught by the replay and fixed
  - a gazette now ranks as what it notifies (`_gazette_instrument`): "… Rules, <year>" → Rules (as before); else the instrument on its own line — Gazette 3644 notifies Finance Cir.Memo 25/2023 → CIRCULAR_MEMO (level 7); none named → no level
  - both indexed: 1905 (Rules, AMENDS G.O.Ms.20/2011); 3644 (circular memo level). Sandbox v2 now holds 82 of 83 cited orders (only ESE 66/2018 held: own line missing from the PDF text)
  - pre-send: one order cited twice in a note (Ref list + para) gave the same flag twice; flags are now unique (regression test first)
  - replay (61 answers): A 21/23, **B 8/8**, C 0/12, D 0/16 (6 other), E 13/18, F 50/76, G 8/10, clean 0/38. 3 new Gemini questions (FIN 130/2023, 137/2024 now have the 3644 text)
  - **answer-key / data findings for the owner (NOT edited, CLAUDE.md §9.2):** (1) FIN 130/2023: the note (Sept 2023) cites Gazette 3644 dated 05-01-2024, so the system now flags F "takes effect only on 05-01-2024" — correct for the data, but the builder picked an order issued after the note; (2) FIN 137/2024 is planted G with 3644 as the higher rule, but 3644 notifies a circular memo (same level as the synthetic memo), so the check can only find B there
  - tests: +6 (masthead ×3, gazette instrument, duplicate flag, --count is evaluation code); full suite **1352 passed, 4 skipped**; ruff, mypy clean; v1 harness unchanged (0 / 1,142; recall@10 0.754; MRR 0.833; A/C/E/F P = R = 1.000)
  - **next:** owner `--count` then `--live --label gazettes` (3 questions); owner decides on the two findings; then type C rules for v2
- **Type C on set v2 + answer-key fixes (owner "ok proceed", 13 Nov 23:03–):**
  - **rules:** `data/ontology/authority_rules_v2.yaml` (status mock = unverified; loaded when `C2_SANDBOX_SEED=v2`; "both" keeps the v1 file because the two sets share order numbers). 5 rules, each quoting a real order (5 of 6 quotes verbatim in the indexed text; G.O.51 para 11 differs by one stray space in the PDF text layer): ESE teacher / Headmaster transfers need the Transfer Committee (G.O.Ms.22/2025 paras 4, 5); no additional funds / re-appropriation in the first two quarters of 2016-17 (G.O.Ms.51/2016 para 11); Deputy Collector transfers belong to GAD (G.O.Ms.74/2017); Housing Board / Rajiv Swagruha under MA&UD (G.O.Ms.99/2017); tourism, culture and heritage bodies under YAT&C (G.O.Ms.32/2017)
  - **engine (`procedural.py`):** rules may be limited to departments and named subjects, may end (`effective_until`), and may state a barred period; actions `reappropriation`, `business_allocation`. v1 behaviour unchanged
  - **facts (`facts.py`):** a named-subject rule gives the action when the subject has no action word; "It is proposed that …" is read as the proposal; the proposed body is the ONE known body the sentence names (bodies set aside by "without / not" do not count; several → unknown, never picked); "grants" read from the proposal's own verb
  - **pre-send:** a draft that only says "Para 4 may kindly be seen" now gets its proposal from the file's earlier notes the officer may see (`file_notes`); the draft's own proposal wins when it has one
  - **result (replay):** **C 10/12**, no C flag on any non-C file, clean 0/38, v1 harness unchanged. Not found, by design: FIN 81/2016 and 88/2016 — G.O.Ms.110/2016 only grants permission for 10,000 posts; it does not state that recruitment needs Finance permission, so there is no clause to quote (answer-key weakness, reported to the owner; not edited)
  - **caveat:** the v2 C files were written from these same orders: recall shows the rules are applied correctly, not that rules are found unaided. The single-body reading is a pattern, not understanding: a sentence that names one body in order to reject it would be misread (grounded Gemini extraction is the upgrade path, ADR-0010)
  - **answer key (owner OK):** FIN 130/2023 now rests on G.O.Ms.2/2022 read with 105/2022 (was Gazette 3644, issued after the note); FIN 137/2024 relabelled G → B (key FIN01-B-HB4): 3644 publishes a circular memo, same level as the synthetic instruction. Totals: B 9, G 9; 163 planted, 38 clean; check 0 problems; seed rebuilt. `handpicked_bcg.yaml` `also_cite`; `render_efiles_v2.py --overwrite` (lists files the run did not write; no deletes needed)
  - replay with the 61 saved answers: A 21/23, B 8/9, C 10/12, D 0/16, E 13/18, F 50/76, G 8/9, clean 0/38; 5 Gemini questions not yet saved (FIN 130, FIN 137)
  - data collection plan: `check_coverage.py` now counts set v2 and marks 2026 orders out of scope → only gap left: real circular memos (not online). Holdback candidates listed (GAD 139/2025, 109/2025, 72/2025): owner to choose
  - tests: +14 (`test_authority_rules_v2.py`); full suite **1366 passed, 4 skipped**; ruff, mypy clean
  - temp file for the owner to delete: `Project_1/_to_delete/v2sync.tgz` (deep rendered files cannot be copied to the cloud copy directly)
- **Demo holdback + SECURITY FIX (owner's choices 13 Nov, late):**
  - **holdback:** GAD G.O.Ms.139/2025 moved to `staging/holdback/` (`find_holdback.py --move`; `scope.yaml` updated; `extract_relations.py` re-run: 4,247 candidates from 1,374 documents). Two open Cabinet.II files added through `scenarios/holdback_v2.yaml` (211, 212/2025; cite 59/2018 read with 8/2021); nothing else changed (checked by digest). **203 files, 163 planted, 40 clean**; check 0 problems; 85 cited orders indexed
  - sandbox: `public_holdback.csv`, `arrivals_from_v2`, `adapter.order_arrives`, `GET /sandbox/orders/pending`, `POST /sandbox/orders/arrive`. Local end-to-end run: G.O.139 ingested, AMENDS 59/2018 confirmed, notice lists both files
  - **security finding while testing that run:** UNCLASSIFIED papers inside e-Files counted as "public" → readable by every officer on set v2 (**4,182 officer × document disclosures** against the v2 access matrix; a Finance ASO saw the two Cabinet.II files in the notice). mock_v1 has no such papers, so the v1 harness stayed at 0. **Fixed** (ADR-0009 addendum): public = published instrument only; file papers follow the file's reach; policy version `2026-11-13-mock`. Regression test written first (failed with 4,182, now 0); scope filter test; v1 harness 0 / 1,142 unchanged; v2 pre-send results unchanged
  - tests: full suite **1369 passed, 4 skipped**; ruff, mypy clean
  - **still to do for the plan's step 12:** owner re-uploads the corpus (`08_upload_public_corpus.sh`; holdback and `_review` are left out)
  - **next (owner's order):** type D (precedent) in pre-send, then the first cited Gemini answer (M4). Also: add a v2 outsider leakage suite to the evaluation harness (today only the unit test covers it)
- **LLM failover (owner's request 14 Nov; ADR-0021):** `OllamaClient` (loopback only), `FailoverLLM` (circuit breaker: 2 failures → local model; trial on Gemini after 60 s, doubling to 15 min; back to Gemini on the first success), per-model answer cache, fallback named in the flag text. Off by default (`C2_LLM_FALLBACK=ollama`, `C2_OLLAMA_MODEL`). `presend_v2.py` now prints why a question got no answer. Tests +5 with fake engines (no Ollama was called: **not yet run against a real Ollama model, quality not measured**); full suite **1374 passed, 4 skipped**; ruff, mypy clean. Decision still open: which model
- **Synthetic set v2 — audit of every missed planted conflict and corpus fixes (owner "complete the corpus work", 14 Nov):**
  - **finding 1 (loading gap):** the sandbox loaded only the orders the notes CITE (85), so 16 superseding / amending orders were absent and those A / F conflicts could never be found. `index_public_cited.py` now also lists the held orders that change a cited order, taken from the corpus's own links (`relations.jsonl`, `chains.yaml` chains and rate series), never from the answer key → **120 orders** (110 MB)
  - **finding 2 (type E files were badly written):** all 18 had the placeholder subject "Proposal relying on an earlier order" and cited an invented form or a raw canonical ID. Now each cites the missing order exactly as a real order of the department printed it (`cite_raw` from `relations.jsonl`), on that order's subject
  - **finding 3 (FIN C1 / C2):** rested on a rule G.O.Ms.110/2016 does not state. Rewritten on what it says (posts under APPSC / SLPRB, para 2; the agencies issue the notification, para 3); rule `FIN-DIRECT-RECRUITMENT-AGENCIES-2016`, action `recruitment`
  - **finding 4 (GAD G3):** the synthetic memo named no post. Now the Chief Legal Advisor's term (rule: 3 years; memo: five years)
  - reader: `G.O.(P).No.` citations are read (test first)
  - renderer side effect: new subjects shifted the random draws, so names / times in later files changed; structure (keys, dates, sections, touchpoints) unchanged (diff 0). 31 stale papers moved to `Project_1/_to_delete/` (no delete permission). check: 203 files, 163 planted, 0 problems
  - **replay (recorded answers, 1 new question for G3):** A 20/23, **B 9/9, C 12/12, E 18/18**, F 57/76, G 8/9, D 0/16, clean 0/40. Was A 21, C 10, E 13, F 50
  - **still held in the sandbox (11 of 120):** 8 scans without a Document AI reading (FIN 115/2023, 116/2022, 154/2018, 16/2019, 29/2024, 31/2024, 7/2020; ESE none) — owner run, billed (cents); FIN 9/2022 OCR confidence 0; ESE 24/2025, ESE 66/2018, FIN 26/2024 "type not recognised" (reader)
  - remaining misses are system work, not corpus: A 3, F 15 (rate series and links the reader does not extract), D 16 (detector not built)
  - tests: full suite **1376 passed, 4 skipped**; ruff, mypy clean; v1 harness unchanged (0 / 1,142)
- **Type D built; set v2 type D files repaired (14 Nov, after the owner's bucket upload):**
  - bucket: the owner's rsync finished (1,507 files, 784 MiB). Not verifiable from here (no credentials in the cloud copy). **To check by the owner:** the upload script has no delete option, so G.O.Ms.139/2025 (held back after yesterday's upload) and any `_review` leftovers may still be in the bucket
  - **check:** `app/precedent/consistency.py` + pre-send hook (ADR-0022): opposite disposal to most earlier same-subject files the officer may see, not referred to → uncertain type D. Scoped L1 filter + re-check per candidate; no model call
  - **set v2:** 4 of 16 type D files pointed to an earlier file that was trimmed out; none recorded a disposal to compare. Builder re-points or turns the file clean (1 case); renderer writes the section's usual disposal in clean / earlier files and the opposite in type D files. One clean date moved → ESE file numbers after it shifted; 364 stale papers + 87 stale documents moved to `Project_1/_to_delete/`. check: **203 files, 162 planted, 41 clean, 0 problems**
  - owner ran the 7 scans through Document AI (63 recorded readings joined) and the G3 question (68 saved answers)
  - **replay:** A 21/23, B 9/9, C 12/12, **D 15/15**, E 18/18, F 57/76, G 8/9, clean **0/41**; 2 Gemini questions not yet saved (texts shifted by the re-render). First version of the check flagged 4 clean files that followed the usual line after a stray case → majority rule (test added)
  - **honest reading:** D, C and E are found in full because the set states them in forms the checks read; that proves the wiring, not real-world recall. Open: F 19 (rate series / links the reader does not extract), A 2, G 1
  - tests: +5 (`test_precedent_consistency.py`); full suite **1381 passed, 4 skipped**; ruff, mypy clean; v1 harness unchanged (0 / 1,142)
  - **next:** first cited Gemini answer (M4: evidence package → answer → citation check), v2 outsider leakage suite in the harness
- **Exact next action:** after (1) and (2): re-run the v2 pre-send baseline; then decide how synthetic correspondence is ingested; then the v2 evaluation suites; upload after all checks

### 2026-11-13 · Data workstream / M2 · Corpus OCR tool + gazette ID rule (owner OK 09:17 IST)
- **Status:** DONE. Corpus complete for upload: **1,375 documents** (1,137 G.O.s + 238 gazettes)
- **Gazette No.914 of 2022:** the one held was the 7 Sep GAD gazette (I had said 25 Jan earlier, wrongly). The 25 Jan Law gazette (Retired Chief Justices and Judges benefits rules) is now saved as `AP-GAZ-GAZETTE-EI-914-2022-D20220125`, with `id_note`. It has a readable text layer, so no OCR was needed. Audit clean; validate fails only the 2 known records
- **OCR cache slimmed:** the Document AI responses held page images (~1 MB/page). They were stripped from all 300 cached responses: 1,316 MB → 229 MB. `ocr_corpus.py` now strips them before caching (as backend `CachingOcr` does); the PDFs stay the source. Staging is now ≈1.2 GB (rule-library 0.97 GB)
- **Upload allow-list (owner, 10:44 IST: only files the project uses):** `08_upload_public_corpus.sh` now uploads only:
  - per document: order.pdf, ocr.txt, meta.json;
  - `manifests/relations.jsonl` and `provenance.jsonl`;
  - `ocr_cache/` (Document AI layout for page/paragraph locations).

  It leaves out `_review/`, `holdback/`, `ocr.archive.txt`, the working reports and lists, temp and OS files; logs are outside staging. It prints both lists before uploading. Checked locally: 1,375 × 3 + 300 cache + 2 manifests in; 234 archive texts, 8 review records, 7 reports/lists and 4 .DS_Store out
- **Synthetic corpus (owner asked):** later, with its own script. The sandbox sources already go to `synthetic/mock_v1/sources/` through the document store. The ground truth (manifest answer key, golden questions, planted conflicts) must never go to a bucket the API service account can read (CLAUDE.md §9.2)
- **Implemented:**
  - `data_collection/tools/ocr_corpus.py`, run from backend/ with the gcp extra:
    - reads with the backend's `DocumentAiOcr`: pinned v2.1.1 (refuses another version), asia-south1, te/en hints;
    - sends ≤15-page chunks and keeps each response in `staging/ocr_cache/documentai/<version>/<sha256>-p<first>.json`, so it never pays twice;
    - writes `ocr.txt` (form-feed page breaks) and keeps the old text as `ocr.archive.txt`;
    - records `ocr_source`, `ocr_version`, `ocr_pages`, mean `ocr_confidence` and `ocr_pages_unconfirmed` in meta;
    - skips withheld / document_missing records and files already read with this version; stops after 3 errors in a row;
    - dry run by default: files, pages and cost. `--scans-too` adds scans that only have the archive's OCR (better text + page locations)
  - **gazette ID rule (ADR-0007 addendum):** the first record keeps `AP-GAZ-GAZETTE-<part>-<no>-<year>`; a repeat gets `-D<yyyymmdd>` (publication date), with an `id_note`. Applied in `collect_gazette.py` `save_row`
  - the full candidates list is kept as `staging/manifests/gazette_candidates_full_2026-11-12.jsonl`, because each batch run rewrites the candidates file
- **Tests run:**
  - fake-engine run in a temp data root: a 17-page PDF went as chunks [1–15], [16–17]; two cache files; `ocr.archive.txt` kept; meta fields set; a second dry run finds 0 files (idempotent);
  - live dry run on the real corpus (no network): **145 files / 369 pages** (144 gazettes + GAD 30/2019); with `--scans-too` **371 files / 1,254 pages**: ≈US$1.88 at list price, or ≈US$0.38 if this month's first 1,000 pages are still free (US$1.50 per 1,000 pages, cloud.google.com/document-ai/pricing, checked 13 Nov)
- **Fixes during the run:**
  - the "unreadable" check flagged short, readable gazettes. It now also accepts ≥50 words with ≥12% common words; Telugu-majority text is not judged by English words. The same fix is in `audit_corpus.py`;
  - an expired ADC sign-in made the SDK retry silently (looked like a hang). The tool now refreshes the credentials first and stops with the login command;
  - pypdf warnings are hidden, and `… sending` is printed per chunk
- **Result:** 292 files / 1,067 pages read with v2.1.1 (65 gazettes, 227 scanned G.O.s); 300 cached responses; mean confidence 0.98. 5 files are below 0.9: FIN 25/2024 0.74, FIN 36/2022 0.79, GAD 39/2024 0.82, FIN 12/2025 0.84, FIN 9/2022 0.86. No page without confidence; no empty text. GAD 30/2019 (Telugu) now reads cleanly (0.978)
- **After OCR:**
  - extract_relations: 4,218 edges (137 AMENDS, 38 SUPERSEDES, 4 REPEALS); 1,819 citations resolve inside the corpus;
  - `reconcile_dates --write`: 1,009 printed = listing date, 354 unreadable (mostly gazettes, which have no G.O. line), 0 mismatches;
  - audit: **no problems**. The gazette identical to the G.O. it republishes is now counted as linked (validate + audit), not an error. `validate.py` fails only GAD 17/2023 (empty PDF) and GAD 9/2025 (confidential), as expected;
  - coverage: PASS for type G (109 rules), 21 SUPERSEDES / 91 AMENDS with both ends held, 45 DA/DR orders. GAPs: memos (type C), 2026 orders, synthetic e-Office parts
- **Exact next action:**
  - owner, on the Mac:
    1. (done) OCR;
    2. then `collect_gazette.py --batch --dept "GENERAL ADMINISTRATION" --years 2022 --types 1 --download --limit 0` to fetch the 7 Sep 2022 gazette No.914;
  - then extract_relations, audit, reconcile_dates

### 2026-11-12 · Data workstream / M2 · e-Gazette batch mode for Rules / Acts (owner OK 22:54 IST)
- **Status:** DONE (237 gazettes collected); OCR of scanned ones pending
- **Implemented:** `data_collection/tools/collect_gazette.py --batch`:
  - searches every department × year × gazette type (default FINANCE, GENERAL ADMINISTRATION, SCHOOL EDUCATION; 2016–2025; Extraordinary + Weekly);
  - keeps only rows about Rules, Regulations, Acts, Ordinances, Codes or bye-laws. `skip_topics` still apply; appropriation / vote-on-account is excluded (scope.yaml);
  - dry run by default, and lists candidates to `staging/manifests/gazette_candidates.jsonl`. `--download --limit N` saves them (0 = all). Saving happens right after each search, because download tokens belong to the search;
  - 10 s between requests; stops after 3 errors in a row; already-held files are skipped. The save logic is shared with `--pick` (`save_row`). `--dept` is repeatable (e.g. add LAW for Acts)
- **Tests run:** offline only (the workspace cannot reach the site):
  - against the saved 18 Oct search page (Finance 2024, Extraordinary): 35 results, 5 kept. Kept: APGLI Fund Rules 2024 (RULE), Pension Rules notification, the Contract Employees Act 2023 commencement, the Regulation of Appointments Act notice, and the NMR regularisation. The Vote-on-Account ordinance was excluded;
  - a fake-site run saved 2 files into a temp data root, with correct IDs (AP-GAZ-GAZETTE-EI-<no>-<year>) and candidates file
- **Not verified live:** whether a search returns all results or only the first page, and the site's exact names for GAD / School Education (a wrong name prints `!!` and the run goes on)
- **First dry run (owner, 23:14 IST):** FINANCE / GENERAL ADMINISTRATION / SCHOOL EDUCATION / LAW, 2016–2025, both types: 80 searches, result counts vary (0–376), so the site is not cutting results to one page. 637 candidates; on review many were noise:
  - "Act" alone matched bans under the Public Security Act, pipeline declarations and holidays;
  - "Rules Supplement" parts also carry ordinary G.O.s (e.g. 130 aided-school takeovers in School Education 2023).
- **Filter tightened:**
  - kept: rules, rule N, regulations, codes, manuals, bye-laws, and an Act or ordinance coming into force or amended;
  - dropped: elections, holidays, premises declarations, Public Security Act bans, takeovers;
  - LAW and other non-scope departments are kept only for an Act change or one of our keep topics;
  - Rules Supplement no longer means "Rule";
  - each run starts a fresh candidates file.

  Re-applied to the 637: **238 kept** (GAD 109, School Education 60, LAW 44, Finance 25; 109 RULE, 129 notifications about rules/Acts). Some noise remains (e.g. the SALT project, an SIT declaration)
- **Downloads (owner):** test of 5 (23:32 IST), then full run, finished 12 Nov ~00:30 IST: **237 gazettes saved**, 238 listed. GAD 109, School Education 60, LAW 43, Finance 25; 109 RULE + 128 notifications; 2016–2025 (most in 2022–2023). 118 are linked to a G.O. we hold that they republish
  - **1 ID collision:** two different Extraordinary Part I gazettes are both "No.914 of 2022" (25 Jan: Law, judges' benefits rules; 7 Sep: Ministerial Service Rules 1998 amendments). The second was not saved ("exists — not overwritten"). Gazette numbers are not unique per part and year, so the ID rule needs a suffix (ADR-0007, open);
  - `fontTools` warnings from pypdf are harmless; owner may install it in the venv
- **After the gazettes (09:00 IST, 13 Nov):** extract_relations gives 3,966 edges from 1,374 documents (117 AMENDS, 37 SUPERSEDES, 4 REPEALS); 1,765 resolve inside the corpus
  - audit: 84 gazettes with unreadable text (mostly Telugu / old fonts) and 60 with no text need Document AI. AP-GAZ-GAZETTE-EI-342-2023 is the same PDF as AP-FIN01-GOMS-79-2023 (a republished G.O.; keep both, link them)
  - Document AI scope: 288 PDFs have no text layer (1,062 pages), plus the 84 unreadable gazettes (≈367 pages). The whole corpus is 7,681 pages
- **Exact next action:**
  - a corpus OCR tool: Document AI v2.1.1, splitting into ≤15-page requests (or batch mode via GCS), writing `ocr.txt` + `ocr_source`, with a page/cost estimate first. Owner runs it on the Mac;
  - decide the gazette ID suffix (ADR-0007)

### 2026-11-12 · P8 / M9 · Cited orders not in the collection: shared message, clickable (ADR-0019) + collection rounds 2–3
- **Status:** DONE (message + click). The admin coverage page (ADR-0019 part 2) is NOT_STARTED
- **Collection rounds (owner ran):**
  - **round 2** (`--cited`): only the confidential FIN 134/2016 was found (no PDF, still in `_review/`). The other 13 in-scope tier-1 orders had never been searched: they are cited only by orders that were themselves fetched as citations, and the collector follows one level only;
  - **fix:** new opt-in `collect_ia.py --in-scope-depth2` follows one more level, but only to G.O.(Ms) of FIN01/GAD01/ESE01 dated 2016–2025. `--cited staging/…` now also resolves inside the data root;
  - **round 3:** 11 orders added: FIN 44/2018, 52/2017, 56/2020, 144/2016, 195/2016; GAD 12/2020, 32/2021, 33/2021, 48/2021, 63/2021, 151/2017. Still missing: FIN 1557/2016 and GAD 2852/2019 (numbers ≥1000, probably G.O.Rt)
- **Corpus now:** 1,137 orders (FIN01 512, GAD01 386, ESE01 239); 1,635 citations resolve inside the corpus. FIN 56/2020 date verified as printed (02-07-2020; matches G.O.Ms.No.57/2020's reference list)
  - note: G.O.Ms.No.56/2020 cites FIN 25/2020 as "dated 29-03-2020", while 25/2020's own header and G.O.Ms.No.28/2020 say 28-03-2020; the printed header was kept
- **Known gaps (owner, 22:47):** tier 2 (1965–2006, none in the mirror), the 9 in-scope orders the mirror doesn't carry, and the 7 listed without a usable PDF. Hand downloads dropped as impractical
- **Owner request → decision (ADR-0019):** officers should be told a cited file isn't in the database yet. A separate "not in our database" text would reveal which cited orders exist but are restricted (CLAUDE.md §4.7), so the owner chose **one shared message** for both cases, and the gap list for admins only
- **Implemented:**
  - `app/auth/messages.py`: `GUIDE` (was `_GUIDE`), `NOT_IN_COLLECTION`, `CITED_NOT_FOUND`; `DOCUMENT_NOT_AVAILABLE` now includes the collection sentence;
  - type E explanation (`conflict/deterministic.py`), `NO_MATCH` and the approval brief's governing-order message (`agents/routes.py`) use it;
  - sandbox `Citations.tsx`: label "Not found in the records available to you". A not-found citation is now **clickable** and shows the message under the note (no ID, no document link). Same words as the backend, and a test keeps them equal
- **Tests run:** ruff + format clean; mypy 135 files clean; pytest **1286 passed, 4 skipped** (Postgres tests without DSN) + new `test_not_found_message.py` (2 passed); frontend vitest **29 passed**, `tsc` + `vite build` clean
- **Security:** the same text is shown for not-held and hidden orders, so nothing is learnt about existence. The not-found link carries no canonical ID
- **Exact next action:** gazette batch mode (needs owner OK); admin coverage page (ADR-0019 part 2: admin role is a mock, `[To confirm]`); Document AI for GAD 30/2019 and the 227 scans; then upload

### 2026-11-12 · P0-P5 / M2 · Review decisions, confirmed OCR text and audit trail in Cloud SQL (plan §3.5, §4.2, §10.4)
- **Status:** DONE (tables created on `c2-sql` 12 Nov 2026 15:34 IST, owner run)
- **Cloud SQL created (owner, 05_cloudsql.sh):** `c2-sql`, PostgreSQL 16, db-g1-small, `asia-south1-c`, database `c2`, IAM users `c2-api`, `c2-ingest` and the developer. No passwords
- **Implemented:**
  - `data/schemas/postgres/0001_review_audit.sql`: `schema_migrations`, `review_items` (one row per kind/subject/version; a decided row must have reviewer + time + reason, enforced by CHECK), `confirmed_texts`, `audit_events` (IDs only; a trigger refuses UPDATE/DELETE). Idempotent;
  - `app/pg.py`: one connection behind a lock, one transaction per call, rollback + re-raise on error (fail closed). Local/test via `C2_PG_DSN` (psycopg); Cloud SQL via the connector with IAM auth (`C2_CLOUDSQL_INSTANCE`, `C2_CLOUDSQL_USER`; pg8000). Fixed SQL statements only, all values bound;
  - `PostgresReviewQueue`, `PostgresConfirmedText` (`app/hitl/pg_queue.py`), `PostgresAuditLog` (`app/audit/pg_log.py`): same contract as the in-memory classes (same errors, same order of checks, `RV-000001` IDs);
  - settings `C2_STATE_STORE=memory|postgres` (default memory, so the sandbox is unchanged); `create_app` and `AssistRuntime.build` take the Postgres queue / confirmed text / audit when set. `IngestionStores.confirmed_text` is now a `MutableMapping`;
  - `infrastructure/gcp/12_cloudsql_schema.py` (Mac; dry run by default): applies migrations as `postgres` with a one-time random password, grants least privilege (api/ingest: read/write review + confirmed text, insert-only audit; developer: read-only), resets `postgres` to an unseen random password, then checks the developer IAM login
- **Restart behaviour:** re-ingesting at startup re-submits the same (kind, subject, version), gets the stored decided item back, and `blocks()` is false, so a file confirmed before a restart is indexed again without asking anyone
- **Tests run:** `ruff check .` clean, `ruff format --check` clean, `mypy` 135 files clean; `pytest -q` with `C2_TEST_PG_DSN` set to a local PostgreSQL 16 → **1290 passed** (7 new in `test_pg_state.py`; the 4 database tests skip when no DSN is set). Extra manual checks against local Postgres: the same classes over pg8000 (the Cloud SQL driver); the script's grants with roles named like the IAM users: api role can submit/decide/audit but DELETE on review_items, UPDATE on audit_events and DROP TABLE are refused; developer can read, cannot write
- **Security/correctness:** audit holds IDs and outcomes only; append-only at two levels (trigger + no UPDATE/DELETE grant). No password stored anywhere. Confirmed text is application data in Cloud SQL, never in logs
- **Known gaps:**
  - a scan confirmed **without** corrections keeps no text in Postgres: at restart it needs its OCR draft again, which comes from the OCR cache on local disk. On Cloud Run that disk is gone, so the cache must move to GCS (or the merged text be stored at confirm time) before the backend runs there;
  - `data/schemas/authz.sql` (authz tuples) is still not applied; it moves to `data/schemas/postgres/` as migration 0002 when the access store goes to Postgres;
  - one connection per process (fine for the PoC; a pool when Cloud Run concurrency needs it)
- **Live run (owner, 15:34 IST):** `+ applied 0001_review_audit`, `+ 12 grants`, `+ postgres password reset to an unseen random value`; check as `venkat.c@techbharat.ai` over IAM auth → migrations `['0001_review_audit']`, review_items 0, audit_events 0. Two earlier attempts changed nothing:
  - the random password could start with `-`, which gcloud read as a flag. Fixed: letters and digits only, passed as `--password=…`, and gcloud's error is shown with the password masked;
  - the gcloud login had expired (reauth cannot prompt inside a script). The owner ran `gcloud auth login` + `gcloud auth application-default login`
- **Exact next action:** the app runs with Postgres state only when `C2_STATE_STORE=postgres` is set (first on Cloud Run with `c2-api`, which still needs its IAM roles from the CoE). The OCR-cache gap above comes before that

### 2026-11-12 · Data workstream / M2 · Full collection 2016–2025 (done): 1,126 orders
- **Source re-check (owner, 09:34):** GOIR still `Disallow: /`; the code was checked and robots.txt is parsed correctly. No circumvention (UA spoofing or proxies refused). Routes: Internet Archive mirror (bulk), hand downloads, or permission via the CoE
- **Full run started (owner, 09:38):** `FULL=1 run_batches.sh` from the Internet Archive mirror, log `~/Documents/c2-24-corpus/logs/full_run_2026-11-12.log`. FIN01 2025: seen 1,851, kept 14 (type 1,783, topic 54 skipped)
- **Owner decisions (09:40):**
  - **start date widened to 2016** (`scope.yaml from_date: 2016-01-01`; `run_batches.sh` years now 2025…2016, overridable with `YEARS=`; the script was swapped by `os.replace`, so the running copy was untouched). The 2016–2017 pass runs after the current one;
  - **stop at 2025 for now:** the mirror ends 12 Dec 2025 and GOIR blocks crawlers;
  - **as-of date stays 31-12-2025.** Current status is never claimed past the date the corpus is complete for
- **Network cut (owner, ~10:30–11:00 IST):** the run ended at 11:00 IST without finishing. From GAD01 2025 onwards, every request failed with `SSLCertVerificationError: EE certificate key too weak`, which looks like a network that intercepts TLS (e.g. a captive portal while reconnecting). The script then ran through the remaining years and finished early
  - **collected before the cut:** FIN01 complete for 2018–2025 (241 + 131 cited); GAD01 29 from the 2025 main pass + some cited; ESE01 0;
  - **total 401 orders** (FIN01 361, GAD01 40), 1,582 candidate edges. Coverage: SUPERSEDES 13 / AMENDS 12 with both ends held; 42 DA/DR orders; 2 records for review. Gaps (expected): memos, rules/Acts, 2026, synthetic parts
- **Fix in `run_batches.sh` (network guard):**
  - before each collector step it waits until archive.org answers with a valid certificate (checking every 60 s, giving up after 60 min with exit 2);
  - a failed step is retried once after the network is back;
  - resuming is safe, because collected orders are skipped.

  The script was swapped atomically
- **Resumed and finished (owner ran the resume, 12 Nov, done 16:49 IST):** log `resume_2026-11-12.log`. GAD01 + ESE01 2016–2025 and FIN01 2016–2017, each with depth-1 cited orders. No network stop after the guard was added
- **Result (audit_corpus.py + check_coverage, 19:15 IST):**
  - **1,126 orders** (FIN01 507, GAD01 380, ESE01 239): 1,074 G.O.(Ms) + 52 G.O.(Rt, only when cited). In scope 2016–2025 by topic: FIN01 329, GAD01 279, ESE01 194; the rest are cited older orders;
  - 899 PDFs with a text layer, 227 scans only (page locations need Document AI); 1,123 with usable OCR text; 7 with Telugu;
  - relations: 3,585 REFERENCES, 113 AMENDS, 36 SUPERSEDES, 4 REPEALS. 1,612 resolve inside the corpus; 556 point to 361 orders we don't hold; 1,570 can't be resolved (other departments, letters, memos);
  - conflict material: 20 SUPERSEDES and 78 AMENDS links with both ends held; 45 DA/DR rate orders (type F);
  - gaps (expected): Rules/Acts/Gazette (type G), memos/circulars (type C), 2026 orders, synthetic e-Office parts
- **Problems found (audit, not yet fixed):**
  - 14 printed header dates differ from metadata;
  - 10 orders whose own number is not on page 1 of the OCR;
  - 3 with too little text and 2 unreadable: these need Document AI;
  - 8 records in `_review/`: 6 listed in the mirror without a PDF, 1 confidential (subject "CONFIDENTIAL", no document), and 1 duplicate ID (AP-FIN01-GOMS-126-2023 claimed by two items, ADR-0007);
  - 2 failed downloads in `failed.jsonl` (one during the network cut, one HTTP 500)
- **Hand-download list:** `~/Documents/c2-24-corpus/logs/hand_download_list_2026-11-12.csv`, 366 rows by tier:
  - tier 1 (28): FIN/GAD/ESE G.O.(Ms) 2016–2025 we lack, including the 6 listed without a PDF;
  - tier 2 (12): older orders that an in-scope order supersedes or amends;
  - tier 3 (149): older orders cited by in-scope orders;
  - tier 4 (177): the rest.

  Numbers ≥1000 are flagged "[check]" (they may be G.O.Rt or misread); never guessed. The confidential order is excluded. GOIR is still `Disallow: /` (owner check 16:15): hand downloads only
- **Status:** DONE for the automated collection
- **Owner decision (12 Nov, 21:07 IST): G.O. number from the GOIR listing when the order doesn't print it.** Applied to the 8 orders where page 1 shows no readable number: AP-FIN01-GOMS-230-2008, -53-2016, -73-2024; AP-GAD01-GOMS-101-2021, -138-2021, -146-2021, -48-2022, -98-2022. Most print "G.O.Ms.No. ____ Dated:" (number stamped later); 73-2024 is a Telugu Gazette scan with unreadable OCR. Each `meta.json` now has `number_source: "registry"` + a note; `audit_corpus.py` counts them separately (8) instead of as problems. To re-check after Document AI OCR
  - **AP-GAD01-GORT-1018-2023:** owner checked the PDF (21:17 IST); it prints "G.O. Rt.No.1018", and the OCR dropped the last digit. Recorded as `number_verified`; the audit counts it as checked
  - **AP-GAD01-GOMS-9-2025:** a "Confidential" placeholder with no order text. Owner: leave it as it is (not moved). The audit keeps listing it
- **Issue dates checked against the PDFs (owner request, 12 Nov 21:22 IST).** The 14 "header date ≠ metadata" flags were checked on the page-1 images (by Claude, recorded as `date_checked_by`):
  - **8 real differences: the printed date is used** (via `reconcile_dates.py --verify … --as printed`; the listing date is kept as `archive_date`):
    - FIN01: GOMS-25-2020 → 28-03-2020; GOMS-28-2020 → 06-04-2020; GOMS-57-2020 → 02-07-2020; GOMS-118-2023 → 31-10-2023; GOMS-84-2024 → 30-08-2024;
    - GAD01: GOMS-95-2021 → 02-09-2021; GOMS-95-2022 → 26-09-2022; GOMS-1-2024 → 08-01-2024.

    No year changed, so no canonical ID or folder changed. The assumed `effective_from` follows the date;
  - **6 false alarms: the record was already right.** The audit had read a date from a G.O. cited in the subject or reference list, not from the order's own line: FIN01 GOMS-126-2016, 127-2016; GAD01 GOMS-123-2020, 146-2021, 87-2021, 97-2021. 126-2016 and 146-2021 are marked verified as recorded. 146-2021 also prints its number (G.O.Ms.No.146), so it moved from "registry number" to "checked on the PDF";
  - **tool fixes (data_collection/tools):**
    - `audit_corpus.py` compares only the order's own G.O. line (same number) and counts verified dates;
    - `reconcile_dates.py --verify` now also moves an assumed `effective_from`;
    - `reconcile_dates.py --write` was run once over the whole corpus: 991 printed = listing date, 126 printed date unreadable (listing date kept), 9 mismatches → now all decided;
- **Remaining text problems cross-checked (owner request, 12 Nov 21:33 IST)**, on the page-1 images and the PDF text layers:
  - **FIN GOMS-121-2017:** a clean digital PDF, but `ocr.txt` was empty. Rebuilt from the PDF text layer (11k chars); No.121, dated 18.07.2017, matches;
  - **FIN GOMS-73-2024:** page 1 is a clean English G.O. (No.73, dated 31.07.2024). The old text was unreadable OCR of the attached Telugu Gazette pages. Rebuilt from the text layer; the number is now printed + checked (was "registry");
  - **GAD GOMS-17-2023:** the archived PDF is an empty page (2 KB). Marked `document_missing` and added to tier 1 of the hand-download list (now 29);
  - **GAD GOMS-30-2019:** a Telugu G.O., No.30, dated 06.03.2019 (matches). Its text layer uses a legacy Telugu font mapping, so the text is garbled. Marked `ocr_status: needs_documentai`;
  - **GAD GOMS-9-2025:** tagged confidential (`classification: CONFIDENTIAL`, mock level, + `withheld`). Number and date are corroborated by GAD G.O.Ms.No.27/2025, which cites "G.O.Ms. No. 9, G.A. (Poll.A) Dept., dated: 11.01.2025". FIN GOMS-134-2016 (in `_review/`) is tagged the same way;
  - old text kept as `ocr.archive.txt` (nothing deleted). The audit counts withheld / missing separately. Only open problem: 30-2019, waiting for Document AI. `validate.py` still fails 17-2023 and 9-2025 (no text), as expected
  - **audit now:** no date problems. Left: 3 short-text and 2 unreadable OCR (Document AI), and G.O.Ms.No.9/2025 (confidential, left as is). Note: AP-GAD01-GOMS-97-2021 prints "Office Order (Ms).No.97", not a G.O.: its type is to be checked
- **Exact next action:** owner downloads tier 1 + 2 by hand (GOIR in a browser, AP Finance, APUTF) and registers them with `add_manual.py`. Upload with `08_upload_public_corpus.sh` can run now (additive, never deletes) or after

### 2026-11-11 · Data workstream / M2 · Old public corpus archived; fresh collection prepared. Cloud SQL sized (owner OK)
- **Status:** IN_PROGRESS. The archive is DONE; the collection and Cloud SQL creation are the owner's next commands (Mac)
- **Plan section:** plan doc "Data collection, end to end", steps 1–3; §3.5 (Cloud SQL); ADR-0006
- **Archive (owner go-ahead, 22:42):** moved, not deleted, from `~/Documents/c2-24-data-tools/{staging,seed,logs,inbox}` to `~/Documents/c2-24-data-tools/archive/2026-11-11/`
  - **636 MB, 2,931 files, 831 orders with meta.json:** staging 632 MB / 2,754 files; seed 3.6 MB / 170; logs 508 KB / 6; inbox 1
- **New data root:** `~/Documents/c2-24-corpus/` (empty staging, seed, logs, inbox + README). `data_collection/local.env` now points there (git-ignored)
- **Source re-check and collection:** they must run in the owner's Mac Terminal, because the linked VM cannot reach goir.ap.gov.in or archive.org. Crawl delays (≥10 s) make the full run several hours, so it runs under `caffeinate` + `nohup`
- **Cloud SQL (owner OK on idle cost):** `05_cloudsql.sh` now uses shared-core `db-g1-small` (about US$31/month in asia-south1 + 10 GB storage; third-party price list, no SLA on shared core) with `TIER=` override, `--deletion-protection` and `--storage-auto-increase`. It adds the developer's own IAM user (no passwords anywhere)
- **Source check run (owner, 22:52):** GOIR robots.txt is now `Disallow: /` (it allowed all on 18 Oct, when 1 order, G.O.Ms.No.19/2024 FIN01, was fetched directly and lawfully). The other sources are unchanged. Recorded in `docs/data_collection/source_check.md` and LEARNINGS
- **Owner decision (22:59):** the full collection is **postponed to the morning of 12 Nov**. Re-run `check_robots.py` first. If GOIR allows crawling again, include it; if not, run the Internet Archive collection and list GOIR-only gaps for hand download
- **Exact next action (12 Nov morning):** `check_robots.py` → full collection. Meanwhile: `I_ACCEPT_COST=1 APPLY=1 ./05_cloudsql.sh` (owner OK) and the Postgres-backed review queue + audit log (same interfaces)

### 2026-11-11 · P0-P1 / M2 · Cloud Storage document store (ADR-0014 rule 7)
- **Status:** DONE (verified live, 11 Nov 2026 22:31)
- **Plan section:** §3.5, §4.6; ADR-0014 rules 2, 3, 7
- **What:**
  - `GcsDocumentStore`: private raw bucket; one object per version under `synthetic/mock_v1/sources/<sha256>/<hash>/<pipeline>`;
  - written once (`if_generation_match=0`), never overwritten, and the bucket keeps versions;
  - media type and version stored on the object;
  - errors carry the type only;
  - the SDK is loaded lazily;
  - `C2_DOCUMENT_STORE` memory|gcs, `C2_GCS_RAW_BUCKET`, prefix `C2_GCS_DOCUMENTS_PREFIX` (default synthetic/mock_v1/sources);
  - the runtime takes the store from settings (sandbox default unchanged: memory)
- **Files changed:**
  - `backend/app/ingestion/document_store.py`, `backend/app/config.py`, `backend/app/agents/runtime.py`, `backend/app/main.py`;
  - new `backend/tests/unit/test_document_store_gcs.py` (3, fake bucket with the SDK's own exception types);
  - `.env.example` (Mac);
  - new `infrastructure/gcp/11_document_store_check.py` (live: sandbox app on GCS, preview as U01 compared with the corpus file, hidden document still 404, objects listed)
- **Tests/commands run:** ruff ✅ · mypy strict (131 files) ✅ · `pytest -q` **1283 passed** ✅
- **Security:** bytes are served only after `can_access` (unchanged path). The store has no access logic; the prefix keeps synthetic data apart from real files
- **Live evidence (owner's Mac, `11_document_store_check.py`):**
  - preview of `AP-FIN01-GOMS-88-2022` as U01: HTTP 200, 43,589 bytes, **byte-identical** to the corpus file, served from GCS;
  - hidden document `AP-USD01-RPT-USD0131-9-2025` for U05: **404**;
  - **21 objects** under `gs://use-case-24-project-c2-raw/synthetic/mock_v1/sources/` (the 21 indexed native files; OCR'd scans are stored only after review), with the correct media types
- **Exact next action:** Cloud SQL (bills while idle; IAM DB auth needs the SA roles) or the Vertex AI Search data store (L2). Owner to choose; SA role grants are still pending the CoE admin

### 2026-11-11 · P5 / M6 · OCR review screen (human review of OCR drafts) in the sandbox (ADR-0018)
- **Status:** DONE (sandbox). Who may confirm OCR in the department is [To confirm]
- **Plan section:** §4.2, §9.1 checkpoint 5, §11; CLAUDE.md §4.7, §8; ADR-0014 rule 4, ADR-0016
- **What:**
  - a new "OCR review" screen shows the scan beside the OCR text (whole document, as it would be indexed), with per-page confidence and languages;
  - the reviewer confirms, confirms corrected text, or rejects for a re-scan; a reason is required;
  - the queue lists only scans the officer may open; a hidden item answers like an unknown one;
  - confirm re-runs the pipeline (indexed only if every check passes, under the scan's own version);
  - the sandbox replays recorded Document AI v2.1.1 output (`sandbox.yaml ocr.provider: recorded`)
- **Files changed:**
  - backend: `app/agents/routes.py` (5 endpoints), `app/agents/runtime.py` (`review_ocr`, artefacts kept, accounting), `app/ingestion/pipeline.py` (`review_text`), `app/auth/messages.py` (`REVIEW_ITEM_NOT_AVAILABLE`), `app/main.py` (`sandbox_ocr`), `config/sandbox.yaml`, new `tests/unit/test_ocr_review_api.py` (8)
  - frontend: new `components/OcrReview.tsx`, `TopBar.tsx`, `App.tsx`, `api.ts`, `types.ts`, `styles.css`, `render.test.tsx` (+2), `api.test.ts` (+1)
  - docs: new ADR-0018, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** ruff ✅ · mypy strict (130 files) ✅ · `pytest -q` **1280 passed** ✅ · frontend tsc ✅, Vitest **29** ✅, build ✅. Playwright, U03 (Works SO): the queue shows D01, D02, D09, D13, D15, D16; on D16 the reviewer corrected the Rc. No. line, and the file was indexed as `AP-USD01-RC-USD01WRKS0-22-2025-D20250602`; no console errors
- **Acceptance evidence:**
  - every officer's queue equals exactly the scans the access matrix allows;
  - a hidden item (D22 for U01) is byte-identical to an unknown item on view, scan, confirm and reject, and nothing is decided;
  - D09 confirmed → indexed `AP-GAD01-GOMS-19-2018`, and preview serves the scan;
  - D16 unchanged → still held (unresolved_reference); D16 corrected → indexed;
  - reject → stays out of the index;
  - audit records IDs only
- **Security implications:** a new disclosure path (the review queue and the scan) under the same check, with 404 parity; no OCR text in logs
- **Known gaps:**
  - the reviewer group is not narrowed (department to confirm);
  - reviews live in memory (lost on restart) until Cloud SQL;
  - headless Chromium lacks a Telugu font, so the Mac system fonts are listed as fallback
- **Exact next action:** owner try-out on the Mac (`make run` + `make fe-dev`, sign in as Works SO, open "OCR review"). Then the GCP build-out

### 2026-11-11 · P7 / M8 · Evaluation on real OCR (Document AI v2.1.1, recorded) instead of hand transcriptions
- **Status:** DONE
- **Plan section:** §13 (evaluation), §4.2 (review path); CLAUDE.md §9.5
- **What:**
  - `run_eval.py --ocr-recorded <version>`: held scans are read from the recorded Document AI responses (no GCP calls) and confirmed by a **simulated** reviewer through the production `confirm_extraction`, with no corrections. Hand transcriptions are not used;
  - a scan whose OCR text fails a pipeline check stays held, as in the app;
  - the TP04 replay uses the same mode;
  - the report header states the mode and lists the scans indexed from OCR
- **Files changed:** `evaluation/harness/stack.py`, `evaluation/harness/suites.py`, `evaluation/run_eval.py`, `backend/tests/unit/test_ocr_eval.py` (+1), report `2026-11-11-ocr-v2.1.1`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Result vs `2026-11-11-baseline` (transcriptions):**
  - indexed from OCR: D01, D02, D09, D11, D13, D15, D22; held: D16 (unresolved reference, marker misread);
  - **touchpoints 17/17**, opposites 20/20, leakage **0/1126** (16 fewer checks because D16 is not indexed);
  - recall@5/@10 0.706/0.754, MRR 0.833, ladder 0.684, A/C/E/F P/R 1.0, clean-control false flags 0: all unchanged;
  - NDCG@10 0.714 → 0.711
- **Tests/commands run:** ruff ✅ · mypy strict (129 files) ✅ · `pytest -q` **1272 passed** ✅ · `run_eval.py --ocr-recorded pretrained-ocr-v2.1.1-2025-01-31 --compare …baseline.json` ✅
- **Security / correctness:** the leakage bar holds on OCR'd text; no ground truth feeds the stack in this mode
- **Known gaps:**
  - the simulated reviewer accepts every draft. A real reviewer would correct D16's marker. The HITL review screen (P5) is still to build;
  - the 4 touchpoints that used to fail without OCR now pass on real OCR
- **Exact next action:** reviewer screen for OCR drafts (P5, HITL), or continue the GCP build-out (P0/P1: upload the corpus to the raw bucket once the new collection is ready; IAM roles still pending the admin)

### 2026-11-11 · P1 / M2 · First live Document AI run on the synthetic scans: findings and fixes
- **Status:** DONE for English scans. BLOCKED on the Telugu photo D16 (investigation script ready)
- **Plan section:** §4.1, §4.2, §4.3, §13 (OCR accuracy); CLAUDE.md §9.5 (regression run)
- **Run (owner's Mac):** `ocr_scans.py --live`. 9 pages over 8 files, processor `c2-ocr`, asia-south1. Responses cached in `data/synthetic/mock_v1/ocr/documentai/` (images stripped: 11 MB → 1.5 MB)
- **First report** (`2026-11-11-ocr-documentai`): ID recovered 2/8, mean WER 0.46. Diagnosis:
  - **(1) Bug in our metadata extraction, not OCR.** Document AI reads a two-column header as separate lines, with the number and "Dated:" in either order (D01, D02, D09, D13). `_OWN_GO` / `_OWN_MEMO` needed them on one line. Fix: `_join_split_header` rejoins a number-only line with an adjacent date-only line (blank lines allowed, either order), used only to find the own reference. A date further away is never joined (no guessing)
  - **(2) WER overstated errors.** It counted text the transcription leaves out (signature block, distribution list, footer) and dash and spacing variants. Added word recall (reference words recovered, in order) and normalised dashes and "Dt. 17" spacing. Notes are now identified by e-File number (D22)
  - **(3) D16, the Telugu photo:** read as Latin-script noise (confidence 0.51, recall 0.04, languages en/is/jv/lt…), although the photo is clean and Google lists Telugu as supported. The confidence gate would hold it anyway. Open
- **After the fixes** (`2026-11-11-ocr-documentai-2`, replay of the same responses, no new cost): identity recovered **7/8**, mean word recall **0.842** (English scans 0.917–1.0; D15 table 0.863), page confidence 0.963–0.984 on English, 0.508 on D16
- **Files changed:**
  - `backend/app/ingestion/metadata.py` (`_join_split_header`)
  - `backend/app/ingestion/ocr.py` (cache drops page images)
  - `evaluation/ocr_scans.py` (recall, identity, normalisation)
  - new `evaluation/ocr_telugu_probe.py`
  - tests: `test_ingestion_extract_metadata.py` (+5), `test_ocr_eval.py` (+2, including a regression on the recorded Document AI output)
  - OCR cache (8 JSON files)
  - reports: `2026-11-11-ocr-documentai-2`, `2026-11-11-baseline`
- **Tests/commands run:** ruff ✅ · mypy strict (129 files) ✅ · `pytest -q` **1267 passed** ✅ · `run_eval.py` regression (metadata changed) → leakage 0/1142, recall@10 0.754, MRR 0.833, ladder 0.684, A/C/E/F P/R 1.0: **unchanged**
- **Decision needed (owner):** calibrate `extraction_confidence_min`? Evidence: English pages 0.96–0.98 with recall ≥ 0.92; the failed Telugu page 0.51. Not changed; stays null until approved
- **Telugu probe (`2026-11-11-ocr-telugu-probe`), D16 on `c2-ocr`:**
  - default version = Google Stable `pretrained-ocr-v1.0-2020-09-23`: Latin noise (conf 0.51, recall 0.04) with no hint, te, or te+en;
  - `pretrained-ocr-v2.1.1-2025-01-31` (Google Release Candidate): **conf 0.97, recall 0.98**, languages te/en.

  Cause: the processor default is the 2020 model, not the hints
- **Fix:**
  - OCR model version pinned by config (`C2_DOCAI_OCR_PROCESSOR_VERSION`, sent as `processorVersions/<v>`);
  - responses cached per version (`ocr/documentai/<version>/`; the first run moved to `pretrained-ocr-v1.0-2020-09-23/`);
  - ADR-0017 point 4 (proposed: pin v2.1.1);
  - `.env.example`;
  - +1 test (1268 passed, ruff and mypy clean)
- **v2.1.1 full run (owner, 21:43):** better recall (0.959 vs 0.842) and higher confidence (0.974–0.989), but IDs fell to 4/8. v2.1.1 emits the right-column "Dated:" several lines after the number (after "Read the following", or between "Sub:" fragments), beyond `_join_split_header`'s reach
- **Fix: rows rebuilt from line geometry** (`ocr._rows_text`). Lines whose vertical centres lie within half a median line height form one row, read left to right; the text order is the fallback when there is no geometry. Replay of both recorded runs (no new cost):
  - **v1.0:** 7/8 IDs, recall 0.841;
  - **v2.1.1:** **7/8 IDs, recall 0.960**, D16 Telugu recall 0.978.

  D16 stays unresolved under v2.1.1: the body is read, but the marker ఆర్.సి.నెం. is misread as "5.2.3.", so the ID is never guessed and the file goes to review (UNRESOLVED_REFERENCE)
- Reports: `2026-11-11-ocr-documentai-pretrained-ocr-v2.1.1-2025-01-31-2`, `…-v1.0-2020-09-23` (replays). Tests +3 → **1271 passed**; ruff and mypy clean
- **Decisions needed (owner):**
  - (1) pin OCR v2.1.1 (ADR-0017 point 4)? The evidence favours it: better on English, and the only model that reads Telugu;
  - (2) set `extraction_confidence_min`? Pages that read correctly scored 0.96–0.99, the unreadable Telugu page 0.51. Stays null until approved
- **Owner decisions (11 Nov 2026, 21:5x):**
  - (1) **pin OCR v2.1.1:** accepted. It is now the code default (`C2_DOCAI_OCR_PROCESSOR_VERSION`), and ADR-0017 point 4 is accepted;
  - (2) **gate threshold stays null:** every OCR page waits for a reviewer until real department scans give enough evidence
- **Exact next action:** the evaluation stack uses recorded v2.1.1 OCR plus the reviewer-confirmation path in place of hand transcriptions

### 2026-11-11 · P1 / M2 · Document AI OCR in the ingestion pipeline, with reviewer confirmation
- **Status:** IN_PROGRESS. The code is DONE and tested offline. The first live OCR run on the 8 synthetic scans is the owner's next command (Mac, billed per page)
- **Plan section:** §4.1 (routing, OCR), §4.2 (confidence gate and human review), §9.1, §13 (OCR accuracy suite); ADR-0017
- **Files changed:**
  - new `backend/app/ingestion/ocr.py`:
    - `OcrEngine` interface;
    - `DocumentAiOcr` (region-pinned endpoint, page selector, te/en language hints, online limit 15 pages, lazy SDK import, errors carry the type only);
    - `parse_document` (Document AI JSON → per-page text, length-weighted confidence, languages, paragraphs);
    - `CachingOcr` (on-disk cache by sha256: each file is billed once);
    - `RecordedOcr` (replay only);
    - `ocr_from_settings` (fails closed on bad config)
  - `backend/app/ingestion/pipeline.py`:
    - OCR runs only on `NEEDS_OCR` pages, and the draft is stored by version;
    - an OCR failure holds the file with an "OCR failed" review item;
    - the gate uses the OCR confidence;
    - new `confirm_extraction`: reviewer confirms or corrects, the decision is recorded, and the file is re-run with `after_review` and indexed under the scan's own version;
    - `text_of` keeps the indexed text
  - `backend/app/agents/runtime.py`: `ocr` engine; indexed text comes from the pipeline
  - `backend/app/config.py`: `C2_OCR_PROVIDER` none/documentai/recorded, `C2_DOCAI_LOCATION`, `C2_DOCAI_OCR_PROCESSOR_ID`, `C2_OCR_LANGUAGE_HINTS`, `C2_OCR_RECORDED_DIR`
  - `backend/app/main.py`
  - `.env.example`
  - new `evaluation/ocr_scans.py` (OCR accuracy suite: WER, character similarity, canonical ID recovered from OCR text, per-page confidence; cache-only unless `--live`)
  - new `backend/tests/unit/test_ocr.py` (18 tests) and `test_ocr_eval.py` (2 tests)
  - `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** `ruff check . ../evaluation` ✅ · `ruff format` ✅ · `mypy` strict (128 files) ✅ · `pytest -q` **1260 passed** ✅. `evaluation/ocr_scans.py` (cache only, no cache yet) lists the 8 scans needing OCR (D01, D02, D09, D11, D13, D15 p.2, D16, D22), all "not run"
- **Acceptance evidence (offline; fake client and engine, labelled):**
  - the request goes to the asia-south1 processor path with page selection and te/en hints;
  - an uncalibrated gate holds the OCR draft for review; reviewer confirmation indexes it under the scan's version, with reviewer, time and reason recorded on the item;
  - a correction is what gets indexed;
  - a mixed PDF merges native page 1 with OCR page 2 in order;
  - an OCR failure holds the file with no draft;
  - no engine confidence → never trusted;
  - each file is billed once (cache)
- **Security / correctness implications:**
  - OCR text is never indexed without a confirmed review while `extraction_confidence_min` is null (unchanged, CLAUDE.md §5.3);
  - errors never carry document text;
  - the cached responses are synthetic-corpus only;
  - with no OCR configured, sandbox behaviour is unchanged (C2_OCR_PROVIDER defaults to none)
- **Known gaps:**
  - no reviewer screen yet (HITL UI, P5), so `confirm_extraction` is reachable from code and evaluation only;
  - batch OCR (>15 pages) not built;
  - the evaluation stack still uses hand transcriptions as the "confirmed text" stand-in. Switching it to recorded Document AI output plus confirmation comes after the first live run
- **Exact next action:** owner runs `uv sync --extra gcp`, then `ocr_scans.py --live` on the Mac. Review WER, ID recovery and confidence, then decide whether to calibrate the gate (owner approval) and whether to use recorded OCR in the evaluation stack

### 2026-11-11 · P0 / M1 · GCP access day: project checked, APIs on, empty foundations created
- **Status:** IN_PROGRESS. Service-account roles are blocked on Project IAM Admin; Cloud SQL and Spanner are deferred (they bill while idle)
- **Plan section:** §3.5, §14.6; CLAUDE.md §2.2
- **Where:** owner's Mac Terminal (`gcloud` 593.0.0). This workspace and the linked VM cannot reach googleapis
- **Files changed (repo):** new `infrastructure/gcp/00_access_check.sh` (read-only; no prompts), new `infrastructure/gcp/09_regional_checks.sh` (read-only, no cost: Document AI types and Gemini `countTokens` in the region; model IDs discovered from Model Garden), new `infrastructure/gcp/10_documentai.sh`, new `docs/decisions/0017-region-and-gemini-model.md`, `01_apis.sh` (+ orgpolicy API), `02_service_accounts.sh` (`SKIP_ROLES=1` / `ROLES_ONLY=1`), `infrastructure/gcp/README.md` (step 0; 08 corpus upload deferred), `.gitignore` (config.env and *.out.txt), `docs/LEARNINGS.md`, `PROGRESS.md`
- **Evidence (`verify.sh` → `verify.out.txt`, `access_check.out.txt`, both local and git-ignored):**
  - project `use-case-24-project`: ACTIVE, billing enabled, account `venkat.c@techbharat.ai` with `roles/editor`;
  - 17 PoC APIs enabled (52 services on in total);
  - org policies: no location restriction, and SA key creation not blocked (none created);
  - buckets `use-case-24-project-c2-raw` and `-c2-artifacts` (asia-south1, uniform access, public-access prevention, versioning);
  - BigQuery `c2_metadata` and `c2_audit` (asia-south1);
  - Artifact Registry `c2` (docker, asia-south1);
  - SAs `c2-api`, `c2-ingest` and `c2-frontend`, with no roles yet;
  - no Cloud SQL, no Spanner
- **Security implications:** no SA keys, buckets private, SAs hold no permissions yet
- **Blocker / decision needed:**
  - CoE admin to grant Project IAM Admin, or to run `ROLES_ONLY=1 APPLY=1 ./02_service_accounts.sh` and the `c2_audit` dataEditor grant;
  - CoE to confirm the data-residency region (asia-south1 is in use; the empty resources can be recreated)
- **Regional checks (`regional_checks.out.txt`):** Document AI in asia-south1 offers OCR, Layout Parser and Form Parser. Gemini in asia-south1: only `gemini-3.5-flash` and `gemini-3.5-flash-lite` answer (countTokens 200 of 38 IDs). See ADR-0017 (Proposed)
- **Document AI:** OCR processor `c2-ocr` (`93ce7a373c394aed`) created in asia-south1, ENABLED. Layout Parser creation failed: us/eu only, although it is listed for asia-south1. Locators will come from OCR output; the script has been updated
- **Exact next action:** the backend Document AI extractor behind the ingestion interface (config: processor ID and region), run on the 8 held scans (unlocks the 4 OCR-dependent touchpoint scenarios)

### 2026-11-11 · P8 / M9 · Guiding message for records an officer cannot get (ADR-0016)
- **Status:** DONE
- **Plan section:** §5.4, §5.9, §13.3 (plan text updated in §5.4 and §5.9 with owner approval)
- **Files changed:** new `backend/app/auth/messages.py`, `backend/app/agents/routes.py`, `backend/app/eoffice_mock/routes.py`, `backend/tests/unit/test_sandbox_api.py`, `frontend/eoffice/src/components/Citations.tsx`, `frontend/eoffice/src/api.test.ts`, `frontend/eoffice/src/render.test.tsx`, `IMPLEMENTATION_PLAN.md`, new `docs/decisions/0016-guiding-message-for-unavailable-records.md`, ADR-0014/0015 wording notes, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Owner request vs rule:** the owner asked for "you are not authorised for this file, get approval". This conflicts with CLAUDE.md §4.7, because it confirms the file exists. The conflict and three options were put to the owner, who chose one guiding message for hidden and non-existent records
- **Tests/commands run:** `ruff check .` ✅ · `mypy` strict (124 files) ✅ · `pytest -q` **1238 passed** ✅ · opposites **20/20** ✅ · frontend `tsc` ✅ · Vitest **26** ✅ · build ✅
- **Acceptance evidence:** a hidden file (2894562 for U03) and a hidden document give a 404 byte-identical to the unknown ones, carrying the guidance, with no "restricted / not authorised / classified" words. The not-found highlight tooltip shows the same guidance
- **Security implications:** none weakened; the leakage bar is unchanged (0)
- **Blocker / decision needed:** department to confirm the "competent authority" wording and the access-request route
- **Exact next action:** owner review; continue the GCP setup plan

### 2026-11-10 · P8 / M9 · Citation highlights in notes + document preview / download (ADR-0014, ADR-0015)
- **Status:** DONE (sandbox scope). Cloud Storage implementation waits for GCP; "open at cited page" waits for page locators
- **Plan section:** §3.5, §4.6, §5.2, §5.4, §6.2, §8.2, §11.5 (touchpoints 10–11), §13.3
- **Files changed:** new `backend/app/ingestion/document_store.py`, new `backend/app/conflict/highlights.py`, `backend/app/ingestion/metadata.py` (`citation_spans`), `backend/app/agents/runtime.py` (stores source bytes + cid → version at ingest), `backend/app/agents/routes.py` (`POST /assist/highlights`, `GET /assist/documents/{id}` + `/preview` + `/download`), new `backend/tests/unit/test_highlights.py`, `backend/tests/unit/test_sandbox_api.py` (+9 tests), `evaluation/harness/opposites.py` (`same_as_unknown.path` for GETs), `data/synthetic/mock_v1/ground_truth/opposite_scenarios.json` (OPP-16–19), new `frontend/eoffice/src/components/Citations.tsx`, `FilePageView.tsx`, `AssistPanel.tsx`, `App.tsx`, `api.ts`, `types.ts`, `styles.css`, `api.test.ts`, `render.test.tsx`, new `docs/decisions/0015-citation-highlights-in-notes.md`, `docs/decisions/0014-…md` (implementation note), `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** backend `ruff check .` ✅ · `ruff format --check .` ✅ · ruff on `../evaluation` ✅ · `mypy` strict (123 files) ✅ · `pytest -q` **1237 passed** ✅. Opposites harness **20/20** ✅. `run_eval.py --no-write` → leakage 0/1142, recall@10 0.754, MRR 0.833, A/C/E/F P/R 1.0 (unchanged). Frontend `tsc` ✅ · Vitest **26** ✅ · build ✅ · `npm audit` 0 ✅. Playwright against `uvicorn` + Vite: highlights on 2894562 (U01) and 2633187 (U02), click → preview blob `%PDF-` 43,589 bytes, download `AP-FIN01-GOMS-88-2022.pdf`, flag sources open the viewer, no console errors
- **Acceptance evidence:** on 2894562 (U01) 88/2022 is marked *potential conflict* (A) and opens the stored PDF byte-identical to the corpus file; 104/2026 is *not found*, uncertain, not linked. Every hidden (document, officer) pair answers byte-identical to an unknown ID on details/preview/download; crafted note citing every corpus order × every officer × every file → no link or evidence ID outside the access matrix; views/downloads audited with IDs + version only; docx downloads, preview 415
- **Bug found by an opposite written before the run (OPP-19):** the not-found flag named a hidden order by the ID resolved from the note (`AP-USD01-SO-2-2020`); now named only in the note's words; regression test compares a hidden and a non-existent order byte for byte
- **Security / temporal / citation implications:** two new disclosure paths (document file, highlights) under the same checks as every other path; no URL carries access (frontend fetches a Blob with the sign-in header); `no-store`; held (review-queue) records never served. Highlights use today's as-of date (pre-send keeps the note's date)
- **Known gaps:** preview opens at page 1 (no page locator for a cited paragraph yet); headless browser check verified the PDF bytes, not the PDF viewer's rendering; e-File links rely on the e-Office file list; `InMemoryDocumentStore` is the sandbox stand-in — Cloud Storage implementation with GCP
- **Blocker / decision needed:** owner — highlights as of today (current) or as of each note's date; review OPP-16–19 (draft)
- **Exact next action:** owner answers above; then with GCP: `GcsDocumentStore` (private bucket, backend-streamed) behind the same interface

### 2026-11-06 · P7 / M8 · Checkpoint re-run + opposite scenarios
- **Status:** DONE (evaluation only; no app behaviour changed)
- **Plan section:** §13 (evaluation), CLAUDE.md §9.3–§9.5; §4.7 (never confirm existence)
- **Files changed:** new `data/synthetic/mock_v1/ground_truth/opposite_scenarios.json` (16 cases, draft — owner review, each with the corpus fact it rests on), new `evaluation/harness/opposites.py` (runs them through the sandbox HTTP API), `evaluation/run_eval.py` (opposites in every run, report section, headline row; touchpoint sentence no longer says "the rest need P8"), new `backend/tests/unit/test_opposite_harness.py` (10: every kind of opposite check is shown failing on a breaking response), new `evaluation/reports/2026-11-06-checkpoint{,-no-ocr}.{md,json}`, new `evaluation/reports/2026-11-06-checkpoint-review.md`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** backend ruff ✅ · format ✅ · mypy strict (120 files) ✅ · `pytest -q` 1216 passed ✅. Frontend `tsc` ✅ · Vitest 18 ✅ · build ✅ · `npm audit` 0 ✅. `run_eval.py --label checkpoint --compare …2026-11-04-checkpoint.json` and `--label checkpoint-no-ocr --no-ocr-stand-in --compare …2026-11-04-checkpoint-no-ocr.json` → both exit 0 (markdown regenerated from the same JSON after the wording fix)
- **Acceptance evidence:** with the stand-in: leakage 0/1142, retrieval and conflicts unchanged since 4 Nov, **touchpoints 17/17 run and passed**, **opposites 16/16**. Without: leakage 0/1014, touchpoints 13/17 (TP06, TP08, TP13, TP14 need scans), opposites 16/16, clean-control flag now uncertain
- **Expectation revised (recorded in the file):** OPP-11a also expected outcome "clear"; under the coverage rule and mock type-C rules "clear" is unreachable — the run gave no flags and "review needed". Kept: no conflict flagged
- **Security / correctness:** five no-access opposites answer exactly like a record that does not exist; lower-clearance officers never see D20 / Works / Vigilance records on the same file
- **Blocker / decision needed:** owner review of the 16 opposite scenarios (draft)
- **Exact next action:** owner choice — demo script over the 17 touchpoints + opposites, or remaining non-GCP gaps (printed references in drafts; no-answer behaviour)

### 2026-11-06 · P8 / M9 · Touchpoint 6: first-cut note (cited points for a Yellow Note)
- **Status:** DONE (deterministic parts); the note's prose waits for Gemini (labelled in the draft)
- **Plan section:** §11.5 touchpoint 6, §7.5 (every factual line cited), §11.1 (drafts only), owner coverage rule (3 Nov 2026)
- **Files changed:** new `backend/app/agents/first_cut.py` (`first_cut_note`, `ground_of`), `backend/app/agents/dfa.py` (`governing_orders` extracted so the DFA and the first-cut note list the same orders), `backend/app/ingestion/clauses.py` (only paragraphs after an "ORDER:" heading are order paragraphs; whitespace normalised), `backend/app/noting/chain.py` (classification page markings dropped from note paragraphs), `backend/app/agents/routes.py` (`POST /assist/first-cut`), new `backend/tests/unit/test_first_cut.py` (9), `backend/tests/unit/test_local_reference.py` (clause test split: with / without ORDER heading), `backend/tests/unit/test_sandbox_api.py` (TP06 over HTTP; clearance regression + endpoint × officer sweep cover `/assist/first-cut`), `evaluation/harness/suites.py` (TP06 handler), new `evaluation/reports/2026-11-06-first-cut{,-no-ocr}.{md,json}`, frontend `types.ts`, `api.ts`, `components/AssistPanel.tsx` (`FirstCutCard`, "First-cut note", editable text, "Insert as Yellow Note"), `render.test.tsx`
- **What it gives:** orders that apply (same as the DFA list); their paragraphs on ceiling (a %), competent authority, the proposal's ground (from the file subject, "on spouse grounds") and ban / relaxation, quoted verbatim with clause IDs; earlier decisions — Link-File precedents of the same action, the last paragraph of the last note quoted with its date and set against the visible action windows (inside / outside); pre-send flags as open points; "[Note text: to be written by the officer …]" in place of prose
- **Tests/commands run:** backend ruff ✅ · format ✅ · mypy strict (118 files) ✅ · `pytest -q` 1206 passed ✅. Frontend `tsc` ✅ · Vitest 18 passed ✅ · build ✅. `run_eval.py --label first-cut --compare …dfa.json` and `--label first-cut-no-ocr --no-ocr-stand-in --compare …dfa-no-ocr.json` → both exit 0. Browser: U01 opens 2894562 → First-cut note → 31/2025 in place of 88/2022; paras 2(i), 2(iv), 2(v), 2(viii), 3 quoted; 2022 and 2025 approvals inside windows, 2023 rejection outside → Insert as Yellow Note → draft; no console errors
- **Acceptance evidence:** TP06 PASS with the OCR stand-in (D04, D09, D11, D17, D18, D19 cited; D20–D23 absent; no superseded order among those that apply; every quoted line cited; windows as the answer key says; flags = TP11-a). **All 17 touchpoint scenarios now run; 17/17 pass with the stand-in.** Without it 13/17 (TP06, TP08, TP13, TP14 need scans D09/D11/D13). Retrieval and conflict metrics unchanged; leakage 0/1142 and 0/1014
- **Harness note:** the first TP06 run failed on a harness check that counted 88/2022 anywhere among the citations; it is cited legitimately as the source of the 2022 window. The check now applies to the orders that apply (the answer key's "governing rule is 31/2025, not 88/2022"). That run's report was removed before sharing; the report kept is the re-run
- **Security / correctness:** every citation is a record the officer may see (unit test checks each); windows used only from visible orders; precedent decisions quoted, never classified; preview writes nothing, Yellow Note only on click
- **Blocker / decision needed:** none
- **Exact next action:** owner choice — (a) checkpoint re-run of the whole evaluation and a short demo script over the 17 touchpoints, or (b) remaining non-GCP gaps: printed references ("G.O.Ms.No.31, Finance … Dt.12-05-2025") instead of canonical IDs in drafts; no-answer behaviour of the keyword stand-in

### 2026-11-05 · P8 / M9 · Touchpoint 14: draft for approval (DFA), deterministic parts
- **Status:** DONE (deterministic parts); order paragraphs wait for Gemini (labelled in the draft)
- **Plan section:** §11.5 touchpoint 14, §11.1 (drafts only), §3.2 (L1 current-rule template), §6 (supersession), owner coverage rule (3 Nov 2026)
- **Files changed:** new `backend/app/agents/dfa.py` (`draft_for_approval`, `abstract_from_subject`), `backend/app/agents/tools.py` (public scoped helpers: `visible_document`, `visible_facts`, `status_covered`, `current_rule_ladder`), `backend/app/agents/routes.py` (`POST /assist/dfa`; latest-note + pre-send logic shared with `/assist/presend`), new `backend/tests/unit/test_dfa.py` (7), `backend/tests/unit/test_sandbox_api.py` (TP14 over HTTP; clearance regression and the endpoint × officer sweep cover `/assist/dfa`; no sign/send/dispatch/approve/issue endpoint exists), `evaluation/harness/suites.py` (TP14 handler), new `evaluation/reports/2026-11-05-dfa{,-no-ocr}.{md,json}`, frontend `types.ts`, `api.ts`, `components/AssistPanel.tsx` (`DfaCard`, "Draft (DFA)", editable body, "Create DFA draft"), `components/FilePageView.tsx` ("DFA — draft"), `styles.css`, `render.test.tsx`
- **How the "Read the following" list is built:** orders the latest visible note cites + orders in force on the proposal's subject (L1, subject term from the proposal's action: transfer / works / outsourcing); each followed along its supersession chain to the latest order the officer may see; a superseded cited order shows as its successor "in place of …"; not found / repealed / expired / not yet in force → `left_out` with the reason; status not confirmed by coverage → listed with "status not confirmed". Abstract from the file subject. Pre-send flags travel in the body as "Open points"
- **Tests/commands run:** backend ruff ✅ · format ✅ · mypy strict (116 files) ✅ · `pytest -q` 1195 passed ✅. Frontend `tsc` ✅ · Vitest 17 passed ✅ · build ✅. `run_eval.py --label dfa --compare …local-reference.json` and `--label dfa-no-ocr --no-ocr-stand-in --compare …local-reference-no-ocr.json` → both exit 0. Browser: U02 opens 2894562 → Draft (DFA) → 31/2025 "in place of 88/2022", 104/2026 not listed with reason, open points A/E/F/C, caveats → Create DFA draft → "DFA — draft" on the file; no console errors
- **Acceptance evidence:** TP14 PASS with the OCR stand-in: read list D04, D05, D09, D10, D11 (expected D04, D09, D11 ⊆; D21–D23 absent; 88/2022 and 104/2026 not read), flags A/C/E/F = TP11-a. **Touchpoints passed 15 → 16 (with stand-in)**. Without the stand-in TP14 FAILS (D09, D11 are scans awaiting review; the preview says some records are awaiting review) — 13 passed, as before; all other metrics unchanged; leakage 0/1142 and 0/1014
- **Security / correctness:** every listed order passes the officer's own visibility check; supersession followed only through visible orders; preview writes nothing (tested), the draft is created only on click and stays a draft; D05 and D10 are listed beyond the answer key (both transfer rules in force)
- **Blocker / decision needed:** none
- **Exact next action:** TP6 Yellow Note deterministic parts (cited points from the governing order, precedents, flags; prose left to Gemini) — the last core touchpoint not run

### 2026-11-05 · P8 / M9 · Touchpoint 10: local reference with a paragraph
- **Status:** DONE (within the status-coverage rule: "current" is not claimed without full coverage)
- **Plan section:** §11.5 touchpoint 10, §4.4 (clause-level IDs), §6 (supersession facts); owner rule 3 Nov 2026 (TP10/TP11 kept as they are)
- **Files changed:** new `backend/app/ingestion/clauses.py` (`clauses`, `paragraph_label`, `clause_text`; moved out of `temporal/windows.py`, which now imports it), new `backend/app/agents/local_reference.py`, `backend/app/agents/tools.py` (`since` on the status result), `backend/app/agents/routes.py` (`/assist/reference` adds `since`, `paragraph`, `cited_clause`, `successor_clause`, `successor_is_current`, `clause_note`), new `backend/tests/unit/test_local_reference.py` (12), `backend/tests/unit/test_sandbox_api.py` (TP10 over HTTP; sweep also asks every reference with "para 2(v)"), `evaluation/harness/suites.py` (TP10 handler), `evaluation/run_eval.py` (row note), `evaluation/slots_v1.json` (`local_references`), new `evaluation/reports/2026-11-05-local-reference{,-no-ocr}.{md,json}`, frontend `types.ts` (`ClauseText`), `components/AssistPanel.tsx` (`ReferenceCard` shows date and both paragraphs), `styles.css`, `render.test.tsx`
- **Tests/commands run:** backend ruff ✅ · format ✅ · mypy strict (114 files) ✅ · `pytest -q` 1187 passed ✅. Frontend `tsc` ✅ · Vitest 16 passed ✅ · build ✅. `run_eval.py --label local-reference --compare …note-reference.json` and `--label local-reference-no-ocr --no-ocr-stand-in --compare …note-reference-no-ocr.json` → both exit 0. Browser: U01 opens 2894562 → "G.O.Ms.No.88/2022 para 2(v)" → superseded by AP-FIN01-GOMS-31-2025 from 12-05-2025; both paragraphs 2(v) shown; "check it covers the same point"; no "current"; no console errors
- **Acceptance evidence:** TP10 PASS in both runs, with the row noting "current version not claimed (status-coverage rule)" — the scenario's `current_version` is withheld under the owner rule; the expected value is unchanged. **Touchpoints passed 14 → 15 (with stand-in), 12 → 13 (without)**; all other metrics unchanged; leakage 0/1142 and 0/1014; HTTP sweep with paragraph requests → 0
- **Security / correctness:** clause text is read only from the cited order (scoped lookup) and from `by` (always an order the officer may see); a paragraph number that occurs twice in an order (e.g. "2." in the Read list and in the order) is not shown — never guessed; the later paragraph is shown as "same paragraph number", not as the current provision, unless the status tool confirmed the current version
- **Blocker / decision needed:** none
- **Exact next action:** TP14 DFA deterministic parts ("Read the following" list from visible, non-superseded, resolvable orders; abstract from the file subject; open flags travel with the draft; order paragraphs left to Gemini, labelled)

### 2026-11-05 · P8 / M9 · Touchpoint 7: referencing in a note
- **Status:** DONE
- **Plan section:** §11.5 touchpoint 7, §11.3 (connector metadata in, drafts out), §8 (citations); ADR-0012 update
- **Files changed:** `backend/app/connectors/eoffice.py` (`NoteRef`, `PageRef` on `FileContext`), `backend/app/eoffice_mock/adapter.py` (fills them from the seed), `backend/app/noting/chain.py` (`by_paragraph` on parsed notes), new `backend/app/noting/references.py` (`suggest_references`), `backend/app/agents/routes.py` (`POST /assist/note-reference`), `backend/app/agents/runtime.py` + `backend/app/main.py` (`ReferenceConfig` from `sandbox.yaml`; none → 503 "not configured"), `backend/config/sandbox.yaml` (`references`: TEST values), new `backend/tests/unit/test_note_references.py` (9), `backend/tests/unit/test_sandbox_api.py` (TP07 over HTTP; clearance regression and the endpoint × officer sweep cover the new endpoint), `evaluation/harness/suites.py` (TP07 handler), `evaluation/slots_v1.json` (`reference_requests`, `reference_config`), new `evaluation/reports/2026-11-05-note-reference{,-no-ocr}.{md,json}`, frontend `types.ts`, `api.ts`, `components/AssistPanel.tsx` (`NoteReferenceCard`, "Refer to an earlier note or page of this file"), `components/FilePageView.tsx` ("Suggested reference — draft"), `render.test.tsx`, `docs/decisions/0012-…md`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** backend ruff ✅ · format ✅ · mypy strict (111 files) ✅ · `pytest -q` 1174 passed ✅. Frontend `tsc` ✅ · Vitest 15 passed ✅ · build ✅. `run_eval.py --label note-reference --compare …held-scan-e.json` and `--label note-reference-no-ocr --no-ocr-stand-in --compare …held-scan-e-no-ocr.json` → both exit 0. Browser (Playwright): U04 opens 2601155 → "the earlier proposal for a preliminary enquiry" → Note #1, para 3 · 2601155-N1 first (then Note #2 para 4, Note #3 para 5) → Insert reference → "Suggested reference — draft MOCK-DRAFT-00001: Please see Note #1, para 3 (2601155-N1)"; no console errors
- **Acceptance evidence:** TP07 PASS on the eval stack (with and without the OCR stand-in): Note #1 para 3 of the same file with the e-Office note ID, sources only D21, D23 never named; **touchpoints passed 13 → 14 (with stand-in), 11 → 12 (without)**; all other metrics unchanged; leakage 0/1142 and 0/1014; HTTP sweep with three requests per file per officer → 0
- **Security / correctness:** note documents re-checked per officer; only Green Notes signed by `as_of`; a page that is an order is offered only if the officer may see it; the file itself goes through `open_file` (reach + clearance); suggesting writes nothing, inserting is a `suggested_reference` draft on click. Matching is a keyword stand-in, labelled in the response and on screen
- **Blocker / decision needed:** none (min_terms 2 / max 3 are sandbox TEST values)
- **Exact next action:** TP10 local reference in the harness (status lookup exists; scenario handler), then TP14 DFA deterministic parts ("Read the following" list, abstract, flags travel with the draft)

### 2026-11-04 · P4 / M5 · Fix: false type E for orders whose scan awaits review
- **Status:** DONE
- **Plan section:** §6.2 (type E), §5.3, §5.6; ADR-0013
- **Files changed:** `backend/app/ingestion/pipeline.py` (`IngestionStores.awaiting`: held records' tags, removed once indexed), `backend/app/conflict/citations.py` (E marked uncertain + "awaiting review" wording when the officer may see a held record of the cited order's department; held record never named), `backend/app/conflict/presend.py` (`awaiting_review` on the report; never CLEAR with it), `backend/app/agents/brief.py`, `backend/app/agents/routes.py` (pass `awaiting`; `awaiting_review` in the pre-send payload), new `backend/tests/unit/test_held_scan_citations.py` (7, written first, failed before the fix), `backend/tests/unit/test_sandbox_api.py` (HTTP regression), `evaluation/harness/suites.py` + `evaluation/run_eval.py` (uncertain flags and awaiting-review per draft in the report), frontend `types.ts`, `components/AssistPanel.tsx` (pre-send card line; brief says "not found yet — may be awaiting review"), `render.test.tsx`, new `docs/decisions/0013-type-e-while-records-await-review.md`, new `evaluation/reports/2026-11-04-held-scan-e{,-no-ocr}.{md,json}`
- **Tests/commands run:** backend ruff ✅ · format ✅ · mypy strict (109 files) ✅ · `pytest -q` 1164 passed ✅ (incl. the HTTP endpoint × officer sweep). Frontend `tsc` ✅ · Vitest 14 passed ✅ · build ✅. `run_eval.py --label held-scan-e --compare …checkpoint.json` and `--label held-scan-e-no-ocr --no-ocr-stand-in --compare …checkpoint-no-ocr.json` → both exit 0
- **Acceptance evidence:** without OCR, D24 and D28 no longer say the 2023 circular is missing from the officer's records; their E is uncertain with the awaiting-review wording. U01 holding nothing visible in Works keeps a certain E. Leakage 0/1142 and 0/1014. All headline metrics are unchanged: the harness counts uncertain flags, so precision without OCR stays 0.778
- **Security / correctness:** only held records that pass the officer's full `check()` count; the held record's ID/URI never appears (tested). Trade-off: while Finance scans wait, D27's non-existent 104/2026 is also uncertain (still flagged)
- **Not changed (checked, not bugs):** expanding L3 on the current-rule template raises recall@10 0.754→0.807 but lowers ladder-level accuracy 0.684→0.632, so it is a template trade-off for the owner. The graph is correct (D16 only REFERENCES D14). Q06/Q19 misses are the keyword stand-in on Telugu text. Q18 follows the owner decision on TP10/TP11
- **Blocker / decision needed:** owner — add L3 expansion to the current-rule template? (numbers above)
- **Exact next action:** owner choice; else TP6/TP7/TP14 deterministic parts

### 2026-11-04 · P7 / M8 · Checkpoint evaluation before the next slice
- **Status:** DONE (evaluation only; one bug found, fix awaiting owner)
- **Plan section:** §13 (evaluation), CLAUDE.md §9.3–§9.5
- **Files changed:** `evaluation/harness/stack.py` (`transcribe` flag: scans can stay in review), `evaluation/run_eval.py` (`--no-ocr-stand-in`; report header says which), new `evaluation/reports/2026-11-04-checkpoint.{md,json}`, `2026-11-04-checkpoint-no-ocr.{md,json}`, `2026-11-04-checkpoint-review.md`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** backend ruff ✅ · mypy strict (108 files) ✅ · `pytest -q` 1156 passed ✅ · `run_eval.py --label checkpoint --compare …baseline.json` exit 0 · `run_eval.py --label checkpoint-no-ocr --no-ocr-stand-in --compare …checkpoint.json` exit 0. Frontend `tsc` ✅ · Vitest 13 ✅ · build ✅ · `npm audit` 0
- **Acceptance evidence:** with the OCR stand-in: leakage 0/1142, recall@10 0.754, MRR 0.833, ladder-level 0.684, A/C/E/F P 1.0 R 1.0, touchpoints 13/13 run. Without: leakage 0/1014, recall@10 0.544, MRR 0.632, A/C/E/F P 0.778, clean-control false flags 1, touchpoints 11/13
- **Security / correctness:** leakage holds on both runs. **Bug:** a scan held for review (D13) makes the pre-send check report its citation as type E "not found" (D28, clean control D24)
- **Blocker / decision needed:** owner — fix the held-scan type-E flag (mark uncertain, without naming the held record) before TP6/TP7/TP14?
- **Exact next action:** on approval, regression test first, then the E-uncertain fix; re-run both checkpoint evals

### 2026-11-04 · P8 / M9 · Touchpoint 13: approval brief for a senior
- **Status:** DONE (deterministic parts); the written brief and types B/D wait for Gemini
- **Plan section:** §11.5 touchpoint 13, §6, §8, status-coverage rule
- **Files changed:** new `backend/app/agents/brief.py` (`approval_brief`: proposal facts from the draft, note chain, each cited order through the status tool, pre-send flags, Link-file precedents, movement trail), `backend/app/agents/routes.py` (`POST /assist/brief`, via `open_file`), `backend/tests/unit/test_sandbox_api.py` (TP13 per-officer test; sweep covers the brief), `evaluation/harness/suites.py` (TP13 scenario; shared `_tool_ctx`), new `evaluation/reports/2026-11-04-approval-brief.{md,json}`, frontend `types.ts`, `api.ts`, `components/AssistPanel.tsx` (`BriefCard`, "Approval brief"), `styles.css`, `render.test.tsx`, `PROGRESS.md`, `docs/LEARNINGS.md`
- **Tests/commands run:** backend: ruff ✅ · mypy strict (108 files) ✅ · `pytest -q` → 1156 passed ✅ · `run_eval.py --label approval-brief --compare …received-letters.json` → exit 0. Frontend: `tsc` ✅ · Vitest 13 passed ✅ · build ✅. Browser: the Secretary opens the 2026 transfer file → Approval brief: proposal (transfer · staff post · approval sought from the Deputy Secretary, with the note's words), put up by ASO (Estt.I) on 22-09-2026, 88/2022 superseded by 31/2025 (current version not claimed), 104/2026 not found, flags A/E/F/C, precedents including the CONFIDENTIAL 2025 case; no console errors
- **Acceptance evidence:** TP13 PASS on the eval stack — every required document named, flags A/C/E/F; D26 (evidence only for type B) reported as waiting for Gemini, not counted; **touchpoints passed 12 → 13**; other metrics unchanged; leakage 0 / 1142; HTTP sweep covers the brief for every officer and file → 0. The Estt.I SO's brief on the same file does not list the CONFIDENTIAL 2025 case; the Works SO gets 404
- **Blocker / decision needed:** none
- **Exact next action:** remaining core touchpoints need drafting (TP6 Yellow Note, TP7 referencing, TP14 DFA) — build their deterministic parts (cited points, reference targets, "Read the following" list) and leave the prose to Gemini; or pause P8 and pick up owner items

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
