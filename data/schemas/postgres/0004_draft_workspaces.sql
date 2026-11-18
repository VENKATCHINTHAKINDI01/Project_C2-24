-- Draft recovery (ADR-0046): an officer's draft workspace, saved as they work, so a power cut or a
-- dropped network does not cost them the draft. One row per officer and target (a file's Computer
-- No., or 'new' for a matter with no file yet). Scratch, not a record: never read by ingestion or
-- search; cleared when the draft is saved into the file.
CREATE TABLE IF NOT EXISTS draft_workspaces (
    user_id   TEXT NOT NULL,
    target    TEXT NOT NULL,
    body      TEXT NOT NULL,          -- JSON: format, the officer's inputs and draft text
    saved_at  TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (user_id, target)
);
INSERT INTO schema_migrations (version) VALUES ('0004_draft_workspaces') ON CONFLICT (version) DO NOTHING;
