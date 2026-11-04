"""Retrieval ladder L0-L3, templates, evidence package (plan §3.2-§3.3).

Implemented: permission-enforced L0/L1 over a reference in-memory index (`scoped`): scope from the
access store first, then the rung, then a per-document re-check; L3 scope-constrained graph
expansion (`graph_expansion`); the evidence package (`evidence`), the only content that may reach
Gemini; ladder orchestration L0 → L1 → L2 (early exit) → L3 with a per-rung trace, and a
deterministic keyword stand-in for L2 (`ladder`); cross-department reference lookup that asks
the officer when ambiguous (`references`). Not yet: BigQuery templates, Vertex AI Search.
"""
