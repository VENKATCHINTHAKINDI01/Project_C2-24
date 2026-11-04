"""7-type conflict engine, deterministic + LLM (plan §6.2).

Implemented: deterministic reference checks A, E, F (`deterministic.check_citations`); type C
against approval-authority rules in config (`procedural.check_authority`, ADR-0010).
Proposal facts read from note text with evidence (`facts`); the pre-send check running A/C/E/F
together with status coverage (`presend`, touchpoint 11).
Type F for the proposal's own date against action windows stated in in-force orders
(`windows`). Not yet: B/G/D (grounded Gemini judgment).
"""
