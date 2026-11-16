# ADR-0033: Streamed answers — only checked statements are streamed

- **Date:** 2026-11-15
- **Status:** Accepted (owner asked for answers that appear as they are written, like Claude's chat)
- **Plan section:** §8.1 (cited answers), §8.2 (citation check), §10.6 (conversation), §11 (sandbox UI)

## Context
A cited answer waits for retrieval, the model's whole answer and the citation check before anything is
shown. The officer sees a spinner for the whole time. Streaming the model's text as it is generated would
show claims before the citation check — which CLAUDE.md §4.12 / §7.7 forbid (unsupported claims are
withheld, never shown and then taken back).

## Decision
- `POST /assist/chat/stream` runs exactly the `/assist/chat` turn and sends Server-Sent Events:
  - `stage`: searching → found N records (rung) → writing → checking;
  - `statement` / `review`: one per statement, sent the moment its JSON object is complete in the model's
    output AND it passes the same citation check as the final answer (`verify` on that one claim:
    evidence ID in the package, still authorised, quote in the cited text). Status lines from the order
    records (no model) are sent first;
  - `done`: the full `/assist/chat` answer — authoritative; the screen replaces the streamed part with it;
  - `error`: the neutral failure message only.
- The model's raw text never leaves the server. Statements that fail the check are never streamed.
- Sign-in and access are checked before the stream opens (401/403 as for `/chat`); scope, cache, memory,
  query log and audit are the same code path as `/chat`.
- `stream_json` asks Gemini with `generate_content_stream` (same request, same JSON schema, same saved-
  answer key); clients that cannot stream (saved answers, local Ollama) hand over the whole answer at once.
- The frontend server passes the stream through unbuffered; the screen shows the stage, reveals each
  checked statement at reading pace (text present for screen readers), offers Stop, and falls back to
  `/chat` if streaming is not available.

## Alternatives considered
| Option | Why not |
|---|---|
| Stream raw model tokens, check afterwards | Shows unsupported claims before they are withheld (CLAUDE.md §4.12) |
| Only a progress indicator, no partial answer | Simpler but the officer still waits for the whole answer |
| WebSockets | Two-way channel not needed; SSE passes Cloud Run, IAP and the frontend proxy as plain HTTP |

## Consequences
- With saved answers (sandbox default) statements arrive together; the stream's benefit shows with live
  Gemini.
- If a primary model fails part-way and the fallback answers, statements already shown were checked;
  the `done` answer replaces them.
- A stopped stream leaves the turn to finish on the server (it is still remembered and logged).

## Mentor input (if any)
None.
