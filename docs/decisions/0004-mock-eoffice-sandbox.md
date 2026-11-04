# ADR-0004: Demo inside a mock e-Office sandbox via EOfficeConnector

- **Date:** 2026-10-13
- **Status:** Accepted
- **Plan section:** §11

## Context
No authorised access to the production e-Office for the PoC, but officers work inside e-Office.

## Decision
Build a clearly labelled mock e-Office sandbox (simulated eFile screens) that reaches the core only through an EOfficeConnector interface; assistant writes drafts only.

## Alternatives considered
| Option | Why not |
|---|---|
| Standalone UI only | Does not show how officers would use it in daily work |
| Scraping / automating the live portal | Not authorised; security and policy risk |

## Consequences
A real adapter (authorised export or official API) can replace the mock without core changes. Sandbox scope limited to touchpoint screens.

## Mentor input (if any)
Mentor reviewed the changes since the first call and found them satisfactory (13 Oct 2026).
