-- Conversation memory (plan §10.1; ADR-0029). IDs and metadata only: never record text.
-- A session belongs to the officer who opened it; another officer can neither read nor extend it.
CREATE TABLE IF NOT EXISTS session_owners (
    session_id  TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS session_turns (
    session_id       TEXT NOT NULL REFERENCES session_owners (session_id),
    seq              INTEGER NOT NULL,
    request_id       TEXT NOT NULL,
    at               TIMESTAMPTZ NOT NULL,
    canonical_query  TEXT NOT NULL,
    entity_ids       TEXT NOT NULL,         -- JSON list of canonical IDs / file numbers
    scope_signature  TEXT,
    PRIMARY KEY (session_id, seq)
);
INSERT INTO schema_migrations (version) VALUES ('0003_sessions') ON CONFLICT (version) DO NOTHING;
