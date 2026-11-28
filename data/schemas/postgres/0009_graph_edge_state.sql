-- C2-24 knowledge graph edge learning state (ADR-0074 step 3; plan §3.6, §8).
-- Nightly roll-up writes state, score and documentary evidence from link_signals / link_decisions.
-- Idempotent: safe to apply again.

ALTER TABLE graph_edges ADD COLUMN IF NOT EXISTS state    TEXT;
ALTER TABLE graph_edges ADD COLUMN IF NOT EXISTS score    INTEGER NOT NULL DEFAULT 0;
ALTER TABLE graph_edges ADD COLUMN IF NOT EXISTS evidence TEXT;

INSERT INTO schema_migrations (version) VALUES ('0009_graph_edge_state')
    ON CONFLICT (version) DO NOTHING;
