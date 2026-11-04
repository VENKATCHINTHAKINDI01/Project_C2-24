# CLAUDE.md — Agent Operating Contract for C2-24

**Version:** 2.0 (10 Oct 2026)
**Authority:** `IMPLEMENTATION_PLAN.md` (Implementation Plan Final / v5, 13 Oct 2026; PDF copy in `docs/`)
**Project:** C2-24 — AI-Enabled Institutional Memory & Conflict Detection for Departmental Files (TechBharat AI CoE Fellowship, Cohort #2, Government of Andhra Pradesh)

This file is the mandatory operating contract for any AI coding agent working in this repository. Read it before inspecting, planning, editing, testing or committing code. The implementation plan is the source of truth; this file puts it into practice and does not override it. Other agents (Cursor, Codex, Copilot) reach this file through `AGENTS.md`.

---

## Project files (use these names — do not create alternatives)

| File | Purpose | Update when |
|---|---|---|
| `CLAUDE.md` | This contract | Only with the owner's approval |
| `IMPLEMENTATION_PLAN.md` | The design (Final / v5); § numbers referenced everywhere | Only after an approved decision |
| `PROGRESS.md` | Project state, phase/milestone status, checklist, blockers, open questions, decision index, task ledger, session log | End of **every** task |
| `docs/decisions/NNNN-title.md` | One record per decision (ADR) — use `0000-template.md` | When a decision is made or an assumption resolved |
| `docs/LEARNINGS.md` | Project memory: commands, conventions, data facts, gotchas | The moment something is learned |

**Never rely on memory from a previous session.** Re-read these files. If something is not written down, it does not exist.

---

## 0. Mandatory task protocol

### At the start of EVERY task, before making changes
1. Read `CLAUDE.md` completely.
2. Read `PROGRESS.md` and `docs/LEARNINGS.md`.
3. Inspect the actual repository: tree, current branch and status, relevant source files, tests, configuration and recent changes. Do not assume the repository matches a previous session.
4. Consult the relevant sections of `IMPLEMENTATION_PLAN.md` when a requirement, architecture decision, tier or sequence is involved. If the plan is not available, do not pretend to have re-read it — work from the explicit rules here and record the missing source in `PROGRESS.md`.
5. Identify the relevant plan sections and acceptance criteria for the task.
6. State a concise implementation plan before broad or risky edits (task · plan § · files · how it will be tested). For small, local fixes, proceed directly after identifying the expected behaviour.
7. **Preserve existing user changes.** Never overwrite, reset, delete or reformat unrelated work to make a task easier.

### During the task
- One checklist item at a time; finish it (code + tests + docs) before starting another.
- Small, reviewable changes; no drive-by refactors outside the task.
- Record anything future sessions must know in `docs/LEARNINGS.md` immediately.
- If the context is getting long or work is interrupted, write the exact next action in `PROGRESS.md` before continuing.

### At the end of EVERY task
1. Run the relevant tests, static checks and formatting/type checks that are available. **Never claim a check passed unless it was actually run.**
2. Update `PROGRESS.md`: task ledger entry (§12 format), checklist ticks, phase/milestone status, blockers, next action, session log row, "Last updated".
3. Update the project-state lines at the top of `PROGRESS.md` only when a durable architecture, decision or status fact changes.
4. If a plan assumption is resolved or a design decision is made: add `docs/decisions/NNNN-*.md` (date, context, options, decision, rationale, consequences, whether mentor/department confirmation is still needed) and a one-line entry in the `PROGRESS.md` decisions index.
5. Reply in the format in §13.
6. Keep the ledger factual: work is **done** only when acceptance criteria and tests have evidence — not because code was generated.

---

## 1. Source-of-truth and conflict rules

Priority order:
1. Official C2-24 problem statement and confirmed department/security requirements.
2. `IMPLEMENTATION_PLAN.md` and approved decisions in `docs/decisions/`.
3. This contract and the project state in `PROGRESS.md`.
4. Existing implementation, tests and conventions (`docs/LEARNINGS.md`).
5. Agent assumptions.

When sources conflict, **do not silently choose.** Stop the affected design decision, describe the conflict, cite the relevant section(s), and record it as a blocker or proposed decision in `PROGRESS.md`. Never "improve" the project by adding unrelated product features.

**Do not silently change the plan.** Any proposed architecture or scope change must state: reason, plan section affected, alternatives, security/correctness impact, effort impact, migration implications and approval status. Do not implement a material deviation until the owner approves it — unless it is required to prevent an immediate security vulnerability; then make the smallest safe change and report it clearly.

---

## 2. Immutable architecture decisions

### 2.1 System shape
- **Modular monolith:** one FastAPI backend on Cloud Run with clear internal modules. No microservices in the PoC.
- **React** officer-facing UI, hosted on Cloud Run.
- **LangGraph** orchestration with **one typed `AgentState`** through the graph. Agents keep no hidden/private workflow state.
- **Gemini on Vertex AI** only for controlled reasoning and drafting, and only from the authorised evidence package.
- Graph access behind a store-agnostic **`GraphRepository`** interface.

### 2.2 Data stores and their responsibilities
| Service | Responsibility |
|---|---|
| Cloud Storage | Raw uploaded/source documents and source artifacts |
| Document AI | OCR and extraction, incl. scanned/image files and Telugu/English |
| Vertex AI Embeddings | Text embeddings |
| Vertex AI Search | Hybrid vector + keyword retrieval at ladder rung **L2**, filtered by authorization metadata |
| Spanner Graph | Relationships and scope-constrained traversal at **L3** (supersession, amendment, reference, hierarchy/related links) |
| BigQuery | Structured metadata and canonical-ID lookup/filter facts for **L0/L1**; supersession facts where modelled; query log, audit, analytics. Do not put all graph traversal in BigQuery by default |
| Cloud SQL (PostgreSQL) | Application data, RBAC/ABAC tuples, LangGraph checkpointer/session memory, optional Tier-2 row-level security |
| Memorystore (Redis/Valkey) | **Cache only** — not the primary session store in the PoC |
| Cloud Run / Cloud Run Jobs | Backend and frontend hosting; Jobs for batch ingestion at PoC scale |
| IAM + IAP | Identity, roles, app gating |
| Secret Manager + Cloud KMS | Secrets and encryption/key management |
| RAGAS + project harness | Evaluation; the golden dataset/manifest is the source of expected outcomes |

### 2.3 Forbidden substitutions
- Spanner Graph is the planned graph store — **do not use Neo4j**.
- Do not replace Vertex AI Search with another vector database without explicit approval.
- Do not replace the Cloud SQL/PostgreSQL checkpointer with Redis in the PoC.
- Do not introduce microservices as the default architecture.
- Do not add Cloud Load Balancing, Pub/Sub, Dataflow, Apigee, Cloud Armor, Security Command Center, Terraform, full CI/CD, multi-region DR or other Tier-3 infrastructure as if it were part of the PoC. Cloud Run Jobs and simple async are the PoC-scale choices.
- Do not imply a live AP e-Office integration exists until an authorised integration path and credentials/data are confirmed. Start with synthetic data and authorised uploads/exports.

### 2.4 Mock e-Office sandbox (plan §11)
- The demo runs inside a **mock e-Office sandbox** (simulated eFile screens) — React screens in `frontend/eoffice/`, backend module `eoffice_mock/`, its own schema in the same Cloud SQL instance. No new cloud services.
- The sandbox reaches the C2-24 core **only through the `EOfficeConnector` interface** (`backend/app/connectors/`): events in, context (file no., user, scope) in, drafts out. Core modules must not import `eoffice_mock` directly.
- Every sandbox screen shows the banner "Mock e-Office sandbox — not NIC e-Office · synthetic data". No Parichay, DSC, eSign or Aadhaar; signatures are simulated clicks.
- The assistant writes **drafts only** (Insert as Yellow Note, Create DFA draft, suggested reference), created only on the officer's click. It never confirms a Green Note, signs, sends, dispatches or closes.
- compute_scope uses the sandbox profile (role/post, section, clearance, search scope, dealing section, movement trail) plus classification; the assistant must never return more than the officer's e-Office search scope allows.
- Build only the screens the touchpoints in plan §11.5 need. Core touchpoints first, then extended ones.

---

## 3. Retrieval ladder — do not reorder

All rungs execute within `compute_scope(user)` and enforce the officer's authorization. Stop early when sufficient authorised evidence is found.

- **L0 — Exact reference:** canonical document/clause ID lookup using fixed templates.
- **L1 — Structured filter:** BigQuery metadata query with fixed parameterised templates; status-aware.
- **L2 — Hybrid search:** Vertex AI Search vector + keyword, capped top-K, reranked.
- **L3 — Graph expansion:** Spanner Graph, scope-constrained traversal from L0–L2 hits for supersession, amendments and related decisions. Always the final rung.

The orchestrator classifies intent and fills template slots. **The LLM never generates SQL, graph queries or free-form retrieval queries.** Retrieval templates are deterministic, versioned, testable and parameterised.

---

## 4. Security rules — non-negotiable

Security is built before RAG and stays enforced throughout the stack. **The LLM is never the security boundary.**

1. Deterministic **RBAC + ABAC**: role, department, section, clearance, file assignment, document classification, action and relevant context.
2. `compute_scope(user)` runs before retrieval and produces filters pushed into every rung/retriever, including graph traversal. A retriever without a required scope parameter must not exist.
3. `can_access(user, document)` re-checks every candidate before evidence-package construction.
4. **Fail closed:** if identity, scope computation, authorization or re-check fails or times out, deny with a neutral message. Never fall back to unscoped retrieval or cache.
5. Never retrieve restricted content and then merely hide it in the UI or prompt.
6. Enforce authorization on: direct reference lookup, semantic/keyword retrieval, graph expansion, counts, summaries, aggregations, comparisons, existence questions, citations, conversation memory and cache hits.
7. Never confirm or deny the existence of inaccessible files. Counts and summaries are computed only over the authorised set; never hint at exclusions.
8. **Cache rules:**
   - user-agnostic artifacts may use content-hash keys;
   - authorised answers are keyed by `hash(canonical_query + scope_signature)` and invalidated on permission changes, reclassification or relevant new documents;
   - within-request retrieval/evidence reuse never crosses requests or scopes;
   - if cache scope cannot be verified, **bypass the cache**.
9. Re-apply current authorization on **every conversational turn**; a permission change takes effect immediately. Sessions are per `(user_id, session_id)` and never shared.
10. Retrieved document text is **untrusted data**. Prompt injection inside a document must not override system instructions, call tools or widen access.
11. Never log restricted document bodies or sensitive extracted text to general logs. Log IDs, metadata, access decisions and trace references as policy allows.
12. Citation verification is mandatory: reject citations not in the evidence package and withhold unsupported claims.
13. Human officers approve consequential actions. AI drafts and flags; it never signs, approves or makes an official decision.
14. No real confidential departmental data in local fixtures, test snapshots, commits or prompts unless explicitly authorised and protected. No secrets in code or git.
15. Required security tests: **zero unauthorised disclosure** across direct, exact-ID, keyword, vector, graph, cache, memory, count, summary, aggregation, comparison, existence and citation paths.

---

## 5. Ingestion and canonicalization

1. Route native PDF/DOCX/TXT, scanned/image-only and mixed PDFs, JPG/PNG/HEIC photos, and XLSX/CSV tables. **Detect the actual content type** — a `.pdf` extension does not prove a text layer.
2. Preserve provenance and structure: canonical document/clause ID, page, paragraph/location, source URI, document type, hierarchy level, status, effective dates, extraction confidence, access-decision reference.
3. **Extraction-confidence gate:** low-confidence extraction enters the human review queue and is not indexed as trusted evidence until confirmed.
4. Classify document types per the plan: G.O. (Ms/Rt), Standing Order, Circular, Memo, Office Order, Office Memorandum, Notification, Rule, Amendment, Clarification, Decision, Noting, and relevant source-specific types.
5. Resolve canonical IDs consistently. Proposed pattern: `AP-<DEPT>-<TYPE>-<NUMBER>-<YEAR>`, clause IDs `…#para-3.2`. Validate against real departmental numbering before freezing.
6. Preserve raw references when unresolved and flag them for review. **Never guess a canonical ID.**
7. Extract relationships: SUPERSEDES, SUPERSEDED_BY, AMENDS, CLARIFIES, REPEALS, REFERENCES. Uncertain relationships go to human review, never silently asserted.
8. Keep superseded documents versioned; never delete them. Ingesting a new document reconciles affected relationships/status and **invalidates impacted cached answers**.
9. The AP administrative hierarchy is a **working assumption** pending department confirmation — keep it configurable; do not treat it as legally confirmed.
10. Ingestion and update operations are idempotent with safe retries.

---

## 6. Temporal reasoning and conflict detection

1. Supersession, status, effective dates and instrument precedence are facts in structured metadata/graph plus deterministic logic — never LLM guesses.
2. Support as-of-date questions. "Latest document wins" is not a substitute for a supersession chain and validity dates.
3. Deterministic precedence: higher hierarchy level wins; at the same level the later effective instrument wins unless explicitly saved — subject to department confirmation.
4. Implement all seven conflict types:
   - **A** superseded reference · **B** direct rule contradiction (same level) · **C** procedural / wrong authority · **D** precedent inconsistency (review only) · **E** missing/unresolvable authority · **F** temporal mismatch · **G** hierarchy conflict (lower contradicts higher).
5. Deterministic checks where facts exist; Gemini only for grounded judgment (contradiction, comparable-case interpretation). Hierarchy precedence itself is deterministic.
6. Conflict flags are advisory and evidence-backed: "Potential conflict — … Review recommended", never a legal verdict.
7. Every conflict result includes: type, explanation, source evidence IDs/citations, relevant dates/status, uncertainty/review state.

---

## 7. Evidence package, agents and noting

1. The evidence package is the **only** document content sent to Gemini. Never append raw documents, unfiltered results, database dumps, hidden prompts or unrestricted memory.
2. Package fields: request ID, scope signature, as-of date, evidence ID, canonical ID, clause ID, text span, page/paragraph, source URI, type, hierarchy level, status/effective dates, retrieval rung/score, authorization decision reference.
3. All agents read/write the shared typed `AgentState`; outputs are structured and schema-validated.
4. Lean agent set: Orchestrator · Institutional Memory · Conflict Detection · Noting · Citation Verification. Authorization is a deterministic service, not an agent.
5. Every factual line in the first-cut noting has a verifiable citation. The noting stays a draft until the officer approves/signs it through the official workflow.
6. Insufficient evidence → the defined no-answer/deferred state: "No sufficiently supported answer was found in the authorised records." Never fill gaps with model knowledge or invent citations.
7. Citation check: claim → evidence ID exists in package → still authorised → cited span supports claim → pass / review. Unsupported claims are removed or withheld.
8. Prompts live in `backend/prompts/` as versioned files, not inline strings.

---

## 8. Human review and feedback

Human review is required for:
- approval/signing of notings;
- accepting/dismissing consequential conflict flags;
- confirming inferred supersession/hierarchy relationships;
- low-confidence extraction and unresolved canonical references.

Capture reviewer identity, action, timestamp, affected record/version and reason. Store feedback as evaluation data in the PoC; **never silently use it to change policy or production behaviour.**

---

## 9. Evaluation and definition of done

1. Maintain the synthetic corpus and ground-truth manifest (`data/synthetic/`) before relying on real data. Targets: ~100–300 documents, 3–4 departments, 5–8 officers — planned targets, not proof of completion.
2. **Evaluation integrity:** the ground truth (manifest answer key, golden questions, conflicts, relations) is for the evaluation harness only. Application code under `backend/app/` must **never import or read it**. Never edit golden questions or expected results to make a test pass.
3. Required suites:
   - retrieval: Recall@5/@10, Precision@5, MRR, NDCG, ladder-level accuracy;
   - canonical ID resolution across variants and unresolved references;
   - RAG faithfulness/groundedness, citation correctness/completeness, relevance;
   - temporal/as-of-date and hierarchy precedence;
   - per-type conflict precision/recall/F1, false negatives, clean-case false positives;
   - OCR/extraction accuracy and confidence gate;
   - permissions/leakage matrix;
   - prompt injection;
   - conversation-memory scope;
   - cache scope/invalidation;
   - audit completeness and human-approval workflow;
   - mock e-Office touchpoint scenarios (plan §11.5): each touchpoint end to end in the sandbox; scope never exceeds the officer's e-Office search scope; insert actions create drafts only.
4. **Security pass bar: zero unauthorised disclosure.** Also assert that no evidence package contains a forbidden canonical ID. Never weaken a threshold to get a green run — propose and record any threshold change for approval.
5. Any change affecting model, prompt, embeddings, chunking, retrieval thresholds/templates, authorization, ontology, temporal logic, conflict logic or caching → run the relevant regression harness and compare against the baseline.
6. Report metrics exactly as measured.

---

## 10. Build order and scope control

Follow the plan's sequence — never build RAG first and add security later:

**P0** foundation/design → **P1** ingestion/extraction → **P2** authorization core → **P3** retrieval ladder/RAG/citations → **P4** temporal/conflict/reconciliation → **P5** agents/noting/memory/HITL → **P6** verification/audit/tracking → **P7** evaluation/security harness → **P8** UI/integration/demo hardening (mock e-Office sandbox + touchpoints, core first) → **P9** buffer/rehearsal.

Work in vertical slices; always keep a runnable system. Tier 1 ahead of Tier 2; Tier 3 is deferred and must not displace Tier 1.

---

## 11. Engineering standards

1. Module boundaries per the plan: `backend/app/{auth,ingestion,identifiers,updates,retrieval,graph,temporal,conflict,precedent,noting,citation,hitl,memory,cache,tracking,audit,agents,connectors,eoffice_mock}`, plus `backend/tests/`, `backend/prompts/`, `frontend/` (incl. `frontend/eoffice/`), `data/{ontology,schemas,synthetic}`, `evaluation/`, `infrastructure/`, `docs/`. New top-level folders need a decision record.
2. Python 3.11+, FastAPI, Pydantic v2, LangGraph; React + TypeScript. Type hints everywhere; schemas for all data crossing module boundaries.
3. Interfaces + dependency injection (`GraphRepository`, `Retriever`, `LLMClient`, …) so cloud services can be faked; avoid unnecessary abstractions.
4. Deterministic business rules (auth, temporal, hierarchy, conflict types A/C/E/F) are pure functions with unit tests.
5. Config (thresholds, ladder settings, TTLs, hierarchy table) in config files, not hard-coded.
6. Docstrings on public functions name the plan section implemented, e.g. `"""Retrieval ladder rung L1 (plan §3.2)."""`
7. No secrets in source, committed `.env` files, logs, screenshots or fixtures. Provide `.env.example` with placeholder names only.
8. No new dependency without explaining why, checking compatibility and updating the lock/manifest.
9. Explicit error states; **never swallow exceptions** — convert failures to safe outcomes and log non-sensitive diagnostics.
10. **Clearly label mocks, synthetic data, stubs and unimplemented features.** Never fake data or mock an integration in a way that could be mistaken for a real one.
11. Never claim cloud services are deployed or operational unless verified in the actual environment.
12. No destructive database/schema/data change without a migration, a backup/recovery consideration and explicit approval when data could be lost.
13. Deterministic tests; unit tests never depend on live cloud credentials. Separate, explicit integration tests for real services.
14. Document any known limitation that could affect security, correctness or the demo.
15. Every feature ships with tests; bug fix → regression test first.
16. Commits: one logical change, `<area>: <what> (plan §x.y)`; commit only when checks pass, never with failing leakage tests.

**Checks before "done"** (record exact commands in `docs/LEARNINGS.md` once tooling exists): lint/format (`ruff`, frontend lint) · type check (`mypy`) · `pytest` · leakage suite (0 disclosures) · relevant evaluation suites.

---

## 12. Progress tracking format (task ledger in `PROGRESS.md`)

For every task record:
- date;
- phase/milestone (P0–P9, M1–M10);
- task and plan section;
- status: `NOT_STARTED` · `IN_PROGRESS` · `BLOCKED` · `DONE`;
- files/modules changed;
- tests/commands actually run and results;
- acceptance evidence;
- security / temporal / citation implications;
- blocker or decision needed;
- exact next action.

A task is `DONE` only when acceptance criteria are implemented, tests are run, results recorded and any required review completed. If tests cannot be run, say why and do not mark it fully done.

---

## 13. Required response format after each coding task

**Implemented** · **Files changed** · **Plan sections / milestone** · **Tests and actual results** · **Security and correctness implications** · **Known gaps / blockers** · **PROGRESS.md updated?** · **Next action**

Be concise but specific. Never report a successful build, test, deployment, authorization guarantee or cloud integration without evidence.

---

## 14. First task in a fresh repository

Before implementing features:
1. Inspect the repository and confirm this contract, `PROGRESS.md`, `docs/LEARNINGS.md` and `docs/decisions/` are present.
2. Compare the repository against the intended module structure (§11).
3. Identify actual language/runtime/dependency versions and existing tests.
4. Write a gap report into `PROGRESS.md`, mapped to P0–P9 and M1–M10, marking DONE / PARTIAL / NOT_STARTED / BLOCKED with evidence.
5. Do not scaffold the whole system blindly. Propose the smallest P0 vertical slice and wait for approval if the request is broad.

---

## 15. Never

- Invent department facts (classification levels, hierarchy, numbering, roles) — use mock values and mark real ones `[To confirm]`.
- Mark checklist items or tasks done without evidence.
- Leave a TODO without a matching entry in `PROGRESS.md`.
- Bypass these rules because the request is urgent — explain the risk instead.
- Create alternative tracking files (e.g. `PROJECT_STATE.md`, `IMPLEMENTATION_PROGRESS.md`, `DECISIONS.md`) — use the files listed at the top.
