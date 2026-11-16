# ADR-0035: Monitoring officer's pad, question log, Redis (Memorystore) cache

- **Date:** 2026-11-15
- **Status:** Accepted (owner request 15 Nov 2026: a separate officer who sees all activity, the questions
  asked and the most frequent ones, on a monitoring pad only they can open; Redis for caching)
- **Plan section:** §10.2 (cache layers), §10.4 (query log incl. raw_query, FAQ analytics, access-aware
  views), CLAUDE.md §2.2 (Memorystore = cache only), §4.8, §4.11

## Context
The query log kept IDs and a hash of each question (ADR-0029), so nobody could see what officers asked.
Plan §10.4 lists `raw_query` and FAQ analytics and requires the aggregate views to be access-aware. The
answer cache lived in one instance's memory: lost on restart, not shared.

## Decision
- **Monitoring officer:** a mock profile `M01` (sandbox.yaml `monitoring.officers`; more by
  `C2_MONITORING_USERS`). No files of their own (search scope: individual). The pad
  (`GET /assist/monitor`) and `GET /assist/usage` exist only for them; everyone else gets the same 404 as
  an unknown route. The screen asks `GET /assist/me/roles` whether to show it.
- **Question words in the log:** `question` (the officer's words, max 500 chars, never document text) and
  `clearance_rank` (the asker's clearance) on each query-log record; `C2_QUERY_LOG_TEXT=false` turns it off.
  **Access-aware:** the pad shows a question's words only if the monitoring officer's clearance is at least
  the asker's; otherwise the row stays and the words are withheld. M01 is SECRET in the mock, so sees all.
- **The pad:** overview (questions, answered, no-answer and cache-hit rates, median/90th-percentile answer
  time, feedback, last start), questions per day, answer time per day, outcomes, search step that
  answered; tabs for the activity log (filter, CSV export), frequent questions (grouped by the normalised
  question), unanswered questions (gaps), officers, slowest answers, feedback, cache. Live refresh 30 s.
  Built from the same rows in memory or BigQuery (fixed SQL; window date and a 5,000-row limit).
- **Redis (Memorystore), cache only:** `RedisAnswerCache` — the same key as before (hash of canonical query +
  scope signature: identical permissions share, different never), every entry listed under each record it
  cites and dropped when one changes, TTL 6 h as a backstop; `CachedEmbedder` — a question's vector by a
  content hash (user-agnostic), TTL 7 days. Short timeouts; any Redis error bypasses the cache; a failed
  invalidation stops this instance serving cached answers until restart. Unset `C2_REDIS_URL` = in-memory.
- **Infrastructure:** `24_memorystore.sh` (Basic 1 GB, private IP, AUTH; the URL with the AUTH string goes
  to Secret Manager `c2-redis-url`, readable by c2-api only; needs `I_ACCEPT_COST=1`), `20_api_service.sh`
  `REDIS=1` (secret + Direct VPC egress, private ranges only), `25_query_log_columns.sh` (adds the two
  columns; run before deploying, or the new rows are rejected by BigQuery).

## Alternatives considered
| Option | Why not |
|---|---|
| Show every question to the monitor regardless of clearance | Plan §10.4 requires access-aware views; a SECRET-file question could reach someone not cleared |
| Keep hashes only | The owner wants the questions; FAQ analytics need the words |
| A separate restricted table for question text | Same dataset permissions in the PoC; the access rule is enforced where the words are shown |
| Redis as the session store | CLAUDE.md §2.3 forbids it; sessions stay in Cloud SQL |
| Cache Gemini responses in Redis | Possible later (content-hash keys); answer + embedding caches cover repeats now |

## Consequences
- Memorystore bills while it exists (~USD 35–50/month, Basic 1 GB); the app works without it.
- Redis helps repeated questions (answer cache) and repeated wording (embedding); a first-time question
  still needs retrieval and the model.
- The query log now holds officers' words: retention and who may read the BigQuery dataset are owner
  decisions [To confirm with department].

## Mentor input (if any)
None.
