"""Stage 2 of the synthetic set v2 (ADR-0020): turn verified real-order chains into one scenario per synthetic e-file.

Reads  efiles_v2/scenarios/chains.yaml (stage 1), efiles_v2/directory/officers.yaml, the corpus (data root).
Writes efiles_v2/scenarios/scenarios.yaml — the reviewable plan for ~200 files — and prints coverage tables.

Every scenario: key, dept, section, note date, subject, movement (officer ids along the real chain), touchpoints,
cited orders, and either a planted conflict (type, cited, governing, reason, quotes from the real orders) or clean.
Types built here from verified data: A (superseded / cancelled order cited), F (provision amended / rate revised before
the note), E (cited order not in the corpus), D (an earlier synthetic file decided the same matter), and clean
controls (before the change, or citing the current order). B, C and G need a person to read the orders: they are
written as `needs_hand_review: true` drafts from hand-picked candidates and are never rendered until reviewed.

  python tools/build_scenarios_v2.py              # deterministic (seed 20261113)
"""
from __future__ import annotations

import collections
import datetime as dt
import json
import random
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import ROOT, normalize_ocr  # noqa: E402

ST = ROOT / "staging"
V2 = HERE.parents[1] / "data" / "synthetic" / "mock_v1" / "efiles_v2"
AS_OF = "2025-12-31"
TARGET = 67                     # files per department (≈200 total)
CLEAN_SHARE = 0.27
rng = random.Random(20261113)

TOUCH = {1: "diarise receipt", 2: "receipt inbox", 3: "put in a file", 4: "received G.O. supersedes",
         5: "previous references", 6: "yellow note", 7: "referencing in a note", 8: "file so far",
         9: "link file", 10: "local reference", 11: "before send", 12: "initiate action summary",
         13: "approval brief", 14: "DFA draft", 15: "advance search", 16: "closing a file",
         17: "reopening a file", 18: "migrated old file", 19: "section reassignment", 20: "search privilege"}


def load_meta():
    out = {}
    for p in (ST / "rule-library").rglob("meta.json"):
        m = json.loads(p.read_text())
        m["_dir"] = p.parent
        out[m["canonical_id"]] = m
    return out


def text(m) -> str:
    f = m["_dir"] / ((m.get("files") or {}).get("ocr") or "ocr.txt")
    return re.sub(r"\s+", " ", normalize_ocr(f.read_text(errors="ignore"))) if f.exists() else ""


def gid(cid: str, meta) -> str:
    """How a note cites a real order: G.O.Ms.No.45, dated 24-06-2019 (gazettes by number/part/date)."""
    m = meta[cid]
    d = dt.date.fromisoformat(m["date"]).strftime("%d-%m-%Y")
    if cid.startswith("AP-GAZ"):
        return f"A.P. Gazette ({m.get('instrument', '').replace('A.P. Gazette ', '')}) No.{m['number']}, dated {d}"
    kind = "Rt" if "-GORT-" in cid else "Ms"
    return f"G.O.{kind}.No.{int(m['number'])}, dated {d}"


def after(date: str, lo: int, hi: int) -> str | None:
    d = dt.date.fromisoformat(date) + dt.timedelta(days=rng.randint(lo, hi))
    while d.weekday() == 6:                      # no notes on Sundays
        d += dt.timedelta(days=1)
    return d.isoformat() if d.isoformat() <= AS_OF else None


def between(a: str, b: str) -> str | None:
    da, db = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    if (db - da).days < 20:
        return None
    return (da + dt.timedelta(days=rng.randint(10, (db - da).days - 7))).isoformat()


def section_for(dept, chain_key, subject, officers) -> str | None:
    """The file sits in the real section of the orders it concerns; a chain from a section we do not staff is skipped
    (never moved into another section)."""
    sec = chain_key.split("/")[1]
    return sec if sec in officers["departments"][dept]["sections"] else None


def movement(dept, section, officers, to_head: bool) -> list[str]:
    """Real file flow (A.P. Secretariat Office Manual ch.1): ASO -> SO -> AS -> JS -> head. A restricted section has
    no ASO or AS in our directory: its SO goes straight to the JS."""
    offs = [o for o in officers["officers"] if o["dept"] == dept]
    by = lambda rank, sec=None: next((o["id"] for o in offs if o["rank"] == rank and (sec is None or sec in o["sections"])), None)
    chain = [by(1, section), by(2, section), by(3, section), by(5)]
    if to_head:
        chain.append(by(6))
    return [c for c in chain if c]


def rate_pairs(meta, series):
    """Consecutive DA/DR orders whose texts give 'from X% ... to Y%': type F (old rate applied after the revision)."""
    out = []
    pat = re.compile(r"from\s+(?:the\s+existing\s+)?([\d.]+)\s*%[^%]{0,120}?to\s+([\d.]+)\s*%", re.I)
    for kind in ("DA", "DR"):
        xs = series.get(kind, [])
        for a, b in zip(xs, xs[1:]):
            ta, tb = text(meta[a["id"]]), text(meta[b["id"]])
            ma, mb = pat.search(ta), pat.search(tb)
            if ma and mb and ma.group(2) == mb.group(1):   # b starts where a ended: a real revision chain
                out.append({"kind": kind, "older": a["id"], "newer": b["id"], "older_rate": ma.group(2),
                            "newer_rate": mb.group(2), "q_old": ta[max(0, ma.start() - 80): ma.end() + 60],
                            "q_new": tb[max(0, mb.start() - 80): mb.end() + 60]})
    return out


def main() -> None:
    meta = load_meta()
    officers = yaml.safe_load((V2 / "directory" / "officers.yaml").read_text())
    st1 = yaml.safe_load((V2 / "scenarios" / "chains.yaml").read_text())
    restricted = {(d, s) for d, info in officers["departments"].items()
                  for s, v in info["sections"].items() if v.get("restricted")}
    scen = collections.defaultdict(list)

    def add(dept, **kw):
        kw["key"] = f"{dept}-{kw['kind']}-{len(scen[dept]) + 1:03d}"
        kw["dept"] = dept
        kw["synthetic"] = True
        if (dept, kw["section"]) in restricted:
            kw.setdefault("touchpoints", []).append(20)
        scen[dept].append(kw)

    # ---- A / F (+ clean before / after) from verified chains
    for ckey, chain in st1["chains"].items():
        dept = ckey.split("/")[0]
        if dept not in officers["departments"]:
            continue
        for c in chain:
            if not ("2016-01-01" <= c["newer_date"] <= AS_OF) or c["older"] not in meta or c["newer"] not in meta:
                continue
            sec = section_for(dept, ckey, c["subject"], officers)
            if sec is None:
                continue
            ctype = "A" if c["type"] in ("SUPERSEDES", "REPEALS") else "F"
            verb = {"SUPERSEDES": "superseded", "REPEALS": "cancelled", "AMENDS": "amended"}[c["type"]]
            for lo, hi in ((25, 240), (250, 700)):       # two files per chain at different dates (trimmed later)
              d_conf = after(c["newer_date"], lo, hi)
              if d_conf:
                add(dept, kind=ctype, section=sec, date=d_conf, subject=c["subject"], cite=[c["older"]],
                    conflict={"type": ctype, "cited": c["older"], "governing": c["newer"],
                              "reason": f"The note relies on {gid(c['older'], meta)}; {gid(c['newer'], meta)} "
                                        f"{verb} it before the note was written ({d_conf}).",
                              "quote_governing": c["quote"]},
                    touchpoints=[11, 10, 6] + ([4] if rng.random() < 0.4 else []),
                    movement=movement(dept, sec, officers, to_head=True), source=c)
            d_before = between(c["older_date"], c["newer_date"]) if c["older_date"] >= "2016-01-01" else None
            if d_before:     # clean: the older order was in force on the note date
                add(dept, kind="CLEAN", section=sec, date=d_before, subject=c["subject"], cite=[c["older"]],
                    conflict=None, why_clean=f"{gid(c['older'], meta)} was in force on {d_before}; "
                                             f"{gid(c['newer'], meta)} came later.",
                    touchpoints=[6, 7, 14], movement=movement(dept, sec, officers, to_head=False), source=c)
            d_after = after(c["newer_date"], 30, 300)
            if d_after:     # clean: cites the current order (read with the old one)
                add(dept, kind="CLEAN", section=sec, date=d_after, subject=c["subject"], cite=[c["newer"], c["older"]],
                    conflict=None, why_clean=f"Cites {gid(c['older'], meta)} read with {gid(c['newer'], meta)}.",
                    touchpoints=[6, 8, 13], movement=movement(dept, sec, officers, to_head=True), source=c)

    # ---- F from DA / DR rate revisions (Finance HR.III / PC-TA)
    for p in rate_pairs(meta, st1["rate_series"]):
        if p["kind"] != "DR":          # DA belongs to PC-TA, which is not staffed in v2
            continue
        sec = "HR-III"
        d = after(meta[p["newer"]]["date"], 20, 150)
        if d:
            add("FIN01", kind="F", section=sec, date=d,
                subject=f"Arrears of {'Dearness Relief' if p['kind'] == 'DR' else 'Dearness Allowance'} — claim",
                cite=[p["older"]],
                conflict={"type": "F", "cited": p["older"], "governing": p["newer"],
                          "reason": f"Arrears worked out at {p['older_rate']}% ({gid(p['older'], meta)}); "
                                    f"{gid(p['newer'], meta)} had revised it to {p['newer_rate']}% before {d}.",
                          "quote_cited": p["q_old"], "quote_governing": p["q_new"]},
                touchpoints=[11, 13, 14], movement=movement("FIN01", sec, officers, to_head=True), source=p)

    # ---- E: cited order not in the corpus (advisory: "missing / unresolvable authority")
    # The note cites it exactly as a real order of the department printed it (relations.jsonl `to_raw`), on that
    # order's subject: a real officer copies the reference from the earlier order on the matter.
    printed = collections.defaultdict(list)
    rel_path = ST / "manifests" / "relations.jsonl"
    for line in rel_path.read_text().splitlines() if rel_path.exists() else []:
        e = json.loads(line)
        if e.get("to") and e.get("to_raw") and e["from"] in meta:
            printed[e["to"]].append((e["from"], re.sub(r"\s+", " ", e["to_raw"]).strip(" .,;")))
    for u in st1["unresolved_citations"]:
        dept = u["dept"]
        if dept in officers["departments"] and sum(s["kind"] == "E" for s in scen[dept]) < 8:
            if u["section"] not in officers["departments"][dept]["sections"]:
                continue
            sec = u["section"]
            m = re.search(r"-((?:19|20)\d{2})(?:-D\d{8})?$", u["cited"])
            yr = min(max(int(m.group(1)) if m else 2016, 2016), 2024)
            d = f"{rng.randint(yr + 1, 2025)}-{rng.randint(1, 12):02d}-{rng.randint(1, 26):02d}"
            seen = sorted(x for x in printed.get(u["cited"], []) if meta[x[0]]["department_code"] == dept)
            by, raw = seen[0] if seen else (None, None)
            add(dept, kind="E", section=sec, date=min(d, AS_OF),
                subject=meta[by]["subject"] if by else "Proposal relying on an earlier order",
                cite=[u["cited"]], **({"cite_raw": {u["cited"]: raw}, "cited_in": by} if by else {}),
                conflict={"type": "E", "cited": u["cited"], "governing": None,
                          "reason": "The cited order is not in the records available; the authority cannot be verified."},
                touchpoints=[11, 10, 15], movement=movement(dept, sec, officers, to_head=False), source=u)

    # ---- D: a later file on the same matter ignores an earlier synthetic file (precedent inconsistency, review only)
    for dept, items in scen.items():
        cleans = [s for s in items if s["kind"] == "CLEAN"]
        for base in cleans[:8]:
            d = after(base["date"], 60, 400)
            if d:
                add(dept, kind="D", section=base["section"], date=d, subject=base["subject"], cite=list(base["cite"]),
                    conflict={"type": "D", "cited": base["key"], "governing": None,
                              "reason": "An earlier file on the same matter exists in this section; the note does not "
                                        "refer to it and proposes a different disposal. Review recommended."},
                    precedent=base["key"], touchpoints=[9, 5, 3], movement=movement(dept, base["section"], officers, False))

    # ---- trim / balance to TARGET per department, keeping every type and ~27% clean
    final = {}
    for dept, items in scen.items():
        by = collections.defaultdict(list)
        for s in items:
            by[s["kind"]].append(s)
        n_clean = round(TARGET * CLEAN_SHARE)
        rng.shuffle(by["CLEAN"]); rng.shuffle(by["F"])
        keep = by["CLEAN"][:n_clean] + by["E"][:5] + by["D"][:4] + by["A"]       # every A chain is scarce: keep all
        rest = TARGET - len(keep) - 10            # room for the 10 hand-picked B / C / G per department
        keep += by["F"][: max(0, rest)]
        short = TARGET - 10 - len(keep)            # a department with few chains: more E / D / clean files
        for extra in (by["E"][5:], by["D"][4:], by["CLEAN"][n_clean:]):
            take = extra[: max(0, short)]
            keep += take; short -= len(take)
        final[dept] = sorted(keep, key=lambda s: s["date"])
        # A type D file needs its earlier file. Where trimming dropped that one, point to the latest earlier kept file
        # of the same section on the same subject (no random draw; found 14 Nov 2026: 4 D files had none).
        kept = {s["key"] for s in final[dept]}
        for s in final[dept]:
            if s["kind"] == "D" and s["precedent"] not in kept:
                same = [x for x in final[dept] if x["section"] == s["section"] and x["subject"] == s["subject"]
                        and x["date"] < s["date"] and x["kind"] != "D"]
                if not same:      # no earlier file on the matter is left: it is not a type D case; keep it as clean
                    s.update(kind="CLEAN", conflict=None, relabelled=True,
                             why_clean="Planned as type D, but no earlier file on the same matter is in the set.")
                    s.pop("precedent")
                    continue
                s["precedent"] = same[-1]["key"]
                s["conflict"] = dict(s["conflict"], cited=same[-1]["key"])

    # ---- hand-picked B / C / G (read against the orders): the anchor must match the real order's text
    hp = yaml.safe_load((V2 / "scenarios" / "handpicked_bcg.yaml").read_text())
    for dept, items in hp["departments"].items():
        for h in items:
            rule = meta.get(h["rule"])
            if rule is None:
                sys.exit(f"hand-picked {dept} {h['id']}: {h['rule']} is not in the corpus")
            for extra in h.get("also_cite", []):
                if extra not in meta:
                    sys.exit(f"hand-picked {dept} {h['id']}: also_cite {extra} is not in the corpus")
            t = text(rule)
            m = re.search(h["anchor"], t, re.I)
            if not m:
                sys.exit(f"hand-picked {dept} {h['id']}: anchor not found in {h['rule']}: {h['anchor']!r}")
            entry = {"key": f"{dept}-{h['type']}-H{h['id']}", "dept": dept, "synthetic": True, "kind": h["type"],
                     "section": h["section"], "date": h["date"], "subject": h["subject"],
                     "cite": [h["rule"], *h.get("also_cite", [])],   # also_cite: e.g. the order that partly supersedes the rule
                     "conflict": {"type": h["type"], "cited": h["rule"], "governing": h["rule"], "reason": h["reason"],
                                  "quote_governing": t[max(0, m.start() - 120): m.end() + 160]},
                     "hand_reviewed": True, "touchpoints": [11, 13, 10] + ([1, 2] if h.get("synthetic_doc") else [6]),
                     "movement": movement(dept, h["section"], officers, to_head=True)}
            if h.get("proposal"):
                entry["proposal"] = h["proposal"]
            for k in ("synthetic_doc", "synthetic_doc_2"):
                if h.get(k):
                    entry[k] = dict(h[k], label="SYNTHETIC — not a real order")
            if (dept, h["section"]) in restricted:
                entry["touchpoints"].append(20)
            final[dept].append(entry)
        final[dept].sort(key=lambda x: x["date"])

    # ---- touchpoints: make sure all 20 appear several times per department
    for dept, items in final.items():
        for i, s in enumerate(items):
            s["touchpoints"] = sorted(set(s["touchpoints"]) | {(i % 20) + 1})
        for s in items:
            if s.get("conflict") is None and rng.random() < 0.25:
                s["touchpoints"] = sorted(set(s["touchpoints"]) | {16})            # closed file -> precedent index
        for s in items:
            if s["kind"] == "F" and rng.random() < 0.3:
                s["touchpoints"] = sorted(set(s["touchpoints"]) | {17})            # reopened: "what has changed since"

    # ---- label corrections (owner OK 13 Nov 2026; after the touchpoint draw so no other file changes): a "clean" file found to rely on a superseded / lapsed order
    rl = V2 / "scenarios" / "relabel_v2.yaml"
    for r in (yaml.safe_load(rl.read_text())["relabel"] if rl.exists() else []):
        dept = r["key"].split("-")[0]
        sc = next((s for s in final[dept] if s["key"] == r["key"]), None)
        if sc is None or sc["date"] != r["date"] or sc["cite"] != r["cite"]:
            sys.exit(f"relabel {r['key']}: the scenario no longer matches (date / cited orders) — review the entry")
        gov = meta.get(r["governing"])
        t = text(gov) if gov else ""
        m = re.search(r["anchor"], t, re.I)
        if not m:
            sys.exit(f"relabel {r['key']}: anchor not found in {r['governing']}")
        sc.update(kind=r["type"], relabelled=True,
                  conflict={"type": r["type"], "cited": r["cited"], "governing": r["governing"], "reason": r["reason"],
                            "quote_governing": t[max(0, m.start() - 120): m.end() + 160]})
        sc.pop("why_clean", None)

    # ---- clean files must be clean against ALL verified links and the orders' stated effective dates (owner OK
    # 13 Nov 2026 17:54). A cited order must be in force on the note date (issue date or its stated later
    # commencement), and no verified later order may have superseded / amended a cited one before the note unless
    # the note cites that order too. Otherwise the note date moves into the clean window; with no window, the file
    # becomes a planted conflict (A for supersession, F for amendment or not yet in force).
    edges = [e for v in st1["chains"].values() for e in v if e["type"] in ("SUPERSEDES", "AMENDS", "REPEALS")]

    def in_force(cid: str) -> str:
        m = meta[cid]
        stated = m.get("effective_from") if m.get("effective_from_source") == "stated_in_order" else None
        return max(str(m["date"]), stated) if stated else str(m["date"])

    moved, turned = 0, 0
    for dept, items in final.items():
        for sc in items:
            if sc.get("conflict") or sc["kind"] != "CLEAN":
                continue
            cites = [c for c in sc["cite"] if c in meta]
            lo = max(in_force(c) for c in cites)
            changes = sorted(((str(meta[e["newer"]]["date"]), e) for e in edges
                              if e["older"] in sc["cite"] and e["newer"] not in sc["cite"] and e["newer"] in meta),
                             key=lambda x: (x[0], x[1]["newer"]))
            hi = changes[0][0] if changes else None
            # the whole note sheet must fit in the window (the approval is checked on the latest note's
            # date): a clean file with a later change carries close_by, and the renderer then moves it within
            # a few days (at most ~5)
            span = dt.timedelta(days=7)
            if hi:
                sc["close_by"] = (dt.date.fromisoformat(hi) - dt.timedelta(days=1)).isoformat()
            if lo <= sc["date"] and (hi is None or dt.date.fromisoformat(sc["date"]) + span < dt.date.fromisoformat(hi)):
                continue
            start = dt.date.fromisoformat(lo)
            end = min(dt.date.fromisoformat(hi) - dt.timedelta(days=1) if hi else dt.date(2025, 12, 31),
                      dt.date(2025, 12, 31))
            start = max(start, dt.date(2016, 1, 13))          # room for the receipt (diarised up to 12 days before)
            if start + span <= end:
                new = start + dt.timedelta(days=min(45, (end - start - span).days // 2))
                sc["why_clean"] = (sc.get("why_clean", "") + f" Note date moved from {sc['date']} into the window "
                                   f"{start.isoformat()} .. {end.isoformat()} when nothing had changed the cited "
                                   f"orders.").strip()
                sc["date"] = new.isoformat()
                moved += 1
                continue
            if sc["date"] < lo:
                c = max(cites, key=in_force)
                conflict = {"type": "F", "cited": c, "governing": c,
                            "reason": f"The note ({sc['date']}) relies on {gid(c, meta)}, which is in force only from "
                                      f"{in_force(c)}.",
                            "quote_governing": (meta[c].get("stated_effective_evidence") or {}).get("text", "")}
            else:
                e = changes[0][1]
                t = "A" if e["type"] in ("SUPERSEDES", "REPEALS") else "F"
                verb = {"SUPERSEDES": "superseded", "REPEALS": "repealed", "AMENDS": "amended"}[e["type"]]
                conflict = {"type": t, "cited": e["older"], "governing": e["newer"],
                            "reason": f"The note relies on {gid(e['older'], meta)}; {gid(e['newer'], meta)} {verb} it "
                                      f"before the note was written ({sc['date']}).",
                            "quote_governing": e.get("quote", "")}
            sc.update(kind=conflict["type"], conflict=conflict, relabelled=True)
            sc.pop("why_clean", None)
            turned += 1
    print(f"clean check against all verified links and stated effective dates: {moved} dates moved, "
          f"{turned} turned into conflicts")

    # ---- demo holdback (data collection plan step 11): open files that cite the order a held-back order changes.
    # Appended last, with fixed touchpoints and no random draws, so no other file changes.
    hb_path = V2 / "scenarios" / "holdback_v2.yaml"
    hb = yaml.safe_load(hb_path.read_text()) if hb_path.exists() else None
    if hb:
        held = ST / "holdback" / hb["order"] / "meta.json"
        if hb["order"] in meta or not held.exists():
            sys.exit(f"holdback: {hb['order']} must be in staging/holdback/ and not in the corpus")
        held_date = str(json.loads(held.read_text())["date"])
        for n, h in enumerate(hb["files"], 1):
            dept = h["dept"]
            missing = [c for c in h["cite"] if c not in meta]
            if missing or hb["changes"] not in h["cite"]:
                sys.exit(f"holdback file {n}: cited orders not held or {hb['changes']} not cited: {missing}")
            if not (max(s["date"] for s in final[dept]) <= h["date"] < held_date):
                sys.exit(f"holdback file {n}: date must be after the department's last file and before {held_date}")
            final[dept].append({
                "kind": "CLEAN", "section": h["section"], "date": h["date"], "subject": h["subject"], "cite": h["cite"],
                "conflict": None,
                "why_clean": f"Cites {' read with '.join(gid(c, meta) for c in h['cite'])}; nothing later is in the "
                             f"corpus. Open on purpose: the held-back {hb['order']} changes {hb['changes']} in the demo.",
                "touchpoints": [4, 6, 8, 11], "movement": movement(dept, h["section"], officers, to_head=True),
                "key": f"{dept}-CLEAN-HK{n}", "dept": dept, "synthetic": True, "open": True, "holdback": hb["order"]})

    doc = {"_note": "SYNTHETIC — plan for efiles_v2 (ADR-0020). Every cited order is a real held order unless the "
                    "conflict type is E; quotes are from the real orders. B / C / G drafts follow after hand review.",
           "departments": {d: v for d, v in sorted(final.items())}}
    (V2 / "scenarios" / "scenarios.yaml").write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120))

    print("files per department and type:")
    for d, items in sorted(final.items()):
        c = collections.Counter(s["kind"] for s in items)
        tp = collections.Counter(t for s in items for t in s["touchpoints"])
        print(f"  {d}: {len(items)}  {dict(sorted(c.items()))}  touchpoints covered {len(tp)}/20 (min {min(tp.values())})")
    print("total", sum(len(v) for v in final.values()))


if __name__ == "__main__":
    main()
