# ADR-0029 — Conversation orchestrator on LangGraph, session memory in Cloud SQL, query log, injection hardening

- **Date:** 15 Nov 2026 · **Status:** Accepted (owner, 15 Nov 2026: "build other building blocks according to
  plan" while cloud access waits) · **Plan:** §3.4, §5.5, §8.1, §10.1, §10.2, §10.4, §10.6, §13.4 · **Milestones:**
  M6, M7, M8

## Decisions
1. **One LangGraph graph per turn over the one typed `AgentState`** (`app/agents/orchestrator.py`, `POST
   /assist/chat`): scope → recall → understand → cache → answer → remember, the order of plan §10.6. The graph
   keeps nothing between turns; each node reads and writes `AgentState` (new fields: `turn`, `recalled`,
   `cache_hit`, `outcome`, `result`).
2. **Intent by fixed rules, not a model** (plan §5.6): e-File number → conflict check; named order + status words
   → status; named order + "replaced" → supersession chain; "para / say" → clause lookup; … The model never picks
   a template.
3. **Session memory instead of a LangGraph checkpointer.** Plan §10.1 names the LangGraph Postgres
   checkpointer. Because a turn is one complete graph run, there is no paused graph state to checkpoint; what must
   carry over is the conversation's entities. They live in `session_owners` / `session_turns` (migration 0003,
   Cloud SQL; in memory in the sandbox), keyed by (user_id, session_id), IDs and metadata only. The store is the
   one the plan names (Postgres, not Redis); only the mechanism differs. A follow-up ("that order") uses earlier
   entities only after they are re-checked against the officer's access NOW; another officer's session ID gives a
   fresh session and no hint. The app account may insert and read turns, never edit or delete them.
4. **Scoped answer cache in the loop** (plan §10.2 layer 2): key = canonical query (with the named / recalled
   entity IDs) + scope signature + as-of date; only confirmed answers with nothing awaiting review are cached; the
   ingestion pipeline already drops entries that cite a changed document.
5. **Query log** (plan §10.4): one `QueryRecord` per turn, fields from `AgentState`. **The question text is not
   stored** — a hash of its normalised form and its intent are (plan §10.4 lists raw_query; CLAUDE.md §4.11 and
   the audit rule "never the question or the answer text" were judged to win; the hash still counts repeats). In
   memory in the sandbox; `C2_QUERY_LOG=bigquery` streams to `<project>.c2_audit.query_log` (day-partitioned,
   `21_query_log_table.sh`), needing table write on that dataset only. A failed insert never breaks an answer.
6. **"Draft the noting using that precedent"** (plan §10.1 golden path): with the open file's Computer No., the
   chat returns the first-cut points (touchpoint 6) with the conversation's re-checked precedents added. A
   preview; inserting stays the officer's click.
7. **Prompt-injection hardening found by the new suite** (plan §5.5, §13.4): with a model that OBEYS planted
   instructions, two statements were confirmed because the planted text itself contained the words the
   instruction asked to be quoted. A passage containing text addressed to an AI system (fixed patterns: "ignore
   previous instructions", a role label opening a line, evidence-fence tags, "cite evidence", "quote exactly",
   tool-like calls) is now marked `addressed_to_ai`: it is still passed on as data (the prompt marks it), but **no
   statement may cite it**, and the officer gets a notice naming the record. False positives: 0 across all 1,374
   public orders and 544 synthetic texts (a first pattern caught cadre names like "Senior Assistant:" and was
   narrowed).

## Consequences / limits
- The pattern list is a heuristic layer on top of the structural defence (fenced data, package-only citations,
  verifier); a new phrasing can pass it, and then the structural defence is what holds (the suite proves it holds
  with an obedient model).
- Memory recall drops entities whose tags are not in memory (cloud-only public orders): a follow-up about such an
  order must name it again.
- No frontend yet for the chat; the sandbox screens call the touchpoint endpoints.
