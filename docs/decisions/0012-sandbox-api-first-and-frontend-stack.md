# ADR-0012: Mock e-Office sandbox — API first, Vite + React + TypeScript screens

- **Date:** 2026-11-04
- **Status:** Accepted (owner, 4 Nov 2026)
- **Plan section:** §11.1–§11.5, §2 (React + TypeScript), P8; CLAUDE.md §2.4

## Context
P8 builds the mock e-Office sandbox and the touchpoints. It needs a backend surface for the screens, a frontend toolchain, a way to sign in without Parichay, ladder thresholds while `runtime.yaml` is still uncalibrated, and a way for the connector to hand the sandbox's documents to ingestion.

## Decision
1. **API first** (owner): sandbox and assist routes in the existing FastAPI service, tested per officer over HTTP, before any screens.
2. **Frontend tooling** (owner): Vite + React + TypeScript with plain CSS and Vitest, in `frontend/eoffice/`. Built as static files; served by Cloud Run later.
3. **Simulated sign-in:** the `X-Sandbox-User` header, accepted only when the sandbox is enabled and only for sandbox profiles that have a login. The core assist router takes an injected `identify(request)`, so IAP replaces it on GCP without touching the routes.
4. **Sandbox thresholds:** `backend/config/sandbox.yaml` holds the evaluation's test values (top-K 10, minimum score 1.0, 2 hops), labelled not calibrated. They are used only while `runtime.yaml` is uncalibrated and the connector is the mock adapter, and every assist response says `"calibrated": false`.
5. **Connector addition:** `EOfficeConnector.documents()` → `SourceArtefact` (bytes + the e-Office's access tags), the initial load for ingestion. It is additive to ADR-0009. The mock reads only the source-system columns of the corpus index (file, department, section, classification, e-File number).
6. **Stricter than e-Office:** the sandbox file screens also require clearance ≥ file classification, so the demo never shows more than C2-24 would.
7. **Composition root:** only `app/main.py` imports `app.eoffice_mock`; the boundary test allows exactly that file.

**Update (4 Nov 2026, security):** `npm audit` found 5 advisories (2 critical) in the dev/test tools vite 5.4.11 and vitest 2.1.8 (dev-server request forgery and `server.fs.deny` bypasses, an esbuild dev-server issue, tinypool / @vitest/mocker code-execution gadgets). They run only during development; the static build ships none of them. Bumped to the oldest releases outside every advisory range that are at least two weeks old: **vite 6.4.5** (21 Oct 2026) and **vitest 4.1.12** (15 Oct 2026); `overrides` pins every copy of vite to 6.4.5 (npm otherwise pulls a second vite for vitest and crashes resolving its optional peers). `npm audit` → 0 vulnerabilities. React, plugin-react and TypeScript unchanged.

**Update (4 Nov 2026, touchpoints 2–3):** the connector gains `receipt_context(computer_no, user_id) → ReceiptContext` (diary metadata only; unknown and unreachable receipts are indistinguishable). Additive; the mock derives a receipt's department from its dealing section.

**Update (4 Nov 2026, touchpoint 4):** the connector gains `open_files()` (e-File numbers of open files, for reconciliation notices). Sandbox replays: `backend/config/sandbox.yaml` names letters held back at startup (`C2_SANDBOX_REPLAY=tp04`); the mock adapter withholds them from `documents()` until "Letter arrives", then raises `ORDER_RECEIVED`. The core only consumes events (`AssistRuntime.sync`) — it never knows about replays.

## Alternatives considered
| Option | Why not |
|---|---|
| API and screens together | Bigger change; the owner chose API first |
| Next.js | Second server process and server rendering the sandbox doesn't need |
| Refuse to run assist calls until calibration | No demo or touchpoint testing possible before GCP; labelled demo values are transparent instead |

## Consequences
- Touchpoints 10, 11 and 15 run end to end over HTTP; the leakage sweep covers the API.
- Node 20+ is needed on the developer machine for slice 2.
- When calibrated values land in `runtime.yaml`, the sandbox uses them automatically and reports `"calibrated": true`.

## Mentor input (if any)
None yet.
