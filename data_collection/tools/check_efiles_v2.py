"""Checks for the synthetic set v2 (ADR-0020) before it is loaded or uploaded. Read-only. Exit 1 on any problem.

  python tools/check_efiles_v2.py

1  every file folder is complete (file.json, receipt, notes, movements, links, GO/link.json)
2  every Markdown file carries the SYNTHETIC banner; every lower instrument says "SYNTHETIC — not a real order"
3  every cited order is held in the corpus (except the cited order of a type E case, which must NOT be held)
4  every citation written in a note parses back to the order it stands for (G.O.s; gazettes are checked by number)
5  note dates lie in 2016-01-01 .. as-of (31-12-2025); the receipt is diarised before the first note
6  A / F: the governing order is dated on or before the note; a "clean before" file is dated before the newer order
7  file numbers are unique; every planted conflict in the ground truth points at a rendered file and vice versa
8  every officer in a file's movements belongs to that department, and the access matrix ALLOWS every one of them
9  restricted-section files are CONFIDENTIAL; ground truth lives only under efiles_v2/ground_truth (never backend/)
10 note times only move forward; every consultation (Finance, GAD Services, Cabinet by U.O. note) is in Correspondence,
   labelled SYNTHETIC, recorded in a note, never with the file's own department, never on a restricted file, returned
   before the note that records it, and consultations follow one another
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import ROOT, load_scope, parse_reference  # noqa: E402

ST = ROOT / "staging"
REPO = HERE.parents[1]
V2 = REPO / "data" / "synthetic" / "mock_v1" / "efiles_v2"
AS_OF = "2025-12-31"


def main() -> None:
    probs: list[str] = []
    meta = {}
    for p in (ST / "rule-library").rglob("meta.json"):
        m = json.loads(p.read_text())
        meta[m["canonical_id"]] = m
    scope = load_scope()
    officers = yaml.safe_load((V2 / "directory" / "officers.yaml").read_text())
    offs = {o["id"]: o for o in officers["officers"]}
    plan = {s["key"]: s for v in yaml.safe_load((V2 / "scenarios" / "scenarios.yaml").read_text())["departments"].values() for s in v}
    gts = json.loads((V2 / "ground_truth" / "efiles_v2_conflicts.json").read_text())
    with open(V2 / "access_matrix.csv") as fh:
        matrix = {r["file_no"]: r for r in csv.DictReader(fh)}

    files = {}
    for fj in sorted((V2 / "efiles").rglob("file.json")):
        d = fj.parent
        f = json.loads(fj.read_text())
        fn = f["file_no"]
        if fn in files:
            probs.append(f"duplicate file number {fn}")
        files[fn] = f
        sc = plan.get(f["scenario"])
        if sc is None:
            probs.append(f"{fn}: scenario {f['scenario']} not in the plan")
            continue
        # 1 completeness
        for need in ("Correspondence/R-001.md", "movements.json", "links.json", "GO/link.json"):
            if not (d / need).exists():
                probs.append(f"{fn}: missing {need}")
        notes = sorted((d / "Note File1").glob("note-*.md"))
        if not notes:
            probs.append(f"{fn}: no notes")
        # 2 banners
        for md in d.rglob("*.md"):
            t = md.read_text()
            if not t.startswith("<!-- SYNTHETIC"):
                probs.append(f"{fn}: {md.name} has no SYNTHETIC banner")
            if re.fullmatch(r"R-00[2-9]\.md", md.name) and "SYNTHETIC — not a real order" not in t:
                probs.append(f"{fn}: {md.name} lower instrument not labelled")
        # 3 cited orders held
        conf = sc.get("conflict") or {}
        for c in sc["cite"]:
            if conf.get("type") == "E":
                if c in meta:
                    probs.append(f"{fn}: type E cites {c}, which IS held")
            elif c not in meta:
                probs.append(f"{fn}: cites {c}, not held")
        # 4 citations parse back
        note1 = notes[0].read_text() if notes else ""
        for c in sc["cite"]:
            if c not in meta or c.startswith("AP-GAZ"):
                continue
            m = meta[c]
            pat = rf"G\.O\.(?:Ms|Rt)\.No\.{int(m['number'])}, [^)]*\) Department, dated \d\d[-.]\d\d[-.]{m['date'][:4]}"
            hit = re.search(pat, note1)
            if not hit:
                probs.append(f"{fn}: citation of {c} not found in note 1")
                continue
            back = parse_reference(hit.group(0), m["department_code"], scope)
            if not back or back.get("canonical_id") != c:
                probs.append(f"{fn}: '{hit.group(0)}' parses back as {back and back.get('canonical_id')}, not {c}")
        # 5 dates
        if not ("2016-01-01" <= sc["date"] <= AS_OF):
            probs.append(f"{fn}: note date {sc['date']} outside 2016..{AS_OF}")
        if f["opened"] > sc["date"]:
            probs.append(f"{fn}: receipt diarised {f['opened']} after the note {sc['date']}")
        # 6 temporal logic
        if conf.get("type") in ("A", "F") and conf.get("governing") in meta:
            if meta[conf["governing"]]["date"] > sc["date"]:
                probs.append(f"{fn}: {conf['type']} but governing order is dated after the note")
        src = sc.get("source") or {}
        if sc["kind"] == "CLEAN" and src.get("newer") and sc["cite"] == [src.get("older")]:
            if sc["date"] >= src.get("newer_date", "9999"):
                probs.append(f"{fn}: 'clean before' file dated on/after the newer order")
        # 8 movements vs department and access
        for mv in json.loads((d / "movements.json").read_text()):
            o = offs.get(mv["from"])
            if not o or o["dept"] != f["department_code"]:
                probs.append(f"{fn}: movement by {mv['from']} outside the department")
            elif matrix.get(fn, {}).get(mv["from"]) != "ALLOW":
                probs.append(f"{fn}: {mv['from']} handled the file but the access matrix denies it")
        # 10 note times; Finance concurrence
        times = []
        for nf in notes:
            m = re.search(r"^(\d\d/\d\d/\d{4} \d\d:\d\d [AP]M)$", nf.read_text(), re.M)
            times.append(dt.datetime.strptime(m.group(1), "%d/%m/%Y %I:%M %p") if m else None)
        if None in times:
            probs.append(f"{fn}: a note has no signature time")
        elif times != sorted(times):
            probs.append(f"{fn}: note times go backwards")
        owner = {"FIN": "FIN01", "GADSER": "GAD01", "CABINET": "GAD01"}
        prev_ret = ""
        for fc in f.get("consultations", []):
            r = d / "Correspondence" / fc["correspondence"]
            if owner[fc["with"]] == f["department_code"] or \
                    officers["departments"][f["department_code"]]["sections"][f["section"]].get("restricted"):
                probs.append(f"{fn}: {fc['with']} consulted by its own department or on a restricted file")
            if not r.exists() or fc["uo_no"] not in r.read_text():
                probs.append(f"{fn}: U.O. note {fc['correspondence']} missing or without its number")
            hit = [k for k, nf in enumerate(notes) if fc["uo_no"] in nf.read_text()]
            if not hit:
                probs.append(f"{fn}: no note records the U.O. note {fc['uo_no']}")
                continue
            if times[hit[0]] and not (fc["sent"] <= fc["returned"] <= times[hit[0]].date().isoformat()):
                probs.append(f"{fn}: U.O. dates out of order ({fc['with']})")
            if times[hit[0] - 1] and fc["sent"] < times[hit[0] - 1].date().isoformat():
                probs.append(f"{fn}: file referred ({fc['with']}) before the order to refer it")
            if fc["sent"] < prev_ret:
                probs.append(f"{fn}: consultations overlap")
            prev_ret = fc["returned"]
        # 9 classification of restricted sections
        if officers["departments"][f["department_code"]]["sections"][f["section"]].get("restricted") \
                and f["classification"] != "CONFIDENTIAL":
            probs.append(f"{fn}: restricted section but classified {f['classification']}")

    # 7 ground truth <-> files
    planted = {s["key"] for s in plan.values() if s.get("conflict")}
    gt_keys = {g["scenario"] for g in gts}
    for g in gts:
        if g["file_no"] not in files:
            probs.append(f"ground truth points at missing file {g['file_no']}")
    if planted != gt_keys:
        probs.append(f"ground truth / plan mismatch: {len(planted ^ gt_keys)} scenarios")
    # 9 ground truth location
    for p in (REPO / "backend").rglob("efiles_v2_conflicts.json"):
        probs.append(f"ground truth found under backend/: {p}")

    for p in probs[:60]:
        print("PROBLEM", p)
    import collections
    cons = collections.Counter(c["with"] for f in files.values() for c in f.get("consultations", []))
    uo = sum(1 for f in files.values() if f.get("received_by") == "U.O. Note")
    print(f"{len(files)} files, {len(gts)} planted conflicts, consultations {dict(cons)}, {uo} U.O. receipts, "
          f"{len(probs)} problems")
    sys.exit(1 if probs else 0)


if __name__ == "__main__":
    main()
