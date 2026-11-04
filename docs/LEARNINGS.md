# LEARNINGS — project memory

Facts, conventions and gotchas discovered while building. Read every session. Add entries **as soon as you learn them**. Keep each entry to one or two lines; newest at the top of each section.

Format: `- YYYY-MM-DD · fact / rule · (source or plan §)`

## Commands
- 2026-11-04 · `make eval` (from repo root) runs the evaluation harness → `evaluation/reports/<date>-baseline.{md,json}`; exits 1 on any disclosure. Without uv: from `backend/`, `python ../evaluation/run_eval.py` (`--no-write` prints only). Lint/format now cover `../evaluation` with `--config pyproject.toml`
- 2026-11-03 · `pypdf` is now a core dependency: run `make setup` (uv sync) on the Mac before `make check`. Lock regenerated with uv 0.9.28 (same as the Mac) — a newer uv rewrites unrelated lock lines
- 2026-11-02 · Without the Mac venv, the same checks run in any Python 3.13 venv: `pip install fastapi uvicorn pydantic pydantic-settings pyyaml pytest httpx ruff mypy types-PyYAML`, then from `backend/`: `ruff check . && ruff format --check . && mypy && pytest -q` (379 passed, 2 Nov 2026)
- 2026-10-22 · From repo root: `make setup` (core+dev) · `make setup-all` (+agents/gcp/cache extras) · `make check` (ruff, mypy strict, pytest, format check) · `make run` (API :8080, `/healthz`) · `make local-up` (needs Docker running + `.env`)
- 2026-10-22 · Backend env is `backend/.venv` managed by uv (Python 3.13.9 from anaconda), not `aenv/`. If `aenv` is activated, uv warns about VIRTUAL_ENV; the Makefile runs `env -u VIRTUAL_ENV uv`
- 2026-10-22 · GCP scripts: `infrastructure/gcp/*.sh` dry-run by default; `APPLY=1` executes; Cloud SQL/Spanner also need `I_ACCEPT_COST=1`; `verify.sh` is read-only evidence
- 2026-10-13 · Local conda env `aenv/` (macOS, Python 3.13) lives in the project folder — keep it out of git; plan targets Python 3.11+, check library support on 3.13 before pinning
<!-- exact commands to run tests, lint, eval harness, local services -->

## Conventions
- 2026-11-04 · Action windows: `windows_from_text(cid, text)` → `ActionWindow(source=cid#para-2.i, action, start, end, evidence)`; ingestion keeps them in `stores.windows`; pass `windows=` to `presend_check`. Only in-force, visible orders count; inside any window → no flag
- 2026-11-04 · ADR-0011: `extract_metadata(..., source_department=)` fills the department only when the text names none (`department_source`); the pipeline holds text/tag disagreements as DEPARTMENT_MISMATCH. `valid_until` is read only from an order's own subject
- 2026-11-04 · Eval reports: `run_eval.py --label <name> --compare <earlier>.json` writes `<date>-<name>` with a before/now table; an existing name gets `-2`, `-3` (never overwritten), so `make eval` is safe
- 2026-11-04 · Evaluation stack = the ingestion job over every corpus file (not the CSV fixtures the unit tests use); slots for golden questions live in `evaluation/slots_v1.json`, written from question wording only — never tune them or the golden set to a result; a new slots version means a new file
- 2026-11-04 · Pre-send = `presend_check(note_id, text, meta, user_id=…)`: A/E/F over visible facts, C from `extract_proposal_facts` (last "may … approve/accord" sentence; "by X" wins), status coverage. Outcome CLEAR only with verified rules + full coverage + no fact gaps
- 2026-11-04 · Type C results: CONFLICT / NO_CONFLICT_VERIFIED / REVIEW_NEEDED. Only a `status: verified` rules file with verified + complete coverage (who/when) for that department + action can give NO_CONFLICT_VERIFIED; mock rules = testing only (owner)
- 2026-11-04 · Type C: rules only in `data/ontology/authority_rules.yaml` (clause-cited, `effective_from`); `check_authority(facts, rules, visible_ids)`; amounts in rupees via `parse_amount` ("Rs.1.30 crore" → 13000000)
- 2026-11-03 · Plan §7.3: explicit supersession ("in supersession of") is set directly; only inferred ones (same dept + type + subject without years/numbers, newer, no statement) go to review as unconfirmed edges. Open-file notices use `notices_for(user, …)` — per-officer filtered
- 2026-11-03 · Ingestion: `ingest(SourceDocument, bytes, stores=…)`; tags from the source only; idempotent per (source, sha256+pipeline version); identical bytes from another source = same document; partial (OCR-pending) documents never indexed; edges to not-yet-ingested targets wait in `stores.pending`
- 2026-11-03 · e-File documents without a printed number: `efile_document_id(file_no, NOTE|RPT|ANX)` → `AP-USD01-NOTE-USD0112-31-2022`
- 2026-11-03 · Metadata extraction follows the printed layout: department heading → own G.O./memo line → ABSTRACT / Sub: → "Read the following" → ORDER ("in supersession of … 1st read above"). Notes: "File No. … (Computer No. …)", "Note # n", date = latest signature. Citation spans must never cross into another reference
- 2026-11-03 · Status coverage (owner): status / "current version" only when `Scope.covers_status_domain(issuing dept, ceiling)` — scope-only, never record-dependent — else `STATUS_UNCONFIRMED`. Default ceiling = top classification (`full_department`)
- 2026-11-03 · Ingestion routes by content, never extension; a PDF page with text AND images is OCR'd (text layer not trusted). Unreadable input → `Route.UNSUPPORTED` → review queue, never an exception
- 2026-11-03 · While `ingestion.extraction_confidence_min` is null, every OCR'd extraction is held for human review; held items index only after a named reviewer CONFIRMS
- 2026-11-03 · Agents reach data only via `call_tool(ctx, name, args)`; `ctx.user_id` comes from the session, never the model. Temporal status/precedence inside tools use only facts the officer may see
- 2026-11-03 · Session memory stores IDs only and re-checks every remembered entity on recall; a session ID belongs to its first user forever
- 2026-11-03 · Citation outcomes (owner): CONFIRMED shown; REVIEW_NEEDED only in a separate labelled section (never as fact); REJECTED removed. Mismatch vs native text = REJECTED, vs OCR/incomplete = REVIEW_NEEDED (`EvidenceItem.text_quality`, `incomplete`)
- 2026-11-03 · References without a department: `reference_candidates` → every department; `lookup_reference` checks each inside the scope and returns FOUND / AMBIGUOUS (ask) / NOT_FOUND / UNRESOLVED
- 2026-11-03 · The model only picks an `Intent` and fills `IntentSlots`; `build_request` (fixed template table) makes the `LadderRequest`. Slots reject non-canonical IDs, non-word terms, unknown keys
- 2026-11-03 · Ladder: L0 exits when every reference is found, L1 on ≥1 authorised match, L2 when a hit passes `l2_min_score`; L3 only when relations are requested, seeded by earlier hits. `ladder_label()` gives the golden form ("L0+L3"). Test thresholds in `test_ladder.py` are not calibration
- 2026-11-03 · Evidence spans are rendered with every `<`/`>` replaced by `‹`/`›`; a tag-name blocklist missed `</evidence_package>` — never fence untrusted text with a blocklist
- 2026-11-03 · Citation verifier is deterministic: numbers/dates in a claim must appear in the cited span; quotes must match verbatim; otherwise NEEDS_REVIEW (no LLM yet)
- 2026-11-03 · L3 walks are constrained at every step: a node outside the scope is never visited, returned or used as a stepping stone; hits and whole paths are re-checked. `retrieval.l3_max_hops` is uncalibrated → callers pass it explicitly (`configured_max_hops` raises)
- 2026-11-03 · Owner rule: no crucial decisions from mock data (policy thresholds, classification, hierarchy, precedence, mock ID migration) — keep them configurable and `[To confirm]` until real data
- 2026-11-03 · ID collisions: first record keeps the bare ID; later ones get the printed section code (`-HRIII`) if it distinguishes, else a registry `-Cnn`; keyed by source identity, never reassigned; bare-ID lookup of a group = AMBIGUOUS (`identifiers/collisions.py`, ADR-0007)
- 2026-11-03 · Access = tuples in an access store, read per request (`scope_for`/`check` take a user ID + store, never a caller-built Principal). Department-wide needs rank ≥ 3 AND Department/Global search scope (owner, ADR-0009). Retrievers take a `Scope`; `retrieve()` re-checks survivors
- 2026-11-03 · Answer cache is shared across officers with identical permissions: key = hash(normalised canonical query + scope signature) (owner, ADR-0009)
- 2026-11-03 · ADR-0007 accepted: memo / circular memo / Rc IDs end in `-D<yyyymmdd>`; L0 tries `lookup_keys(id)` = exact, then without the tag
- 2026-11-02 · Authorization = two code paths that must agree: `compute_scope` → `Scope.admits` (pushed into retrievers) and `can_access` (re-check). Policy params in `data/ontology/access_policy.yaml` (mock). Every retriever must take a `Scope` (ADR-0009)
- 2026-11-02 · Core modules talk to e-Office only via `app.connectors.eoffice`; importing `app.eoffice_mock` outside that package fails a test
- 2026-11-02 · Conflict flags use the §6.4 wording ("Potential conflict — … Review recommended"); type E says "not found in the records available to you" so it never reveals restricted documents
- 2026-11-02 · Temporal: `valid_until` is a document's own end date; ends caused by supersession are derived by the engine. Only confirmed relations change status
- 2026-10-13 · Demo runs in a mock e-Office sandbox: banner on every screen, reaches core only via `EOfficeConnector` (`backend/app/connectors/`), assistant writes drafts only (Yellow Note / DFA draft) on officer click (plan §11)
- 2026-10-13 · 20 e-Office touchpoints: core = 2,3,4,6,7,8,9,10,11,13,14,15,20; extended = 1,5,12,16,17,18,19 (plan §11.5)
- 2026-10-13 · Plan Final (v5) renumbered: §11 Mock e-Office, §12 Data, §13 Evaluation, §14 Repository, §15 Milestones, §16 Open Questions (v4 §11–§15 shifted by one)
- 2026-10-10 · Canonical ID format: `AP-<DEPT>-<TYPE>-<NUMBER>-<YEAR>`, clause IDs `…#para-3.2` (plan §4.4) — confirm against real numbering
- 2026-10-10 · Classification order follows CSMOP: UNCLASSIFIED(0) < RESTRICTED(1) < CONFIDENTIAL(2) < SECRET(3)
- 2026-10-10 · Draft instrument hierarchy: Constitution > Act > Rules > G.O.(Ms) > G.O.(Rt) > Standing Order > Circular/Memo > Office Order > Decision/Noting (plan §4.5) — confirm with department
- 2026-10-10 · Conflict types: A superseded ref · F temporal · C procedural · E missing authority · B contradiction · G hierarchy · D precedent (plan §6.2)

- 2026-11-02 · Officer hierarchy lives in `data/ontology/roles.yaml` (provisional, ADR-0008), separate from the instrument hierarchy in `hierarchy.yaml`; every role carries evidence (official source or G.O. corpus count). Re-research before auth relies on it

## Data facts
- 2026-11-03 · Touchpoint scenarios live in `ground_truth/touchpoint_scenarios.json` (eval only); "as related question" / "same as TP11-a" fields defer to golden questions / conflicts.json. Every mock superseding order arrives before any open file cites the old one, so the TP04 demo is a replay with `setup.holdback`
- 2026-11-03 · e-Office seed: `python3 data/synthetic/tools/build_eoffice_seed.py [--check]` → `data/synthetic/mock_v1/eoffice/seed.json`; a unit test fails if it is stale. Note authors map to profiles by post (two Secretaries over time = one post, U06); ASOs are `POST-…` staff without login
- 2026-11-03 · NIC eFile 7.0 manual (uploaded `UserManualeFile7_0_1.pdf`): Receipt No. = `sequence no./creation year/dealing_section_name`; receipts and files each have a Computer No.; Yellow notes are versioned until confirmed to Green
- 2026-11-02 · Mock access policy reproduces `access_matrix.csv` exactly: public if UNCLASSIFIED; else same dept + clearance ≥ class + (rank ≥ 3 or same section or assigned file). Users with section `ALL` map to `section=None`
- 2026-11-02 · Mock corpus memo IDs have no `-D<date>` tag but the collector adds one (ADR-0007): resolver flag `memo_date_tag` (off) and `CanonicalId.base_id` bridge the two
- 2026-11-02 · e-File references (`File No.USD01-12/19/2026-ESTT.I`) name a file, not a document: the resolver returns `file_no`, never a canonical ID
- 2026-10-22 · Mock corpus v1 copied to `data/synthetic/mock_v1/` (from ~/Desktop/C2-24_mock_corpus); ground truth in `mock_v1/ground_truth/`, guarded by `tests/unit/test_eval_integrity.py`
- 2026-10-22 · `access_matrix.csv` has CRLF line endings; use `csv` module, not naive split
- 2026-10-22 · Data-collection code now lives in `data_collection/` (ADR-0006, owner-approved); the corpus (≈640 MB) stays in `~/Documents/c2-24-data-tools`, named in git-ignored `data_collection/local.env` (`C2_DC_DATA_ROOT`). Project_1's copy of the scripts and `scope.yaml` is the maintained one; never commit the corpus
- 2026-10-22 · Public corpus at integration: 831 records (829 G.O.s: 787 Ms, 42 cited Rt; 2 gazettes) · 2,885 candidate links (2,772 REFERENCES, 79 AMENDS, 31 SUPERSEDES, 3 REPEALS) · dates: 723 printed=archive, 2 corroborated, 6 need review, 100 printed unreadable · 12 synthetic e-files (Finance)
- 2026-10-22 · Archive (Internet Archive GOIR mirror) dates are sometimes a day late vs the printed date (~1%); printed date wins only when corroborated or verified (ADR-0007). GOIR has no memo/circular search; e-Gazette search works only with the year filter and serves files via session tokens
- 2026-10-22 · Collection is in test phase: dry run, then 1–2 files; full runs need `FULL=1` / `--limit 0` and owner approval. Details: `docs/data_collection/crosscheck.md` (findings 1–73)
- 2026-10-13 · Mock corpus v1 has documents only — no receipts, note versions, movements, drafts, links or sandbox profiles yet; these must be added for the e-Office demo (plan §11.6)
- 2026-10-10 · Mock corpus v1: 29 docs, 3 depts (FIN01, GAD01, USD01), 8 officers (U01–U08), as-of date 2026-10-02; answer key in `ground_truth/` is eval-only
- 2026-10-10 · Real G.O.s cite earlier orders in a "Read the following" list; supersession usually refers to list positions ("reference 2nd read above"), so resolve the list first

## Gotchas
- 2026-11-04 · Unit tests built on `documents_index.csv` dates can pass while the real pipeline misses the same fact (D29 type F: ingestion has no validity-end date). Check behaviour on the pipeline stack via `make eval`, not only unit tests
- 2026-11-04 · (fixed same day) subjects were empty for abstracts without a rule line and for reports/statements; base-number references missed dated memo IDs
- 2026-11-03 · PDF text puts note signature dates on their own line and wraps citations; DOCX signature blocks use <w:br/>/<w:tab/> — search flattened text, keep breaks when reading DOCX
- 2026-11-03 · Mock XLSX formulas have no cached values (generated files): extraction keeps "=formula" instead of a number
- 2026-11-03 · `tests/unit/mock_access.py` gives mock users a search scope (rank ≥ 3 → department, else section) because users.csv has none; change both if users.csv gains a scope column
- 2026-11-03 · `data/schemas/authz.sql` is syntax-checked only (pglast); first real run is on Cloud SQL
- 2026-10-22 · Data-collection tools fail fast if `C2_DC_DATA_ROOT` is unset; `staging` arguments resolve inside the data root, so they work from any folder
- 2026-10-22 · macOS `/bin/bash` is 3.2: no associative arrays (`declare -A`) in shell scripts
- 2026-10-22 · Spanner Graph needs Enterprise (or Enterprise Plus) edition; verify GQL support in the Spanner emulator before relying on it locally
- 2026-10-22 · Document AI processor locations may be limited to `us`/`eu`: verify on access day; data-residency question for the department
- 2026-10-22 · Config thresholds are `null` until calibrated; consumers must treat `None` as "not configured", never substitute a guess

## Open assumptions (replace when confirmed)
- Real classification levels, role hierarchy, supersession recording practice — all `[To confirm]`
