# ADR-0008: Officer roles and reporting hierarchy (provisional)

- **Date:** 2026-11-02
- **Status:** Accepted as provisional (owner, 2 Nov 2026) — re-research and confirm before use in access control
- **Plan section:** §4.5, §5.1, §11 (e-Office file movement)

## Context
The knowledge graph, file movement in the mock e-Office and access scopes need a model of who reports to whom in
Finance, GAD and School Education. No department confirmation exists (CLAUDE.md §5.9). The owner asked for a
hierarchy grounded in real data rather than invented.

## Decision
Fix `data/ontology/roles.yaml` for now: the common Secretariat chain (Minister → Chief Secretary → Secretary →
Spl/Addl/Jt/Dy Secretary → Assistant Secretary → Section Officer → ASO → support), the channel of submission
(ASO → SO → AS → DS/JS/AdS → Secretary → Minister), and per-department wings, sections, HoDs and field offices.
Every role carries evidence: official sources (Business Rules / Secretariat Instructions, Finance RTI 4(1)(b),
the Oct 2026 Educational Service Rules amendment) and counts from the public G.O. corpus (signature blocks,
addressees, section codes). It stays separate from the instrument hierarchy in `hierarchy.yaml`.

## Alternatives considered
| Option | Why not |
|---|---|
| Invent a hierarchy for the mock | Would not match real file movement; owner wants real-data grounding |
| Wait for department confirmation | Blocks graph and e-Office work |

## Consequences
Build work can use the roles now. Open: model depth, role granularity, mapping to access scope, and the update
rule when new G.O.s change posts (proposed: ingestion proposes changes, a person approves). **Reminder:** before
the graph/auth work relies on it, re-research in depth (each department's RTI 4(1)(b), org charts) and confirm.

## Mentor input (if any)
—
