-- Model usage (ADR-0060 addendum): a per-officer daily count of optional model calls (suggested
-- draft wording), shared by every API instance so the limit holds across restarts and scale-out,
-- and a log of each such call. IDs, outcomes and counts only: never the officer's text, the prompt
-- or the model's answer.
CREATE TABLE IF NOT EXISTS model_usage_daily (
    user_id  TEXT NOT NULL,           -- the authenticated officer (e-Office user ID)
    day      DATE NOT NULL,           -- calendar day in IST
    action   TEXT NOT NULL,           -- e.g. 'draft.wording'
    calls    INTEGER NOT NULL,
    PRIMARY KEY (user_id, day, action)
);
CREATE TABLE IF NOT EXISTS model_usage_log (
    id          BIGSERIAL PRIMARY KEY,
    at          TIMESTAMPTZ NOT NULL,
    request_id  TEXT NOT NULL,
    user_id     TEXT NOT NULL,
    action      TEXT NOT NULL,
    outcome     TEXT NOT NULL,        -- ok | daily_limit | usage_unavailable | engine_down | all_removed | …
    engine      TEXT,                 -- model@location, or NULL when no call was made
    prompt_id   TEXT,
    target      TEXT,                 -- the file's Computer No., or 'new'
    kept        INTEGER NOT NULL DEFAULT 0,
    removed     INTEGER NOT NULL DEFAULT 0,
    used_today  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS model_usage_log_user_at ON model_usage_log (user_id, at);
INSERT INTO schema_migrations (version) VALUES ('0005_model_usage') ON CONFLICT (version) DO NOTHING;
