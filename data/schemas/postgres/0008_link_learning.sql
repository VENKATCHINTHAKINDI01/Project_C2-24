-- Link learning (ADR-0074): officers' signals on a link between two orders, and their explicit
-- decisions. Append-only for the API. IDs, posts, codes and the one sentence of the newer order the
-- validating officer relied on; never note text or answers.
CREATE TABLE IF NOT EXISTS link_signals (
    id              BIGSERIAL PRIMARY KEY,
    at              TIMESTAMPTZ NOT NULL,
    request_id      TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    post            TEXT NOT NULL,       -- as at the time of the signal
    department      TEXT NOT NULL,
    source          TEXT NOT NULL,       -- the newer order (canonical ID)
    kind            TEXT NOT NULL,
    target          TEXT NOT NULL,       -- the older order
    code            TEXT NOT NULL,       -- useful | not_right | … (ADR-0074 §3)
    weight          INTEGER NOT NULL,
    reason          TEXT,
    file_no         TEXT,
    test            BOOLEAN NOT NULL DEFAULT FALSE,
    automated       BOOLEAN NOT NULL DEFAULT FALSE,
    config_version  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS link_signals_link ON link_signals (source, kind, target);
CREATE TABLE IF NOT EXISTS link_decisions (
    id              BIGSERIAL PRIMARY KEY,
    at              TIMESTAMPTZ NOT NULL,
    request_id      TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    post            TEXT NOT NULL,       -- designation at the time of the decision
    department      TEXT NOT NULL,
    source          TEXT NOT NULL,
    kind            TEXT NOT NULL,
    target          TEXT NOT NULL,
    action          TEXT NOT NULL CHECK (action IN ('validate', 'reject', 'request_evidence')),
    reason          TEXT NOT NULL,
    evidence        TEXT,                -- the newer order's sentence, checked against its text
    config_version  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS link_decisions_link ON link_decisions (source, kind, target);
INSERT INTO schema_migrations (version) VALUES ('0008_link_learning') ON CONFLICT (version) DO NOTHING;
