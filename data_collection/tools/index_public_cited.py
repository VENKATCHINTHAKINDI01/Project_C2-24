"""Index the real public orders the synthetic set v2 can reach, for the sandbox document store (ADR-0020).

The orders live in the data root (ADR-0006, outside the repo); this writes only their source-system tags:

  data/synthetic/mock_v1/efiles_v2/eoffice/public_index.csv
      id, file (path under the data root), department, section, classification, raw_reference, sha256

Scope:
  cited     (default) the orders the rendered notes cite and the corpus holds (type E references are not held,
            so they never appear), plus the held orders that supersede / amend / repeal / clarify one of them
            — about 110 documents, ~65 MB
  sections  also every other held order of the nine v2 sections (distractors for retrieval) — larger

Only public orders are listed (classification UNCLASSIFIED); a withheld/confidential order is skipped. The list
says nothing about which file cites what: the cited set is mixed with the rest by canonical ID order.

  python tools/index_public_cited.py [--scope cited|sections]
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import ROOT  # noqa: E402
from mine_scenarios_v2 import load, section_of  # noqa: E402

REPO = HERE.parents[1]
V2 = REPO / "data" / "synthetic" / "mock_v1" / "efiles_v2"
OUT = V2 / "eoffice" / "public_index.csv"
CHANGES = {"SUPERSEDES", "AMENDS", "REPEALS", "CLARIFIES"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=("cited", "sections"), default="cited")
    a = ap.parse_args()
    meta, _ = load()
    want = set()
    for p in (V2 / "efiles").rglob("GO/link.json"):
        want |= {c for c in json.loads(p.read_text()) if c in meta}
    # A department's rule library also holds the orders that CHANGE the ones its files cite (otherwise nothing could
    # ever be found superseded or amended). Taken from the corpus's own links, never from the answer key:
    # relations.jsonl (links read from the orders' text) and chains.yaml (the verified chains).
    cited = set(want)
    rel = ROOT / "staging" / "manifests" / "relations.jsonl"
    for line in rel.read_text().splitlines() if rel.exists() else []:
        e = json.loads(line)
        if e["type"] in CHANGES and e.get("to") in cited and e["from"] in meta:
            want.add(e["from"])

    def walk(node):
        if isinstance(node, dict):
            if node.get("older") in cited and node.get("newer") in meta:
                want.add(node["newer"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            ids = [v.get("id") for v in node if isinstance(v, dict)]
            hit = [n for n, c in enumerate(ids) if c in cited]
            if hit and len(ids) == len(node):         # a rate series (oldest first): the later orders revise it
                want.update(c for c in ids[hit[0] + 1:] if c in meta)
            for v in node:
                walk(v)

    chains = V2 / "scenarios" / "chains.yaml"
    if chains.exists():
        walk(yaml.safe_load(chains.read_text()))
    print(f"{len(cited)} cited orders + {len(want) - len(cited)} orders that change them")
    if a.scope == "sections":
        want |= {c for c, m in meta.items() if section_of(m)}
    rows, skipped = [], []
    for cid in sorted(want):
        m = meta[cid]
        f = m["_dir"] / ((m.get("files") or {}).get("original") or "order.pdf")
        if m.get("classification") != "UNCLASSIFIED" or not f.is_file():
            skipped.append(cid)
            continue
        rows.append({"id": cid, "file": f.relative_to(ROOT).as_posix(), "department": m["department_code"],
                     "section": m.get("section") or "", "classification": "UNCLASSIFIED", "raw_reference": "",
                     "sha256": hashlib.sha256(f.read_bytes()).hexdigest()})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    # demo holdback (scope.yaml demo_holdback): orders kept out of the corpus, listed apart so the sandbox can let
    # one "arrive" during the demo. Same columns; always written (header only when nothing is held back).
    held = []
    for d in sorted((ROOT / "staging" / "holdback").glob("*/meta.json")):
        m = json.loads(d.read_text())
        f = d.parent / ((m.get("files") or {}).get("original") or "order.pdf")
        if m.get("classification") == "UNCLASSIFIED" and f.is_file():
            held.append({"id": m["canonical_id"], "file": f.relative_to(ROOT).as_posix(),
                         "department": m["department_code"], "section": m.get("section") or "",
                         "classification": "UNCLASSIFIED", "raw_reference": "",
                         "sha256": hashlib.sha256(f.read_bytes()).hexdigest()})
    with open(OUT.with_name("public_holdback.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(held)
    print(f"{len(held)} held-back orders listed → public_holdback.csv: {[h['id'] for h in held]}")
    mb = sum((ROOT / r["file"]).stat().st_size for r in rows) / 1e6
    print(f"{len(rows)} public orders indexed ({mb:.0f} MB) → {OUT.relative_to(REPO)}; skipped {len(skipped)}: {skipped}")


if __name__ == "__main__":
    main()
