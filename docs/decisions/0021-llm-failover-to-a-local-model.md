# ADR-0021 — Fallback to a locally hosted open model when Gemini is down, with automatic return

- **Date:** 14 Nov 2026 · **Status:** Accepted (owner's request, 14 Nov 2026) · **Plan:** §2.1, §7; ADR-0017

## Context
Every model call (today: the type B / G contradiction check) goes to Gemini on Vertex AI in asia-south1. When the
call fails (outage, quota, expired sign-in) the check is reported as incomplete. The owner asked for a fallback to an
open-source model and an automatic return to Gemini when it is back. CLAUDE.md §2.1 says "Gemini on Vertex AI only"
and ADR-0017 says "never falls back to another region or model", so this is a recorded, approved change to both.

## Options
1. Hosted open models (Groq, Hugging Face): document text would leave Google Cloud India. Rejected.
2. A second model on Vertex AI in India: stays in region, but fails together with Vertex in most outages.
3. **An open model on Ollama on the same machine (owner's choice):** nothing leaves the host.

## Decision
- **Chain:** Gemini (primary) → Ollama model on this machine (fallback). Off by default: `C2_LLM_FALLBACK=ollama`
  and `C2_OLLAMA_MODEL=<model>` switch it on. The Ollama address must be loopback (`http://localhost:<port>`); any
  other host is refused at start-up.
- **Circuit breaker (`FailoverLLM`):** while closed, Gemini answers and a failed request is answered by the fallback.
  After `C2_LLM_FAILOVER_THRESHOLD` (2) failures in a row it opens: the fallback answers directly. After
  `C2_LLM_FAILOVER_COOLDOWN_S` (60 s) the next request is a trial on Gemini: success closes the breaker (back to
  Gemini), failure reopens it with double the wait (up to 15 min). A saved answer never counts as a sign of health.
- **Same guard rails for both models:** same versioned prompt, same excerpts, same schema, temperature 0; a flag
  still needs both quotes word for word in the two texts, and B or G is still decided by the hierarchy levels.
- **Said openly:** a flag judged by the fallback says so in its text. Answers are cached per model, never mixed.
- **Both down:** the check is incomplete, as before (fails closed).

## Consequences
- The fallback model is weaker than Gemini: expect more "insufficient" answers and possibly more wrong ones that the
  quote check cannot catch (a real quote, a wrong reading). Its quality on this task is NOT measured yet.
- State is per process (one Cloud Run instance = one breaker). Good enough for the PoC.
- On Cloud Run there is no Ollama beside the app, so the fallback is for local and demo-laptop use until a model
  host inside the project's VPC exists (still "this side of the boundary"; needs its own decision and cost).
- CLAUDE.md §2.1 wording should gain "with an optional locally hosted fallback (ADR-0021)" — owner to approve the edit.

## Still to confirm
Which Ollama model to use (must fit the demo laptop), and its measured B / G quality against the saved Gemini answers.
