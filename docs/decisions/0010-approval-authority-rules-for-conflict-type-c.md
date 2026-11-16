# ADR-0010: Approval-authority rules for conflict type C

- **Date:** 2026-11-04
- **Status:** Accepted by the owner (option A, 4 Nov 2026) for the FRAMEWORK. Rule content is MOCK and for testing only — not approval guidance
- **Plan section:** §6.2 (type C), §6.4, §4.5

## Context
Type C ("procedural / wrong authority") needs facts about who may approve what. Real circular memos are not online and
no department data has arrived. The mock corpus orders state such rules explicitly.

## Decision
1. Rules live in config, `data/ontology/authority_rules.yaml` (`status: mock`), each citing the clause it comes from
   and applying only from that source's date. Code (`backend/app/conflict/procedural.py`) holds no rule content, so real
   rules replace the file without code changes.
2. The check is deterministic over structured proposal facts (action, post level, amount, proposed authority,
   concurrences obtained). The LLM never decides competence; it may later help fill the facts, shown with their evidence.
3. Flags cite only rule sources the officer may see; with none visible the flag is raised but uncertain and uncited.
   No matching rule → no flag.

## Owner conditions (4 Nov 2026)
4. **Testing only until real rules exist.** Mock rules test that rules are applied deterministically, respect effective
   dates and cite sources; they do not establish whether a real officer may approve a real proposal.
5. **Coverage, not silence.** Each check returns CONFLICT, NO_CONFLICT_VERIFIED (only for a `verified` rule set whose
   coverage of that department + action is declared verified AND complete, with who/when) or REVIEW_NEEDED ("not enough
   rule coverage to tell"). "No matching rule" never reads as approval. With unverified rules every flag is uncertain
   and carries a caveat. A `mock` rules file cannot declare verified coverage (rejected on load).
6. **Before real use:** collect authoritative, current rules for the relevant departments and actions — thresholds,
   effective dates, amendments — then set `status: verified` and declare coverage.

## Consequences
- Matches the answer key for D27 (Deputy Secretary can only recommend), D28 (above Rs.1.00 crore → Government only),
  D29 (no Finance concurrence); clean for D19, D24 (pre-2024), D25.
- Post levels ("Section Officer and below" vs "Assistant Secretary and above") follow ADR-0008, still provisional.
- Filling `ProposalFacts` from note text is a later step (patterns or grounded Gemini extraction).

## Addendum — rules for synthetic set v2 from real orders (13 Nov 2026, owner OK)
- `data/ontology/authority_rules_v2.yaml`, loaded when `C2_SANDBOX_SEED=v2`. Every rule quotes a real public order
  (G.O.Ms.22/2025 ESE, 51/2016 FIN, 74 / 99 / 32 of 2017 GAD). Status stays `mock` (= unverified): no coverage is
  declared, every flag is an uncertain prompt, and "no flag" is never a clean pass (points 4–6 above).
- Rule fields added: `departments`, `subject_terms`, `effective_until`, `barred` (a part of the year in which a
  request may not be granted). Actions added: `reappropriation`, `business_allocation`.
- Facts: the proposed body is read only when the proposal sentence names exactly one known body; a draft that points
  to "the paras above" is read together with the file's earlier notes the officer may see.
- Not covered on purpose: a rule the cited order does not state (FIN 81 / 88 of 2016 on G.O.Ms.110/2016).
- Evaluation caveat: the v2 type C files were written from these orders, so recall shows correct application only.
- Upgrade path unchanged: grounded Gemini extraction of the proposal facts, checked against the note's own words.

## Alternatives considered
| Option | Why not |
|---|---|
| Wait for real data (option B) | Owner chose to build now; config keeps the swap cheap |
| Let Gemini judge competence | Competence is a rule fact; deterministic checks have zero hallucination risk (plan §6.2) |
