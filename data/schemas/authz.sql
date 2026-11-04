-- Access store for C2-24 (plan §5.1, §5.8; ADR-0009). Cloud SQL for PostgreSQL, schema `authz`.
-- Permissions are relationship tuples, read on every request; documents carry only location tags.
-- MOCK policy values are loaded from data/ontology/access_policy.yaml. Nothing here is real department data.
-- Not yet applied to any database (GCP access pending); syntax checked with libpg_query (pglast).

CREATE SCHEMA IF NOT EXISTS authz;

-- Who can see what: (subject, relation, object), e.g. ('user:U04','assigned','file:USD01-31/4/2025-VIG').
CREATE TABLE IF NOT EXISTS authz.access_tuple (
    subject     text        NOT NULL CHECK (subject ~ '^user:[A-Za-z0-9_-]+$'),
    relation    text        NOT NULL CHECK (relation IN (
                    'member_of', 'in_section', 'has_clearance', 'has_rank',
                    'has_search_scope', 'assigned', 'handled')),
    object      text        NOT NULL CHECK (object ~ '^(department|section|clearance|rank|scope|file):.+$'),
    granted_by  text        NOT NULL,                -- officer or sync job that wrote the grant
    granted_at  timestamptz NOT NULL DEFAULT now(),
    source      text        NOT NULL DEFAULT 'eoffice_sync',  -- eoffice_sync | admin | mock_seed
    PRIMARY KEY (subject, relation, object)
);
CREATE INDEX IF NOT EXISTS access_tuple_subject_idx ON authz.access_tuple (subject);

-- One department / clearance / rank / section per user (StoreError otherwise → deny).
CREATE UNIQUE INDEX IF NOT EXISTS one_department_per_user ON authz.access_tuple (subject)
    WHERE relation = 'member_of';
CREATE UNIQUE INDEX IF NOT EXISTS one_clearance_per_user ON authz.access_tuple (subject)
    WHERE relation = 'has_clearance';
CREATE UNIQUE INDEX IF NOT EXISTS one_rank_per_user ON authz.access_tuple (subject)
    WHERE relation = 'has_rank';
CREATE UNIQUE INDEX IF NOT EXISTS one_section_per_user ON authz.access_tuple (subject)
    WHERE relation = 'in_section';

-- Every grant and revocation is kept (plan §10.4 audit); never deleted.
CREATE TABLE IF NOT EXISTS authz.access_tuple_log (
    id          bigserial   PRIMARY KEY,
    action      text        NOT NULL CHECK (action IN ('grant', 'revoke')),
    subject     text        NOT NULL,
    relation    text        NOT NULL,
    object      text        NOT NULL,
    actor       text        NOT NULL,
    at          timestamptz NOT NULL DEFAULT now(),
    reason      text
);

-- Monotonic store version: bumped on every change (cache diagnostics, AuthzStore.version).
CREATE TABLE IF NOT EXISTS authz.store_version (
    id      smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    version bigint   NOT NULL DEFAULT 0
);
INSERT INTO authz.store_version (id, version) VALUES (1, 0) ON CONFLICT (id) DO NOTHING;

-- Where each document lives (NOT who may read it). Mirrors DocumentAccessTags; filterable in every index.
CREATE TABLE IF NOT EXISTS authz.document_location (
    doc_id          text PRIMARY KEY,
    canonical_id    text NOT NULL UNIQUE,
    department      text NOT NULL,
    section         text,
    classification  text NOT NULL,
    file_no         text
);
CREATE INDEX IF NOT EXISTS document_location_scope_idx
    ON authz.document_location (department, classification, section);
CREATE INDEX IF NOT EXISTS document_location_file_idx ON authz.document_location (file_no);

-- Tier 2 (plan §5.8): row-level security on document_location using the session's scope.
-- The application sets these per transaction from compute_scope(); unset → no rows (fail closed).
ALTER TABLE authz.document_location ENABLE ROW LEVEL SECURITY;
CREATE POLICY scope_filter ON authz.document_location FOR SELECT USING (
    classification = 'UNCLASSIFIED'
    OR (
        department = current_setting('c2.scope_department', true)
        AND (
            current_setting('c2.scope_department_wide', true) = 'true'
            OR section = ANY (string_to_array(current_setting('c2.scope_sections', true), ','))
            OR file_no = ANY (string_to_array(current_setting('c2.scope_files', true), '|'))
        )
        AND classification = ANY (string_to_array(current_setting('c2.scope_classes', true), ','))
    )
);
