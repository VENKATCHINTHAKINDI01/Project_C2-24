"""L2 Early-Exit Safeguards (plan §3.2, §13.2; ADR-0061 addendum 24 Nov 2026).

Implements three defense-in-depth verification gates prior to L2 early termination:
1. Canonical document deduplication: ensures runner-up scoring compares distinct documents,
   not multiple passages of the top document. Single-candidate queries safely exit if score >=
   threshold.
2. Entity / Attribute verification: ensures high semantic similarity cannot override an explicit
   mismatch on discriminating attributes (e.g. B.P.Ed vs M.P.Ed, degree courses, block periods).
3. Cross-candidate temporal relationship gating: inspects competing top candidates for active
   AMENDS or SUPERSEDES edges, forcing L3 escalation when candidates belong to an amendment chain.
   (Contextual references like READS_WITH/REFERENCES are not treated as amendments).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

import yaml

from app.auth.models import Scope
from app.graph.repository import Direction, EdgeKind, WalkableGraph

log = logging.getLogger(__name__)

SAFEGUARDS_FILE = Path(__file__).resolve().parents[2] / "config" / "l2_safeguards.yaml"


def _key(term: str) -> str:
    return re.sub(r"[.\s-]", "", term.lower())


def _pattern(term: str) -> str:
    """'b.p.ed' → b\\.?p\\.?ed; spaces and hyphens inside a term are optional / flexible."""
    out = []
    for ch in term.lower():
        if ch == ".":
            out.append(r"\.?")
        elif ch == " ":
            out.append(r"\s+")
        elif ch == "-":
            out.append(r"[-\s]?")
        else:
            out.append(re.escape(ch))
    return "".join(out)


class _Kind:
    """One attribute kind (course, cadre): its exclusive groups and a matcher for its terms."""

    def __init__(self, groups: Sequence[Sequence[str]]) -> None:
        self.groups = tuple(frozenset(t.lower() for t in g) for g in groups)
        terms = sorted({t for g in self.groups for t in g}, key=len, reverse=True)  # longest first
        self.canonical = {_key(t): t for t in terms}
        self.rx = re.compile(r"\b(" + "|".join(_pattern(t) for t in terms) + r")\b", re.I)

    def found(self, text: str) -> set[str]:
        return {self.canonical[_key(m.group(1))] for m in self.rx.finditer(text)}

    def conflict(self, query: str, subject: str) -> tuple[str, str] | None:
        q, d = self.found(query), self.found(subject)
        for group in self.groups:
            qo, do = q & group, d & group
            if qo and do and qo != do:
                return sorted(qo)[0], sorted(do)[0]
        return None


@lru_cache(maxsize=1)
def _kinds(path: Path = SAFEGUARDS_FILE) -> dict[str, _Kind]:
    data = yaml.safe_load(path.read_text("utf-8")) or {}
    return {name: _Kind(groups) for name, groups in (data.get("groups") or {}).items()}


_BLOCK_PERIOD = re.compile(r"\b(20\d{2}\s*[-–]\s*\d{2}(?:\s*to\s*20\d{2}\s*[-–]\s*\d{2})?)\b", re.I)
_STANDALONE_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _normalize_period(p: str) -> str:
    return re.sub(r"\s+", "", re.sub(r"[–—]", "-", p.lower()))


def verify_entity_attributes(query: str, document_subject: str) -> tuple[bool, str | None]:
    """Verify that the top document does not conflict with explicit entities in the query.

    Checks:
    1. Course / degree specializations (e.g. B.P.Ed vs M.P.Ed).
    2. Cadre, rank, or category (e.g. gazetted vs non-gazetted, assistant secretary vs section
    officer).
    3. Relevant block periods and explicit calendar years.

    Returns (True, None) if clean, or (False, reason) if an explicit conflict is found.
    """
    # 1–2. Courses, cadres and any other kind listed in config/l2_safeguards.yaml
    for name, kind in _kinds().items():
        clash = kind.conflict(query, document_subject)
        if clash:
            label = "" if name == "course" else f"{name} "
            return (
                False,
                f"query specifies {label}'{clash[0]}' but candidate specifies '{clash[1]}'",
            )

    # 3. Block periods and dates check
    q_periods = {_normalize_period(m.group(1)) for m in _BLOCK_PERIOD.finditer(query)}
    d_periods = {_normalize_period(m.group(1)) for m in _BLOCK_PERIOD.finditer(document_subject)}
    if q_periods and d_periods and not (q_periods & d_periods):
        q_p = sorted(q_periods)[0]
        d_p = sorted(d_periods)[0]
        return False, f"query specifies block period '{q_p}' but candidate specifies '{d_p}'"

    # 4. Standalone year check (only when both mention explicit years with zero overlap)
    q_years = set(_STANDALONE_YEAR.findall(query))
    d_years = set(_STANDALONE_YEAR.findall(document_subject))
    if q_years and d_years and not (q_years & d_years):
        q_y = sorted(q_years)[0]
        d_y = sorted(d_years)[0]
        return False, f"query specifies year '{q_y}' but candidate specifies '{d_y}'"

    return True, None


def verify_cross_candidate_graph(
    candidate_canonical_ids: Sequence[str],
    graph: WalkableGraph,
    scope: Scope,
) -> tuple[bool, str | None]:
    """Check if top candidates are linked by active AMENDS or SUPERSEDES edges.

    If any pair among the candidates has an active AMENDS or SUPERSEDES relationship,
    L2 early termination is forbidden and retrieval must escalate to L3.
    Citations (REFERENCES / READS_WITH) do not block L2 exit.
    """
    top_ids = list(dict.fromkeys(candidate_canonical_ids))[:5]
    if len(top_ids) < 2:
        return True, None

    candidate_set = set(top_ids)
    try:
        # Check direct 1-hop relationships across candidate pairs.
        # Walking per-seed avoids the graph walker pre-seeding `seen` with all candidate IDs.
        for seed_id in top_ids:
            hits = graph.walk(
                [seed_id],
                scope,
                kinds=frozenset(
                    {
                        EdgeKind.AMENDS,
                        EdgeKind.SUPERSEDES,
                        EdgeKind.REPEALS,
                        EdgeKind.CLARIFIES,
                        EdgeKind.CONFLICTS_WITH,
                    }
                ),
                direction=Direction.BOTH,
                max_hops=1,
            )
            for h in hits:
                if h.canonical_id in candidate_set and h.canonical_id != seed_id:
                    return (
                        False,
                        f"candidates '{seed_id}' and '{h.canonical_id}' are linked by {h.via.value}",  # noqa: E501
                    )
    except Exception as exc:  # noqa: BLE001 — fail closed: any graph failure means no early exit
        log.warning("L2 graph gate unavailable, escalating to L3: %s", type(exc).__name__)
        return False, "graph inspection unavailable"

    return True, None
