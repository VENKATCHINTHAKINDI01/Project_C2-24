# C2-24 — Institutional Memory & Conflict Detection for Departmental Files

![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![Backend](https://img.shields.io/badge/backend-FastAPI%20%2B%20LangGraph-009688)
![Frontend](https://img.shields.io/badge/frontend-React%2018%20%2B%20TypeScript-61dafb)
![Region](https://img.shields.io/badge/GCP-asia--south1-4285f4)
![Leakage](https://img.shields.io/badge/unauthorised%20disclosures-0-brightgreen)
![Status](https://img.shields.io/badge/status-proof%20of%20concept-orange)

A permission-aware AI assistant for government e-Office files. While an officer works on a file,
it finds the orders and earlier decisions that apply, says whether each is still in force, flags
possible conflicts before the file is sent, answers questions about the file in plain language,
and prepares cited notes and drafts for approval that the officer edits and saves.

Built for problem statement **C2-24** of the TechBharat AI CoE Fellowship (Cohort #2, Government
of Andhra Pradesh).

> **Status and scope**
> - **Proof of concept.** It runs inside a **mock e-Office sandbox** ("Mock e-Office sandbox — not
>   NIC e-Office · synthetic data"). There is no connection to NIC e-Office.
> - **Data.** Public Government Orders and synthetic e-files only; no real departmental records.
>   The hierarchy, roles and access policy are mock values `[To confirm]` with the department.
> - **AI boundary.** The model is never the security boundary, never writes SQL, graph or search
>   queries, and never signs, approves, sends or closes anything. Officers make every decision;
>   signatures in the sandbox are simulated clicks (no DSC, eSign, Parichay or Aadhaar).

---

## Contents

- [What it does](#what-it-does)
- [How an officer uses it](#how-an-officer-uses-it)
- [Architecture](#architecture)
- [End-to-end flow](#end-to-end-flow)
  - [1. Ingestion: from a paper to searchable evidence](#1-ingestion-from-a-paper-to-searchable-evidence)
  - [2. A question: from the officer to a cited answer](#2-a-question-from-the-officer-to-a-cited-answer)
  - [3. The file chat](#3-the-file-chat)
  - [4. Drafting](#4-drafting)
  - [5. Conflict detection](#5-conflict-detection)
  - [6. Evaluation and release](#6-evaluation-and-release)
- [Retrieval ladder](#retrieval-ladder)
- [The assistant and the model](#the-assistant-and-the-model)
- [Security model](#security-model)
- [Technology stack](#technology-stack)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [Testing and evaluation](#testing-and-evaluation)
- [Results](#results)
- [Deployment](#deployment)
- [Documentation](#documentation)
- [Known limitations](#known-limitations)
- [Contributing](#contributing)
- [License](#license)

---

## What it does

| Area | What it does |
|---|---|
| Institutional memory | Scoped search over orders, circulars and earlier file decisions; every answer line is cited to a record the officer may open. |
| Temporal reasoning | Deterministic in-force / superseded status and as-of-date answers from the supersession and amendment chain, never a model guess. |
| Conflict detection | Seven advisory types: **A** superseded reference · **B** direct contradiction · **C** wrong authority or procedure · **D** precedent inconsistency (review only) · **E** missing authority · **F** temporal mismatch · **G** hierarchy conflict. Deterministic where facts exist; the model only for grounded judgment. |
| File assistant | One chat per file that opens with a structured, end-to-end summary of the file, then takes follow-up questions in plain words: next action, movements, records, approval brief, changes since the decision, pre-send check, related files, first-cut note, drafts, closing remarks, references to earlier notes and order status. |
| Noting and drafting | First-cut Yellow Notes and drafts in e-Office formats (note, G.O.Ms., G.O.Rt., memo, circular, letter). "Prepare a draft" with no kind named picks the draft from the file's stage. Fields are filled from the notes with citations; gaps are marked; saved only on the officer's click. |
| e-Office touchpoints | All 20 touchpoints of plan §11.5 in the sandbox: receipt diarisation, pre-send check, reference matching, handover brief, return with remarks, draft revision and more. |
| Human review | OCR confidence gate and review screen, relation confirmation, feedback captured as evaluation data. |
| General chat | "Ask AI" in the top bar: cited answers over every record the officer may open; yes/no questions answered first; greetings and "what can you do" answered without any search. |
| Chat history | Each officer's conversations are kept by the server and can be reopened, or deleted one by one or all at once in Settings. |

---

## How an officer uses it

1. **Sign in** (sandbox): choose a mock officer. Post, section, clearance and search scope decide
   what they can see.
2. **Open a file.** The page shows the notes, correspondence and movements. A floating **AI
   button** (bottom right) opens the file's chat, which starts with a summary of the whole file:
   what it is about, what happened, decisions and directions, where the file stands (from e-Office
   itself) and what is pending. Every line names the note it comes from.
3. **Ask follow-ups in plain words** — "do I have any action on this file?", "has this been
   decided before?", "prepare a draft". The assistant works out what is meant, answers directly
   with sources, and offers drafts the officer can edit and save.
4. **Send** runs the pre-send check in the chat; nothing is ever sent by the assistant.
5. **Ask AI** in the top bar is the general chat over every file and record the officer may open.

---

## Architecture

A modular monolith (one FastAPI service) behind a React UI, on Google Cloud in `asia-south1`.

```mermaid
flowchart TD
    Officer["Officer"] --> UI["Mock e-Office UI<br/>React 18 + TypeScript (Cloud Run)"]
    UI --> API["c2-api — FastAPI modular monolith (Cloud Run)"]
    API --> Scope["compute_scope(officer)<br/>RBAC + ABAC, fail closed"]
    Scope --> Small["Greetings / help<br/>fixed reply, nothing searched"]
    Scope --> Intent["Intent: one tool from a closed list<br/>Gemini, fixed rules as fallback"]
    Intent --> Tools["File tools<br/>same scoped endpoints as the buttons"]
    Intent --> Orch["LangGraph orchestrator<br/>one typed AgentState, fixed query templates"]
    Orch --> Ladder["Retrieval ladder L0 → L3<br/>scope in every query"]
    Ladder --> BQ["BigQuery<br/>L0/L1 metadata · L2 vector + keyword · audit"]
    Ladder --> Graph["Spanner Graph<br/>L3 relations (Cloud SQL as reference store)"]
    Orch --> Recheck["can_access re-check → evidence package"]
    Recheck --> Gemini["Vertex AI Gemini<br/>wording from the evidence package only"]
    Gemini --> Verify["Citation verifier<br/>unsupported lines withheld"]
    Verify --> Layout["Answer layout over checked statements<br/>gated: numbers, words, claim polarity"]
    Tools --> Record["e-Office record of the file<br/>state, holder, last direction (deterministic)"]
    Record --> Gemini
    Layout --> UI
    API --> SQL["Cloud SQL (PostgreSQL)<br/>app state, access tuples, sessions, chat history, usage ledger"]
```

The sandbox reaches the core only through the `EOfficeConnector` interface
(`backend/app/connectors/`); core modules never import the mock.

---

## End-to-end flow

The system has two paths: **ingestion**, which turns papers into searchable, linked evidence, and
**requests**, which turn an officer's question or action into a checked answer or a draft. Both run
inside the same security rules: the officer's scope is applied before anything is read, and the
model only ever sees what that officer may already open.

### 1. Ingestion: from a paper to searchable evidence

```mermaid
flowchart TD
    Src["Paper arrives<br/>(e-Office event, upload, public G.O. corpus)"] --> Detect["Detect the real content type<br/>native PDF / DOCX / scan / photo / sheet"]
    Detect --> Extract["Extract text<br/>native text layer; Document AI OCR for scans (Telugu / English)"]
    Extract --> Gate{"Extraction confident<br/>and complete?"}
    Gate -- no --> Queue["Held in the OCR review queue<br/>(not evidence until a person confirms)"]
    Queue -- "reviewer confirms or corrects<br/>(who, when, why recorded)" --> Extract2["Same pipeline again, every check re-run"]
    Gate -- yes --> Meta
    Extract2 --> Meta["Metadata by fixed rules (no model)<br/>type, number, date, department, subject,<br/>file no., effective dates, references, relations"]
    Meta --> Checks{"Department / classification match?<br/>Canonical ID resolvable? No ID collision?"}
    Checks -- no --> Held["Held for review<br/>(raw reference kept; an ID is never guessed)"]
    Checks -- yes --> Index["Index: document + access tags"]
    Index --> Graph["Graph: node + explicit relations<br/>(pending edges attach when the target arrives)"]
    Graph --> Temporal["Temporal facts: hierarchy level,<br/>effective-from, valid-until, order paragraphs"]
    Temporal --> Reconcile["Reconcile: superseded / amended orders<br/>change status; open files that cite them are linked"]
    Reconcile --> Invalidate["Invalidate cached answers touching<br/>this document or the orders it affects"]
    Invalidate --> Cloud["Batch job (Cloud Run Job): BigQuery metadata,<br/>passages + gemini-embedding-001 vectors (768),<br/>graph to Cloud SQL / Spanner"]
```

- **Passages for vector search.** Each indexed document is cut into ~1,200-character passages
  (200 overlap). Each passage row in BigQuery carries its text, its 768-dimension vector and the
  same access tags as its document. Current cloud corpus: 1,290 documents, 17,696 passages, all
  embedded; 83 documents held for review.
- **A scan confirmed in the app** is searchable at once on the running service (in-memory index
  and graph). It reaches the BigQuery passages table and the cloud graph at the next batch job.
- **Nothing in ingestion uses the generative model.** Types, numbers, dates and relations come
  from fixed rules and tables; anything uncertain goes to a person.

### 2. A question: from the officer to a cited answer

```mermaid
sequenceDiagram
    autonumber
    actor O as Officer
    participant UI as e-Office UI
    participant API as c2-api
    participant Auth as Scope service
    participant L as Retrieval ladder
    participant G as Gemini (asia-south1)
    participant V as Checks
    O->>UI: "Is G.O.Ms.No.31 of 2025 still in force?"
    UI->>API: /assist/chat (signed identity)
    API->>Auth: compute_scope(officer) — fails closed
    alt greeting, thanks, "what can you do"
        API-->>UI: fixed reply, nothing searched or generated
    end
    API->>L: L0 exact → L1 filter → L2 vector + keyword → L3 graph (scope in every query)
    L-->>API: candidates
    API->>Auth: can_access(officer, record) for every candidate
    API->>API: status of each order (deterministic, as of today)
    API->>G: evidence package only (authorised passages + their status)
    G-->>API: statements, each with an exact quote
    API->>V: citation check · status-word rule · B/G conflict check
    V-->>API: confirmed statements, unsupported ones withheld
    API->>G: lay out the checked statements (direct first line)
    API->>V: gate the layout (no new number, claim or polarity)
    API-->>UI: answer with sources, conflicts, or the defined no-answer
```

1. **Identity and scope.** The signed identity gives the officer's post, section, clearance,
   search scope and movement trail; `compute_scope` turns them into filters before any retrieval.
2. **Small talk** (greetings, thanks, "what can you do") gets a fixed reply. No record is read
   and no model is called.
3. **Retrieval ladder** (L0 → L3, below), each rung a fixed, parameterised query with the scope
   inside it. The model never writes a query or picks a rung.
4. **Re-check.** Every candidate is checked again with `can_access` before the evidence package
   is built.
5. **Status.** Whether each order is in force comes from the supersession and amendment chain.
   When the officer may not be told a status, model statements carrying status words are withheld,
   and the record's content is stated attributed to it by name (prompt `answer_cited.v4`).
6. **Cited answer.** Gemini receives only the evidence package and must quote the passage behind
   every statement. The citation verifier rejects quotes and numbers not in the cited text.
7. **Conflicts.** The B (contradiction) and G (hierarchy) check runs on the records the answer
   rests on; it never withholds the answer, it adds advisory flags.
8. **Layout.** The checked statements are arranged with a direct first line (a yes/no question
   starts with "Yes" or "No" when the records settle it). The first line is gated: no number,
   date or reference outside the statements it names, and no claim such as "approved" or
   "superseded" — or its negation — that those statements do not make.
9. **No answer.** When nothing is supported: "No sufficiently supported answer was found in the
   authorised records", plus the closest records and what to ask next.
10. **History.** The turn is kept in the officer's chat history; on every read the file access and
    each cited record are checked again.

### 3. The file chat

```mermaid
flowchart TD
    Open["Officer clicks the AI button on a file"] --> Rec["e-Office record (deterministic):<br/>subject, state, holder, with you or not,<br/>due date, last direction, correspondence"]
    Open --> Notes["Notes the officer may read<br/>(signature dates as dd-mm-yyyy)"]
    Rec --> Sum["Gemini writes the summary<br/>(file_summary.v4)"]
    Notes --> Sum
    Sum --> Gate["Per-sentence gate: numbers and dates in the notes it names,<br/>most words from them, claims with the same polarity,<br/>holder matches e-Office, officer never made a note's author"]
    Gate --> Show["Structured summary: what the file is about · what happened ·<br/>decisions and directions · where the file stands (record only) · what is pending"]
    Show --> Follow["Follow-up in plain words"]
    Follow --> Intent["Intent: one tool from a closed list<br/>(intent_route.v4; fixed rules as fallback)"]
    Intent --> Tools["File tools: next action · movements · records · brief ·<br/>since · pre-send check · related files · first-cut note ·<br/>draft · closing remarks · earlier notes · order status"]
    Intent --> Search["or the scoped search (flow 2)"]
```

- **Opening.** The summary is written once per opening of the file, only when the panel is shown;
  earlier conversations stay under "Earlier chats".
- **"Where the file stands"** is never model text: it is what e-Office records about the file.
- **Action questions** ("do I have any action on this file?") are answered first, from the
  record and the last direction: whether the file is with the officer, its state, what the last
  direction requires, and whether the record shows it done.
- **Fallbacks.** A sentence that fails the gate is dropped. If nothing passes, the officer sees
  the record sentences or the notes as written — never an unchecked line.

### 4. Drafting

1. **Which draft.** A named kind (note, G.O.Ms., G.O.Rt. or order, memo, circular, letter) is
   used as asked. "Prepare a draft" with no kind named is decided from the record, not the model:
   if the last direction approves, the G.O.Rt. that carries it out; otherwise a note putting the
   proposal up for orders. The reply says which draft and why, and warns if the file is closed.
2. **Fields.** Subject, request, facts, what is ordered, signatory and addressees are filled
   from the notes the officer may read (`draft_inputs.v1`), each field gated against the notes it
   names; anything not filled is listed for the officer.
3. **Read list.** The orders the file and the draft cite, with their current status.
4. **Pre-send check** on the draft itself: superseded references, wrong authority, missing
   authority, temporal mismatch, and B/G conflicts with the orders it reads.
5. **Wording.** Suggested wording from the evidence only; each line checked, removed lines
   counted. A daily per-officer limit applies.
6. **Saving.** Nothing is saved until the officer clicks *Insert as Yellow Note* or *Create DFA
   draft*. The assistant never signs, approves, sends or closes.

### 5. Conflict detection

| Type | What it flags | How it is decided |
|---|---|---|
| **A** superseded reference | A cited order no longer in force | Deterministic, from the supersession chain |
| **B** direct contradiction | Two same-level instruments say opposite things | Gemini judgment over the two passages, grounded and advisory |
| **C** wrong authority / procedure | The proposed approver lacks the power | Deterministic, from the rules table |
| **D** precedent inconsistency | Unlike earlier decisions on like facts | Review only |
| **E** missing / unresolvable authority | A reference that cannot be resolved | Deterministic |
| **F** temporal mismatch | Applying an order outside its effective dates | Deterministic |
| **G** hierarchy conflict | A lower instrument contradicts a higher one | Precedence deterministic; the contradiction judged as in B |

Every flag reads "Potential conflict — … Review recommended" with its evidence, dates and status;
none is a legal verdict.

### 6. Evaluation and release

```mermaid
flowchart LR
    Change["Change to prompts, model,<br/>retrieval or access"] --> Local["make check · make fe-check<br/>leakage harness (local)"]
    Local --> Job["Cloud Run Job c2-eval (MODE=all)<br/>image pinned to its digest"]
    Job --> Leak["Leak check<br/>21 officers × 203 files"]
    Job --> Rag["RAGAS + citation metrics<br/>judge pinned (JUDGE_MODEL)"]
    Job --> Conv["Conversation check<br/>intent, chat, 65 file-chat questions, small talk"]
    Leak --> Bar{"Release bar"}
    Rag --> Bar
    Conv --> Bar
    Bar -- pass --> Deploy["Deploy c2-api, then c2-frontend"]
    Bar -- fail --> Review["Owner review"]
```

- **Release bar:** 0 unauthorised disclosures; 0 critical conversation failures; faithfulness and
  groundedness 1.0; answer relevancy at least the 19 Nov baseline (0.762).
- **Reports** go to `gs://…-artifacts/eval-reports/<UTC date-time>-<mode>-<label>/`, one folder
  per run, with a `run-config.json` naming the image digest, the model and its limits, and the
  judge.
- **Changing the model:** set `GEMINI_MODEL` the same way for the evaluation job and the deploy.
  The judge stays pinned, so scores remain comparable with the baseline. Only models served in
  `asia-south1` are used (check with `infrastructure/gcp/09_regional_checks.sh`).

---

## Retrieval ladder

Every rung runs inside the officer's scope; the ladder stops as soon as authorised evidence is
sufficient. The model never generates retrieval queries and never chooses a rung.

| Rung | Store | What it does |
|---|---|---|
| **L0** exact reference | BigQuery | Canonical ID lookup (e.g. a G.O. number) through a fixed template. |
| **L1** structured filter | BigQuery | Parameterised metadata filter (department, type, dates, status). |
| **L2** hybrid search | BigQuery + Vertex AI embeddings | Vector + keyword search over passages, capped top-K, one fixed template. |
| **L3** graph expansion | Spanner Graph | Scope-constrained walk from L0–L2 hits for supersession, amendment and related orders. Always last. |

- **L2 early exit is off.** L2 may end the ladder only under a calibration measured the way the
  exit runs, whose precision clears the target at the low end of its 95% interval. The first cloud
  measurement (150 questions) did not, so every L2 result continues to L3.
- **Bounded graph walks.** `l3_max_nodes` and `l3_max_edges` in `backend/config/runtime.yaml`;
  only steps to records the officer may see count, so a limit never reveals hidden records. A cut
  walk is re-walked over binding relations and is reported to the officer, never silent.

---

## The assistant and the model

Gemini on Vertex AI (`gemini-3.5-flash`, called only in `asia-south1`) is used in bounded places;
each has a deterministic fallback. Ingestion, scope, status, precedence and conflict types A, C, E
and F never use it.

| Step | What the model sees | What it may do | Gate / fallback |
|---|---|---|---|
| Intent | The officer's message | Pick one tool from the list the screen offers, or the scoped search | Anything off the list, an error or a slow reply → fixed phrase rules |
| Cited answer | The evidence package (authorised passages only) | Write statements, each with an exact quote | Citation verifier: unsupported statements are withheld |
| Answer layout | The statements that already passed the check | A direct first line and grouped points | Every statement shown once; no number, date or reference not in the statements it names; otherwise the answer as checked |
| File summary / next action | The e-Office record of the file and the notes the officer may read | A direct lead and sectioned points, each naming its notes (0 = the record) | Per-sentence gate (numbers, words, claim polarity, holder, note authorship); otherwise the record sentences or the notes as written |
| Draft fields | The notes the officer may read and the chosen format | Fill subject, request, facts, proposal, signatory, addressees | Each field gated against the notes it names; unfilled fields listed for the officer |
| Contradiction (B / G) | The two passages being compared | Say whether they conflict, quoting both | Advisory only; never withholds the answer |

Drafting wording (notes, orders) uses the same evidence-only rule and a daily per-officer limit.
Prompts are versioned files in `backend/prompts/`.

---

## Security model

| Control | How |
|---|---|
| Scope before retrieval | `compute_scope(officer)` (role, post, section, clearance, search scope, movement trail, classification) is pushed into every rung, including graph walks and counts. |
| Re-check | `can_access(officer, document)` re-checks every candidate before the evidence package is built. |
| Fail closed | Any identity, scope or re-check failure gives a neutral denial; never an unscoped fallback. |
| No existence leaks | Inaccessible records are "not available", exactly like records that do not exist; counts and summaries cover the authorised set only. |
| Cache | Answers keyed by query + scope signature; the per-request memo never crosses requests or scopes; unverifiable scope bypasses the cache. |
| Untrusted documents | Retrieved text is data; prompt injection cannot call tools or widen access. |
| Citations | Never chosen by the model; claims are checked against the evidence package and unsupported lines are withheld. |
| Model in the chat | Intent picks from a closed list (never a query or template); layout and summaries are gated against what the officer may already see, including the meaning of status words ("approved", "not approved"); small talk never reaches retrieval or the model. |
| Chat history | Per officer only; file access and every cited record are re-checked on every read; a file tool's answer is never stored, only re-read; deletable. Not a log. |
| Logging | IDs, outcomes and timings only; never document text or the officer's question unless explicitly configured. |
| Data residency | Compute, storage, search and model calls in `asia-south1`. |
| Identity and access | IAP-signed identity on Cloud Run; a mock sign-in header only in sandbox mode. Cloud Run access settings are owned by the platform administrators; deploy scripts never change them on an existing service. |

The leakage suites assert **zero unauthorised disclosure** across direct, exact-ID, keyword,
vector, graph, cache, memory, count, summary, comparison, existence, citation and drafting paths.
See also [SECURITY.md](SECURITY.md).

---

## Technology stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+, FastAPI, Pydantic v2, LangGraph, `uv` |
| Models | Vertex AI `gemini-3.5-flash` (intent, wording, grounded judgment) and `gemini-embedding-001` (768-dim), both in asia-south1; `GEMINI_MODEL` switches the answering model after a passing evaluation |
| Search and metadata | BigQuery (asia-south1): L0/L1 metadata, L2 vector + keyword, audit and query logs |
| Graph | Spanner Graph behind the `GraphRepository` interface (PostgreSQL and in-memory implementations for tests and the sandbox) |
| Application state | Cloud SQL for PostgreSQL 16: sessions, chat history, access tuples, checkpoints, model-usage ledger, draft workspaces |
| Documents and OCR | Cloud Storage, Document AI (pinned OCR processor for Telugu / English) |
| Frontend | React 18, TypeScript, Vite, plain CSS, `lucide-react` icons, Vitest |
| Hosting | Cloud Run (API and UI), Cloud Run Jobs, IAP, Secret Manager; Docker Compose locally |

---

## Repository layout

```
.
├── backend/
│   ├── app/                 # agents, audit, auth, cache, citation, conflict, connectors,
│   │                        # eoffice_mock, graph, hitl, identifiers, ingestion, memory, noting,
│   │                        # precedent, retrieval, temporal, tracking, updates
│   ├── config/              # runtime.yaml (ladder, thresholds), draft formats, sandbox profiles
│   ├── prompts/             # versioned prompt files (intent, answers, summaries, drafts)
│   └── tests/               # pytest suites (unit, security, integration)
├── frontend/
│   ├── eoffice/             # mock e-Office screens (React + TypeScript)
│   └── server/              # static server and API proxy for Cloud Run
├── data/
│   ├── ontology/            # document types, relations, hierarchy (working assumption)
│   ├── schemas/             # PostgreSQL migrations (0001–0006) and BigQuery / Spanner DDL
│   └── synthetic/           # mock corpus and e-files; ground truth for evaluation only
├── data_collection/         # public-corpus collection tools (the corpus lives outside the repo)
├── evaluation/              # harness, datasets and checks (see evaluation/README.md)
├── infrastructure/
│   ├── gcp/                 # numbered GCP setup and deploy scripts, OPERATIONS.md
│   └── local/               # Docker Compose stack and smoke test
├── IMPLEMENTATION_PLAN.md   # the design (Final / v5, with dated amendments)
├── SECURITY.md              # security policy
└── Makefile                 # setup, run, check, eval, frontend targets
```

Application code under `backend/app/` never reads the ground truth in
`data/synthetic/…/ground_truth/`.

---

## Getting started

### Prerequisites

- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
- Node.js 20+ and npm
- Docker with Compose (optional, for the full local stack)
- Google Cloud SDK (only for cloud runs and deployment)

### Run the sandbox locally (no cloud access needed)

```bash
cp .env.example .env            # placeholders only; never commit real values
make setup                      # backend dependencies
make run                        # API on http://localhost:8080 (OpenAPI at /docs)

# in a second terminal
make fe-install                 # pinned npm dependencies
make fe-dev                     # UI on http://localhost:5173
```

Set `C2_SANDBOX=true` in `.env` for the mock sign-in, and `C2_LLM_PROVIDER=recorded` to replay
recorded model output instead of calling Vertex AI. Without a model the assistant still answers:
file tools and cited statements work, and the model steps fall back as described above.

### Full local stack

```bash
docker compose -f infrastructure/local/compose.yaml up --build   # PostgreSQL, migrations, API, UI
bash infrastructure/local/smoke.sh                                # end-to-end checks
```

With PostgreSQL state, migrations in `data/schemas/postgres/` (including `0006_chat_history`) are
applied at start; on Cloud SQL, apply them and the grants in `infrastructure/gcp/12_cloudsql_schema.py`.

---

## Testing and evaluation

```bash
make check       # ruff, strict mypy, pytest (real-Postgres tests run when C2_TEST_PG_DSN is set)
make fe-check    # TypeScript, Vitest, production build
make eval        # evaluation harness → evaluation/reports/ (exits 1 on any disclosure)

# chat intent and answer layout; add --live to call Gemini (billed)
cd backend && env -u VIRTUAL_ENV uv run python ../evaluation/conversation_check.py
```

Heavy and billed suites run on GCP as a Cloud Run Job (`infrastructure/gcp/32_eval_job.sh`), so
no laptop needs the corpus. Other suites — cross-officer leakage matrix, conflict detection, cited answers on the golden set,
RAGAS groundedness, cloud-store parity, L2 calibration — are listed in
[evaluation/README.md](evaluation/README.md). Scripts that call cloud services are billed and are
run only with the owner's approval. Before a release that changes prompts, the model's role,
retrieval or access, the full regression runs with Gemini and is compared with the baseline.

---

## Results

Synthetic e-files and public orders; measured on the dates shown. Reports are kept by the team
(`evaluation/reports/`, not in this repository).

| Measure | Result | Date |
|---|---|---|
| Unauthorised disclosures, cross-officer matrix (seed v2, 21 officers, every assistant path incl. drafting) | **0 / 90,636** checks | 24 Nov 2026 |
| Unauthorised disclosures, regression harness | **0 / 1,190** checks | 24 Nov 2026 |
| Retrieval, golden set (27 questions, in-memory stores) | Recall@5 0.723 · Recall@10 0.765 · Precision@5 0.282 · MRR 0.833 · NDCG@10 0.719 · ladder-level accuracy 0.727 | 24 Nov 2026 |
| Conflict detection A / C / E / F | Precision 1.000 · recall 1.000 · clean-control false flags 0 | 24 Nov 2026 |
| e-Office touchpoint scenarios | 24 / 24 · opposite scenarios 20 / 20 | 24 Nov 2026 |
| RAG quality (RAGAS, 17 questions; judge from the same model family) | Faithfulness 1.000 · groundedness 1.000 · answer relevancy 0.762 · context recall 0.877 · citation correctness 1.000 | 19 Nov 2026 |
| Chat checks (gates; recorded model) | 0 off-list intents · 0 forbidden records · 0 statements lost or duplicated | 24 Nov 2026 |
| Leak check on GCP (c2-eval, MODE=all) | **0 / 90,636** checks, 21 officers, 203 files | 25 Nov 2026 |
| Conversation check on GCP (live Gemini) | 0 critical failures (42 intents, 27 chat questions, 65 file-chat questions, small talk) | 25 Nov 2026 |
| RAGAS on GCP (live Gemini, same judge as 19 Nov) | Faithfulness 0.992 · groundedness 1.000 · answer relevancy 0.735 (below the 0.762 baseline; under investigation) | 25 Nov 2026 |

Precision@5 is lower than the 24-question figure (0.295) only because three harder questions were
added; on the same 24 questions it is 0.305.

---

## Deployment

Cloud resources live in project `use-case-24-project`, region `asia-south1`; services `c2-api` and
`c2-frontend` on Cloud Run. Scripts in `infrastructure/gcp/` are numbered and dry-run by default
(`APPLY=1` executes).

```bash
# API (from infrastructure/gcp): build, then deploy with the agreed settings
APPLY=1 bash 20_api_service.sh
# screens: build and deploy only; existing access settings are kept
PART=dev APPLY=1 bash 23_frontend_service.sh
# inspect the API without the browser (needs Cloud Run access)
gcloud run services proxy c2-api --project use-case-24-project --region asia-south1 --port 8080
curl http://localhost:8080/readyz
```

- A redeploy changes image, environment and size only. Who can reach a service (authentication,
  IAP, ingress, IAM) is set by the platform administrators; any change is agreed with them first
  and then run with `SECURITY_CHANGE=approved` (see `infrastructure/gcp/OPERATIONS.md`).
- Billed operations (deploys, cloud evaluation runs, calibration) are run by the project owner.

---

## Documentation

| Document | Purpose |
|---|---|
| [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) | The design; § numbers are referenced in code and docs; dated amendments inline |
| [SECURITY.md](SECURITY.md) | Security policy |
| [evaluation/README.md](evaluation/README.md) | Evaluation suites, commands and pass criteria |
| [infrastructure/gcp/OPERATIONS.md](infrastructure/gcp/OPERATIONS.md) | Recurring checks, backups, smoke checks, access-settings rule |
| [frontend/README.md](frontend/README.md) | Screens and local frontend work |

Team records are kept on the team's machines and are not in this repository: the progress log and
task ledger, architecture decision records (ADR-0001 onwards, cited by number in code comments),
learnings, the agent contract, design PDFs and run reports.

---

## Known limitations

- Synthetic and public data only; department hierarchy, numbering and access rules are unconfirmed.
- No live e-Office integration; the connector is exercised only by the mock.
- L2 early exit is off until a calibration meets its bar.
- Retrieval metrics are from the in-memory sandbox stores, not the cloud stores.
- The RAGAS judge is from the same model family as the generator. Answer relevancy (0.735 on
  25 Nov) is below the 19 Nov baseline (0.762) and golden question Q05 is not answered; both are
  under investigation.
- Only `gemini-3.5-flash` and `gemini-3.5-flash-lite` are served in `asia-south1` (checked
  25 Nov); the Gemini 4 models are not, and the system does not call models outside the region.
- A scan confirmed in the OCR review screen is searchable at once on the running service, but
  reaches the BigQuery passages table and the cloud graph only at the next batch job.
- Live drafts send 61–95 BigQuery queries (38–69 s) since 25 Nov; the request log now names the
  step behind each query, to batch it.
- The live model's intent accuracy is measured by `conversation_check.py --live`; the fixed rules
  alone route 32 of 39 test phrasings correctly.
- Chat history, OCR review decisions made in the app and per-officer daily model limits are in
  memory unless PostgreSQL state is configured, so they reset when the service restarts.

---

## Contributing

- Read the engineering contract first (build order, security rules, definition of done).
- One logical change per commit, message `<area>: <what> (plan §x.y)`; commit only when
  `make check`, `make fe-check` and the leakage suite pass.
- Record decisions as ADRs and update the progress log at the end of every task.
- Never commit secrets, real departmental data, or edits to golden answers.

---

## License

Built under the TechBharat AI CoE Fellowship for the Government of Andhra Pradesh. All rights
reserved; for fellowship evaluation only.
