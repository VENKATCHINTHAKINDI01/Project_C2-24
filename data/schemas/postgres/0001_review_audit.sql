-- C2-24 application state in Cloud SQL (PostgreSQL 16) — migration 0001.
-- Review decisions (plan §4.2, CLAUDE.md §8), reviewer-confirmed text, and the audit trail
-- (plan §10.4, CLAUDE.md §4.11). Idempotent: safe to apply again.

CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE SEQUENCE IF NOT EXISTS review_item_seq;

-- One row per (kind, subject, version): re-ingesting the same file never adds a duplicate.
CREATE TABLE IF NOT EXISTS review_items (
    item_id          TEXT PRIMARY KEY,
    kind             TEXT NOT NULL,
    subject          TEXT NOT NULL,          -- document / relation / reference ID, never text
    version          TEXT NOT NULL,
    reason           TEXT NOT NULL CHECK (length(reason) <= 500),
    created_at       TIMESTAMPTZ NOT NULL,
    state            TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'confirmed', 'rejected')),
    reviewer         TEXT,
    decided_at       TIMESTAMPTZ,
    decision_reason  TEXT CHECK (decision_reason IS NULL OR length(decision_reason) <= 500),
    UNIQUE (kind, subject, version),
    CHECK ((state = 'pending') = (reviewer IS NULL AND decided_at IS NULL AND decision_reason IS NULL))
);
CREATE INDEX IF NOT EXISTS review_items_pending ON review_items (kind) WHERE state = 'pending';
CREATE INDEX IF NOT EXISTS review_items_subject ON review_items (subject, version);

-- Text a reviewer confirmed or corrected for a scanned file version (what gets indexed).
-- Application data, not a log: never copied to general logs (CLAUDE.md §4.11).
CREATE TABLE IF NOT EXISTS confirmed_texts (
    version      TEXT PRIMARY KEY,
    text         TEXT NOT NULL,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Audit trail: IDs and outcomes only, append-only (enforced below).
CREATE TABLE IF NOT EXISTS audit_events (
    seq         BIGSERIAL PRIMARY KEY,
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    request_id  TEXT NOT NULL,
    user_id     TEXT,
    action      TEXT NOT NULL,
    outcome     TEXT NOT NULL,
    ids         TEXT[] NOT NULL DEFAULT '{}',
    detail      TEXT NOT NULL DEFAULT '' CHECK (length(detail) <= 200)
);
CREATE INDEX IF NOT EXISTS audit_events_user ON audit_events (user_id, at);

CREATE OR REPLACE FUNCTION audit_events_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_events is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_events_no_change ON audit_events;
CREATE TRIGGER audit_events_no_change BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();

INSERT INTO schema_migrations (version) VALUES ('0001_review_audit') ON CONFLICT DO NOTHING;
