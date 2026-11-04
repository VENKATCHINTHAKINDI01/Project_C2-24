"""Canonical ID resolver and reference normaliser (plan §4.4).

Implemented: strict canonical-ID parser/formatter (`canonical`), reference normaliser for G.O.
(Ms/Rt/P), memo, circular memo, Rc, standing order and e-File references (`resolver`), and the
persistent collision registry for same-number orders (`collisions`, ADR-0007).
Not yet: Telugu transliterations, "reference 2nd read above" list resolution (P1 ingestion).
"""
