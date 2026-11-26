-- Sandbox journal (ADR-0071): the officers' actions in the MOCK e-Office (synthetic data), so the
-- sandbox survives a restart or a new deploy. Replayed in `seq` order at start-up through the same
-- adapter methods. Not a record: never read by ingestion, search or the query log.
CREATE TABLE IF NOT EXISTS sandbox_journal (
    seq     BIGSERIAL PRIMARY KEY,
    at      TIMESTAMPTZ NOT NULL,
    action  TEXT NOT NULL,
    body    TEXT NOT NULL            -- JSON: action, time, arguments
);
INSERT INTO schema_migrations (version) VALUES ('0007_sandbox_journal') ON CONFLICT (version) DO NOTHING;
