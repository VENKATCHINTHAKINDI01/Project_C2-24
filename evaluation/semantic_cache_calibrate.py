"""Reworded-repeat matching against labelled pairs (plan §10.3; ADR-0053).

Pairs in evaluation/data/semantic_cache_pairs.json (SYNTHETIC) are labelled "same" (a reworded
repeat that may share an answer) or "different" (the same anchors but a different question: must
never share). Anchors are computed as the app does: orders named (same resolver), intent (same
fixed rules), numbers, negation, outcome, as-of date. A pair matches only with identical anchors
AND identical content words (`app/cache/semantic.py`). Pass bar: 0 "different" pairs matched.

    cd backend && env -u VIRTUAL_ENV uv run python ../evaluation/semantic_cache_calibrate.py
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.agents.orchestrator import _FILE_NO, classify  # noqa: E402
from app.cache.semantic import anchors, same_question  # noqa: E402
from app.config import REPO_ROOT  # noqa: E402
from app.identifiers.resolver import load_departments, reference_candidates  # noqa: E402

PAIRS = ROOT / "evaluation" / "data" / "semantic_cache_pairs.json"
REPORTS = ROOT / "evaluation" / "reports"
DAY = dt.date(2026, 11, 18)  # the as-of date is an anchor; any fixed day checks the same


def main() -> int:
    deps = load_departments(REPO_ROOT / "data" / "ontology" / "departments.yaml")

    def anchor(q: str) -> str:
        named = sorted(set(reference_candidates(q, deps)))
        files = sorted(set(_FILE_NO.findall(q)))
        return anchors(q, [*named, *files], classify(q, named, files).value, DAY)

    rows = []
    for p in json.loads(PAIRS.read_text("utf-8"))["pairs"]:
        same_anchor = anchor(p["a"]) == anchor(p["b"])
        hit = same_anchor and same_question(p["a"], p["b"])
        rows.append({**p, "same_anchor": same_anchor, "match": hit})
    same = [r for r in rows if r["label"] == "same"]
    wrong = [r for r in rows if r["label"] == "different" and r["match"]]
    caught = [r for r in same if r["match"]]
    lines = [
        f"# Reworded-repeat matching — {dt.date.today().isoformat()}",
        "",
        "SYNTHETIC pairs (`evaluation/data/semantic_cache_pairs.json`). A pair matches only with "
        "identical anchors and identical content words (`app/cache/semantic.py`, ADR-0053).",
        "",
        f"- pairs: {len(rows)} ({len(same)} same, {len(rows) - len(same)} different)",
        f"- 'different' pairs served the other's answer: **{len(wrong)}** (pass bar 0)",
        f"- reworded repeats served from the cache: **{len(caught)} / {len(same)}**",
        "",
        "| Label | Anchors equal | Match | A | B |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {r['label']} | {'yes' if r['same_anchor'] else 'no'} | "
        f"{'**yes**' if r['match'] else 'no'} | {r['a']} | {r['b']} |"
        for r in sorted(rows, key=lambda r: (r["label"], not r["match"]))
    ]
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"{dt.date.today().isoformat()}-reworded-pairs.md"
    out.write_text("\n".join(lines) + "\n", "utf-8")
    print("\n".join(lines[4:7]))
    print(f"report: {out.relative_to(ROOT)}")
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main())
