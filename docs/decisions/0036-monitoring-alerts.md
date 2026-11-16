# ADR-0036: Unusual-activity alerts for the monitoring officer

- **Date:** 2026-11-15
- **Status:** Accepted for the PoC (owner request 15 Nov 2026: the monitoring officer should notice unwanted
  activity, out-of-scope questions and suspicious activity across departments). **Thresholds, patterns and
  the policy itself are MOCK**: the department decides what counts as unusual, who may see it and what
  happens after an escalation. Staff notice of monitoring is also the department's matter.
- **Plan section:** §4 (security: refusals, prompt injection, never confirm existence), §10.4 (audit, query
  log, access-aware views), CLAUDE.md §4.7, §4.10, §4.11, §4.13, §8
- **Builds on:** ADR-0016 (same 404), ADR-0029 (query log), ADR-0031 (fixed-code human actions), ADR-0035
  (monitoring pad, question words gated by clearance)

## Context
The pad (ADR-0035) shows every question but nothing points the monitoring officer at what needs a look:
someone asking again and again for records outside their access (probing), questions that try to instruct
the assistant (prompt injection / jailbreak), requests for everything at once, attempts to open the pad
itself, questions that have nothing to do with the assistant's work, unusual volume or hours.

## Decision
1. **Signals on each question, fixed codes only**, computed by deterministic rules and written to the query
   log (`flags`, REPEATED STRING; never text):
   - `instruction_like`: words that read as instructions to the assistant (patterns in
     `backend/config/monitoring.yaml`, written to avoid ordinary official phrasing such as "act as the
     competent authority" or "override the permission given");
   - `bulk_request`: everything at once, or records by restriction ("all confidential …");
   - `named_unavailable`: the question cites an order and no reading of it resolves to a record the
     officer may open. **Hidden and non-existent give the same code**, so the monitor learns nothing about
     existence either (ADR-0016);
   - `off_topic`: no answer, nothing named, nothing found, and none of the subject words in the config.
2. **Refused requests** come from the audit trail (`outcome` "denied" / "not_available": who, when, which
   kind of request; IDs are not passed on). A non-monitor calling `/assist/monitor`, `/assist/usage` or
   the review route still gets the same 404 as an unknown route, and the attempt is now recorded.
3. **Alerts are worked out when the pad opens** (`app/tracking/signals.py` `build_alerts`), per officer per
   day, with a stable ID (hash of rule, officer, day) so a review stays attached:

   | Rule | Severity | When |
   |---|---|---|
   | `pad_probe` | high | any refused call to the monitoring routes |
   | `instruction_like` | high | any such question |
   | `repeated_refusals` | high | ≥ 5 refused requests (pages + `named_unavailable` questions) within 30 min |
   | `bulk_request` | medium | any |
   | `volume_spike` | medium | > 40 questions in any 60 min |
   | `off_topic` | medium if ≥ 3 in a day, else low | — |
   | `named_unavailable` | low | when `repeated_refusals` did not fire that day |
   | `after_hours` | low | questions outside 08:00–20:00 IST |

   All numbers are MOCK (`monitoring.yaml` version `0.1-mock`).
4. **Across departments:** counts by department (high / medium / low, open, officers) and by rule. The
   monitor sees every department's alerts; a question's words appear only where the monitor's clearance
   covers the asker (ADR-0035 rule, reused).
5. **Review, not action:** `POST /assist/monitor/alerts/{id}/review` with `reviewed` (optional reason
   `expected_activity`) or `escalated` — fixed codes, stored as a `HumanAction` (`target_kind: alert`).
   Reviews are not officer feedback (excluded from the feedback counts). Escalation sends nothing and
   changes nobody's access: the department's own procedure takes it from there.
6. **The asker sees nothing.** Answers are identical with or without a signal; no warning, no hint.

## Alternatives considered
| Option | Why not |
|---|---|
| Ask Gemini whether a question is suspicious | A model would read every question for a security decision; CLAUDE.md §4 keeps security deterministic. Patterns are reviewable and testable |
| Separate `security_event` table | The query log and audit trail already hold what is needed; one more column (`flags`) is enough |
| Block or warn the officer on a signal | Turns an unreviewed pattern into an action against an officer and tells a prober what is watched; the plan has humans decide |
| Store alerts | Derived each time from records already kept; only the review is stored, so changing a threshold re-derives consistently |

## Consequences
- `25_query_log_columns.sh` now also adds `flags`; run it before deploying this image (same as ADR-0035).
- False positives are expected with mock patterns; reviews with `expected_activity` are evaluation data
  for tuning them (never applied automatically, CLAUDE.md §8).
- Alerts depend on the window the pad reads (≤ 5,000 query rows; ≤ 20,000 refusals from Cloud SQL).
- The sandbox v1 officers are all USD01, so the department view shows one department there; seed v2 has
  several.

## Confirmation still needed
Department: what counts as unusual, the thresholds, who may monitor, what an escalation triggers, staff
notice, how long monitoring data is kept.
