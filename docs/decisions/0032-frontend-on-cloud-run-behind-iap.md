# ADR-0032: The officer screens on Cloud Run behind IAP

- **Date:** 2026-11-15
- **Status:** Accepted (owner's instruction to put the frontend on Cloud Run; plan §2.1, §3.5)
- **Plan section:** §2.1 (React UI on Cloud Run), §3.5 (identity: IAM + IAP), §11 (mock e-Office sandbox)

## Context
The sandbox screens ran only on a laptop (Vite dev server proxying to `c2-api` through `gcloud run services
proxy`). The plan puts the React UI on Cloud Run with people reaching it through IAP. `c2-api` is private
(IAM: run.invoker), and a browser cannot attach the Google ID token Cloud Run IAM expects.

## Decision
- A second Cloud Run service, `c2-frontend` (service account `c2-frontend`), built from `frontend/Dockerfile`:
  the built screens plus a small Starlette server (`frontend/server/server.py`).
- The server forwards only `/assist/*`, `/sandbox/*` and `/healthz` to `c2-api`, adding an ID token minted for
  its own service account (run.invoker on `c2-api`, nothing else). It passes on only `content-type`, `accept`
  and the sandbox sign-in header; the browser's `Authorization`, cookies and IAP headers never reach
  `c2-api`. Responses keep only content headers, plus security headers (CSP, nosniff, no-referrer).
- People reach `c2-frontend` only through IAP, turned on directly on the Cloud Run service (`--iap`, no load
  balancer); access is `roles/iap.httpsResourceAccessor` for named members (`IAP_MEMBERS`).
- `c2-api` stays IAM-only, so scripts and evaluations keep calling it with identity tokens as before.
- The server decides nothing about access: every call is authorised by `c2-api` (sandbox profile, scope,
  re-check), as before. The sandbox sign-in (choosing an officer profile) stays simulated (plan §11.4).

## Alternatives considered
| Option | Why not |
|---|---|
| Serve the screens from `c2-api` and put IAP on it | Scripts and evaluations would then need IAP tokens; the browser-facing gate and the API would be one surface |
| nginx in front of `c2-api` | nginx cannot mint Google ID tokens for a private Cloud Run service |
| Make `c2-api` public | Removes the identity layer the plan requires (§3.5, defence in depth) |
| IAP through an external HTTPS load balancer | A Tier-3 item (CLAUDE.md §2.3); IAP on Cloud Run directly needs none |

## Consequences
- Two images and two services; `23_frontend_service.sh` builds and deploys the frontend.
- Accounts outside the organisation need an External OAuth consent screen and a custom OAuth client (console,
  once) before IAP lets them in.
- The first call after `c2-api` has been idle still waits for its cold start; the frontend waits up to 15 min.

## Mentor input (if any)
None. Who may open the demo (`IAP_MEMBERS`) is the owner's call.
