"""Session memory (plan §10.1).

Implemented: in-memory `SessionMemory` keyed by (user_id, session_id), IDs only, scope re-applied
on every recall (`session`). Not yet: LangGraph Postgres checkpointer (Cloud SQL, needs GCP).
"""
