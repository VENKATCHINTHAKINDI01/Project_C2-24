"""Session memory (plan §10.1).

Implemented: in-memory `SessionMemory` keyed by (user_id, session_id), IDs only, scope re-applied
on every recall (`session`); the same in Cloud SQL (`pg_session`, migration 0003, ADR-0029).
The LangGraph graph itself runs one turn per request, so it needs no checkpointer: what carries
over between turns is this memory (IDs only), re-checked every turn.
"""
