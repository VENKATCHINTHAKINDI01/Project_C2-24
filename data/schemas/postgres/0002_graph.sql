-- C2-24 knowledge graph in Cloud SQL (PostgreSQL 16) — migration 0002 (ADR-0023).
-- The store-agnostic relation schema of plan §3.6 behind `GraphRepository`: nodes are documents,
-- edges are relations. Spanner Graph stays the planned store; this is the plan's allowed
-- alternative while no Spanner instance exists. Idempotent: safe to apply again.
-- No document text here: IDs, access tags, dates and the subject line only.

CREATE TABLE IF NOT EXISTS graph_nodes (
    canonical_id     TEXT PRIMARY KEY,
    -- access tags (the scope decides; these are the source system's labels)
    department       TEXT NOT NULL,
    section          TEXT,
    classification   TEXT NOT NULL,
    file_no          TEXT,
    doc_id           TEXT NOT NULL,          -- the source system's reference for the file
    -- descriptive properties (set by the batch load; NULL for nodes added one by one)
    doc_type         TEXT,
    hierarchy_level  INTEGER,
    issue_date       DATE,
    effective_from   DATE,
    valid_until      DATE,
    subject          TEXT
);

CREATE TABLE IF NOT EXISTS graph_edges (
    source     TEXT NOT NULL REFERENCES graph_nodes (canonical_id),
    kind       TEXT NOT NULL,
    target     TEXT NOT NULL REFERENCES graph_nodes (canonical_id),
    confirmed  BOOLEAN NOT NULL DEFAULT TRUE,   -- stated in the text or confirmed by an officer
    PRIMARY KEY (source, kind, target)
);
CREATE INDEX IF NOT EXISTS graph_edges_target ON graph_edges (target, kind);

INSERT INTO schema_migrations (version) VALUES ('0002_graph') ON CONFLICT (version) DO NOTHING;
