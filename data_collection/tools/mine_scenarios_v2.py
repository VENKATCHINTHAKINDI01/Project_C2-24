"""Stage 1 of the synthetic set v2 (ADR-0020): mine scenario CANDIDATES from the real corpus and verify them.

Reads staging/rule-library + manifests/relations.jsonl (data root, ADR-0006) and the v2 directory
(data/synthetic/mock_v1/efiles_v2/directory/officers.yaml). Writes, for review before any file is rendered:

  data/synthetic/mock_v1/efiles_v2/scenarios/candidates.csv    every candidate edge, verified or not, with the quote
  data/synthetic/mock_v1/efiles_v2/scenarios/chains.yaml       verified chains per department/section

A relation from relations.jsonl is only a candidate. It is VERIFIED when the newer order's own text names the older
order's number within ~250 characters of a supersession / amendment / cancellation verb, and that quote is kept.
Nothing is guessed: unverified edges stay in candidates.csv with the reason and are never used for a planted conflict.

Also mined (no relation needed):
  - rate series (DA / DR / HRA): orders of one section whose subject names the same allowance, in date order — a note
    applying an older rate after a newer order is a type F candidate;
  - unresolved citations: orders our sections cite that the corpus does not hold — type E candidates;
  - gazette rule amendments of our three departments — type G / rule-version candidates.

  python tools/mine_scenarios_v2.py            # writes the two files and prints a summary
"""
from __future__ import annotations

import collections
import csv
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import ROOT, normalize_ocr  # noqa: E402

ST = ROOT / "staging"
REPO = HERE.parents[1]
V2 = REPO / "data" / "synthetic" / "mock_v1" / "efiles_v2"
OUT = V2 / "scenarios"

# Section of a held order: from its own section field (as GOIR records it). Patterns follow the real labels.
SECTION_PATTERNS = {
    "FIN01": {"HR-I": r"HR-?(?:1|I)-PLG|PLG.?POLICY", "HR-III": r"PENSION|HR-?III|HR-[35]-PEN", "BUDGET-I": r"BUDGET"},
    "GAD01": {"SER-A": r"^SER-A", "CABINET-II": r"CABINET", "SC-F": r"^SC-F"},
    "ESE01": {"SERVICES-II": r"SERVICES-II|SER-II", "PROGRAM-I": r"PROGRAM-I(?![IV])|PROG-?I(?![IV])", "EXAMS": r"EXAM"},
}
VERBS = {
    "SUPERSEDES": r"supersession|superseded|supersede",
    "AMENDS": r"amend|amendment|modif|substitut|errat",
    "REPEALS": r"cancel|withdraw|rescind|repeal",
}
RATES = {"DA": r"dearness allowance", "DR": r"dearness relief", "HRA": r"house rent allowance|\bhra\b"}


def load():
    meta = {}
    for p in (ST / "rule-library").rglob("meta.json"):
        m = json.loads(p.read_text())
        m["_dir"] = p.parent
        meta[m["canonical_id"]] = m
    rels = [json.loads(line) for line in (ST / "manifests" / "relations.jsonl").read_text().splitlines()]
    return meta, rels


def section_of(m) -> str | None:
    pats = SECTION_PATTERNS.get(m.get("department_code"), {})
    s = (m.get("section") or "").upper()
    return next((k for k, pat in pats.items() if re.search(pat, s)), None)


def text_of(m) -> str:
    f = m["_dir"] / ((m.get("files") or {}).get("ocr") or "ocr.txt")
    t = f.read_text(errors="ignore") if f.exists() else ""
    return re.sub(r"\s+", " ", normalize_ocr(t))


def verify(edge, meta) -> tuple[bool, str, str]:
    """(verified, quote, reason). The newer order must name the older one's number near the edge's verb."""
    new, old = meta[edge["from"]], meta[edge["to"]]
    t = text_of(new)
    num = str(int(old["number"]))
    yr = str(old["date"])[:4]
    verbs = VERBS[edge["type"]]
    for m in re.finditer(r"(?:G\.?\s*O\.?\s*(?:Ms|Rt)?\.?\s*No\.?\s*|No\.\s*)0*" + num + r"(?!\d)", t, re.I):
        win = t[max(0, m.start() - 250): m.end() + 250]
        if re.search(verbs, win, re.I) and (yr in win or re.search(r"read above|first read|second read|\d(?:st|nd|rd|th) read", win, re.I)):
            return True, win.strip(), "number + verb (+ year or read-reference) in the newer order"
    if edge["type"] == "SUPERSEDES" and re.search(r"in supersession of (?:all )?the (?:earlier )?orders? issued (?:vide|in) (?:the )?(?:G\.?O\.?\s*)?\d?(?:st|nd|rd|th)? ?read", t, re.I):
        return False, "", "supersession by 'read above' reference only — check the Read-list position by hand"
    return False, "", "older order's number not found near a supersession/amendment verb"


def main() -> None:
    meta, rels = load()
    officers = yaml.safe_load((V2 / "directory" / "officers.yaml").read_text())
    depts = set(officers["departments"])
    OUT.mkdir(parents=True, exist_ok=True)

    rows, chains = [], collections.defaultdict(list)
    for e in rels:
        if e["type"] not in VERBS or e.get("to") not in meta or e.get("from") not in meta:
            continue
        old, new = meta[e["to"]], meta[e["from"]]
        dept = old["department_code"] if old["department_code"] in depts else new.get("department_code")
        if dept not in depts and not (old["canonical_id"].startswith("AP-GAZ") or new["canonical_id"].startswith("AP-GAZ")):
            continue
        sec = section_of(old) or section_of(new)
        ok, quote, why = verify(e, meta)
        rows.append({"type": e["type"], "older": e["to"], "older_date": old["date"], "newer": e["from"],
                     "newer_date": new["date"], "dept": old["department_code"], "section": sec or "",
                     "verified": ok, "reason": why, "quote": quote[:400], "older_subject": old.get("subject", "")[:160]})
        if ok:
            chains[f"{old['department_code']}/{sec or '-'}"].append(
                {"type": e["type"], "older": e["to"], "older_date": old["date"], "newer": e["from"],
                 "newer_date": new["date"], "quote": quote[:400], "subject": old.get("subject", "")[:160]})

    # rate series in our sections (type F candidates)
    series = collections.defaultdict(list)
    for m in meta.values():
        if m.get("department_code") != "FIN01" or str(m.get("date")) < "2016":
            continue
        subj = (m.get("subject") or "").lower()
        for k, pat in RATES.items():
            if re.search(pat, subj):
                series[k].append({"id": m["canonical_id"], "date": m["date"], "subject": m.get("subject", "")[:140]})
    for k in series:
        series[k].sort(key=lambda x: x["date"])

    # unresolved citations made by our sections' orders (type E candidates)
    unresolved = collections.Counter()
    for e in rels:
        f = meta.get(e["from"])
        if f and section_of(f) and e.get("to") and e["to"] not in meta:
            unresolved[(f["department_code"], section_of(f), e["to"])] += 1

    with open(OUT / "candidates.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["dept"], r["section"], r["older_date"])))
    doc = {"_note": "SYNTHETIC set v2 stage 1 — verified real-order chains; every quote is from the newer order's text. "
                    "Generated by data_collection/tools/mine_scenarios_v2.py; review before rendering.",
           "chains": dict(sorted(chains.items())),
           "rate_series": {k: v for k, v in series.items()},
           "unresolved_citations": [{"dept": d, "section": s, "cited": c, "times": n}
                                    for (d, s, c), n in unresolved.most_common()]}
    (OUT / "chains.yaml").write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120))

    ver = collections.Counter((r["dept"], r["section"] or "-", r["verified"]) for r in rows)
    print(f"{len(rows)} candidate edges, {sum(r['verified'] for r in rows)} verified")
    for k in sorted(ver):
        print("  ", k, ver[k])
    print("rate series:", {k: len(v) for k, v in series.items()})
    print("unresolved citations from our sections:", len(unresolved))
    print("written:", (OUT / "candidates.csv").relative_to(REPO), (OUT / "chains.yaml").relative_to(REPO))


if __name__ == "__main__":
    main()
