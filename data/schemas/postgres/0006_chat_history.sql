-- Chat history (ADR-0066): each officer's conversations with the assistant, so they can see and
-- continue them after a reload or a new sign-in. The officer's own: one owner per conversation;
-- the API re-checks access on every read (a stored answer citing a record the officer may no
-- longer see is withheld). Not a record: never read by ingestion, search or the query log.
CREATE TABLE IF NOT EXISTS chat_conversations (
    conversation_id TEXT PRIMARY KEY,      -- = the conversation's session id
    user_id         TEXT NOT NULL,
    place           TEXT NOT NULL,         -- a file's Computer No., or 'all' (general chat)
    title           TEXT NOT NULL,         -- the first question, shortened
    updated_at      TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS chat_conversations_user ON chat_conversations (user_id, updated_at DESC);
CREATE TABLE IF NOT EXISTS chat_turns (
    conversation_id TEXT NOT NULL REFERENCES chat_conversations (conversation_id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    body            TEXT NOT NULL,         -- JSON: question, answer as shown (or the tool asked), cited IDs
    PRIMARY KEY (conversation_id, seq)
);
INSERT INTO schema_migrations (version) VALUES ('0006_chat_history') ON CONFLICT (version) DO NOTHING;
