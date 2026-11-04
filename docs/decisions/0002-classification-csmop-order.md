# ADR-0002: Classification order follows CSMOP grading

- **Date:** 2026-10-02
- **Status:** Accepted
- **Plan section:** §4.4, §5.1

## Context
Earlier draft placed RESTRICTED as the highest level, the reverse of the government grading.

## Decision
Use UNCLASSIFIED(0) < RESTRICTED(1) < CONFIDENTIAL(2) < SECRET(3); keep it configurable until the department confirms its real levels.

## Alternatives considered
| Option | Why not |
|---|---|
| PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED | Conflicts with standard government grading |

## Consequences
Mock corpus and access matrix already use this order. [To confirm with department]

## Mentor input (if any)
—
