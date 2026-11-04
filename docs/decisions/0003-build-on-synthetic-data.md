# ADR-0003: Start building on synthetic data

- **Date:** 2026-10-05
- **Status:** Accepted
- **Plan section:** §12, §16

## Context
Masked department data not yet received.

## Decision
Build and measure on the purpose-built synthetic corpus; real masked data enters the same pipeline when available.

## Alternatives considered
| Option | Why not |
|---|---|
| Wait for real data | Loses weeks; data-independent parts can be built now |

## Consequences
Metrics come from synthetic ground truth; real data validates robustness.

## Mentor input (if any)
—
