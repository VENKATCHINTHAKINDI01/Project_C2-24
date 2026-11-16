"""Audit every collected order against the CLAUDE.md §5 ingestion requirements. Read-only unless --fix.

Checks per order: required metadata, canonical ID (format, folder, uniqueness), department/year folders, date window
(from_date..as_of), G.O.(Ms) only and topic filter (for topic-collected orders), PDF present/valid/sha256 match,
OCR text present and usable (length, noise, Telugu share, page breaks, contains its own number), read-list,
source URLs. Corpus checks: duplicate PDFs, relation endpoints, failed downloads not yet recovered.

  python tools/audit_corpus.py           # report (also written to staging/manifests/audit_report.json)
  python tools/audit_corpus.py --fix     # only fixes official_url placeholders ("URL" -> null)
"""
import argparse, collections, hashlib, json, re
from datetime import date
from pathlib import Path
from common import load_scope, topic_decision, CANONICAL_RE

from common import ROOT  # data root (C2_DC_DATA_ROOT, ADR-0006)
ST = ROOT / "staging"
REQUIRED = ["canonical_id", "doc_type", "instrument", "number", "date", "department_code", "department_name", "subject",
            "hierarchy_level", "classification", "status", "effective_from", "source_url", "sha256", "files",
            "collected_via", "verification_status"]
COMMON = set("the and of to in for government order orders department dated read following issued with from by "
             "is are be this that as on at under rules employees pension finance andhra pradesh hereby date no".split())
TELUGU = re.compile(r"[ఀ-౿]")

def d(x):
    try: return date.fromisoformat(str(x)[:10])
    except Exception: return None

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--fix", action="store_true"); a = ap.parse_args()
    sc = load_scope()
    lo, as_of = d(sc.get("from_date")), d(sc.get("as_of"))
    probs = collections.defaultdict(list)   # check -> [ids]
    stats = collections.Counter(); ids = collections.Counter(); shas = collections.defaultdict(list); republishes = {}
    per = collections.Counter(); notes = {}
    metas = sorted((ST / "rule-library").rglob("meta.json"))
    for mf in metas:
        folder = mf.parent
        try: m = json.loads(mf.read_text())
        except Exception as e: probs["meta.json unreadable"].append(str(folder)); continue
        cid = m.get("canonical_id") or folder.name
        stats["orders"] += 1; ids[cid] += 1
        per[(m.get("department_code"), str(m.get("date", ""))[:4], m.get("collected_via"))] += 1
        miss = [k for k in REQUIRED if m.get(k) in (None, "", [], {})]
        if miss: probs["missing fields: " + ",".join(miss)].append(cid)
        if not CANONICAL_RE.match(cid or ""): probs["canonical ID format"].append(cid)
        if folder.name != cid: probs["folder name != canonical_id"].append(cid)
        if folder.parent.parent.name != (m.get("department_code") or ""): probs["dept folder mismatch"].append(cid)
        if folder.parent.name != str(m.get("date", ""))[:4]: probs["year folder mismatch"].append(cid)
        dt = d(m.get("date"))
        if not dt: probs["bad date"].append(cid)
        elif as_of and dt > as_of: probs["after as_of (must be holdback)"].append(cid)
        topic = m.get("collected_via") == "topic"
        if topic:
            if dt and lo and dt < lo: probs["topic order before from_date"].append(cid)
            if m.get("instrument") != "G.O.(Ms)": probs["topic order not G.O.(Ms)"].append(cid)
            ok, why = topic_decision(m.get("subject") or "", sc)
            if not ok: probs[f"fails current topic filter (run refilter.py)"].append(cid)
        ou = m.get("official_url")
        if ou and not str(ou).startswith("http"):
            probs["official_url placeholder"].append(cid)
            if a.fix:
                m["official_url"] = None; mf.write_text(json.dumps(m, ensure_ascii=False, indent=2)); stats["fixed official_url"] += 1
        if not str(m.get("source_url", "")).startswith("https://archive.org/details/") and m.get("origin") == "public" \
                and m.get("source_name", "").startswith("Internet Archive"):
            probs["source_url not archive.org"].append(cid)
        # PDF
        pdf = folder / ((m.get("files") or {}).get("original") or "order.pdf")
        if not pdf.exists(): probs["PDF missing"].append(cid)
        else:
            b = pdf.read_bytes()
            if not b.startswith(b"%PDF"): probs["PDF not a PDF"].append(cid)
            if len(b) < 2000: probs["PDF tiny (<2 KB)"].append(cid)
            h = hashlib.sha256(b).hexdigest(); shas[h].append(cid); republishes[cid] = m.get("republishes_id")
            if m.get("sha256") and m["sha256"] != h: probs["sha256 mismatch"].append(cid)
        # Known, recorded cases are counted, not re-reported (owner decisions, 12 Nov 2026)
        if m.get("withheld"):
            stats["withheld: confidential, order text not published"] += 1; continue
        if m.get("document_missing"):
            stats["document missing in source (empty PDF; get by hand)"] += 1; continue
        if m.get("ocr_status") == "needs_documentai":
            probs["waiting for Document AI OCR (text layer unusable)"].append(cid); continue
        # OCR
        ocr = folder / ((m.get("files") or {}).get("ocr") or "ocr.txt")
        if not ocr.exists(): probs["OCR text missing"].append(cid); continue
        t = ocr.read_text(errors="replace")
        n = len(t.strip()); stats["ocr_chars"] += n
        if n < 300: probs["OCR text too short (<300 chars; scanned/empty?)"].append(cid)
        if n:
            letters = sum(ch.isalnum() for ch in t); noise = 1 - letters / max(1, len(re.sub(r"\s", "", t)))
            te = len(TELUGU.findall(t)) / n
            if noise > 0.35 and te < 0.3: probs["OCR noisy (>35% symbols)"].append(cid)
            if te > 0.05: stats["orders with Telugu text"] += 1
            if "\f" in t: stats["orders with page breaks"] += 1
            num = str(m.get("number") or "")
            words = re.findall(r"[A-Za-z]{3,}", t[:6000])
            common_w = sum(w.lower() in COMMON for w in words)
            if n >= 300 and te < 0.3 and common_w < 25 and not (len(words) >= 50 and common_w / len(words) >= 0.12):  # short docs
                probs["OCR unreadable (few English words; needs Document AI re-OCR)"].append(cid)
            if num and not re.search(r"(?<!\d)0*" + re.escape(num.lstrip("0") or "0") + r"(?!\d)", t[:3000]):
                if m.get("number_verified"):  # a person checked the printed PDF (OCR misread the number)
                    stats["G.O. number checked on the PDF by a person (OCR misread)"] += 1
                elif m.get("number_source") == "registry":  # owner-accepted 12 Nov 2026: listing number, not printed
                    stats["G.O. number from registry listing (not printed on page 1; owner-accepted)"] += 1
                else:
                    probs["own G.O. number not found in first page of OCR"].append(cid)
        if m.get("read_list"): stats["orders with read_list"] += 1
        if m.get("instrument") == "G.O.(Ms)" and n:   # issue date printed on the order's own G.O. line vs metadata
            try:
                import collect_web as CW
                k, own = CW.own_line(t)
                if m.get("date_verification_status") == "verified":  # a person checked the date on the PDF
                    stats["issue date verified on the PDF by a person"] += 1
                elif k == "MS" and own and own.group(1).isdigit() and int(own.group(1)) == int(m.get("number") or -1):
                    # only the order's OWN G.O. line (same number); a cited G.O. in the subject is not its header
                    dm = CW.own_date(t, own)
                    pdf_date = CW.iso(dm)
                    if pdf_date and pdf_date != str(m.get("date")):
                        probs["issue date in the order's header differs from metadata (check which is right)"].append(
                            f"{cid} (meta {m.get('date')}, header {pdf_date})")
            except Exception:
                pass
        if m.get("status") in (None, "", "unknown"): stats["status unknown (derive from relations at ingestion)"] += 1
        if pdf.exists():
            try:
                import subprocess
                tl = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True, errors="replace").stdout
                stats["PDFs with text layer (page-level text available)" if len(tl.strip()) > 300
                      else "PDFs scanned only (page/para locations need Document AI)"] += 1
            except FileNotFoundError:
                pass
    for cid, k in ids.items():
        if k > 1: probs["duplicate canonical_id"].append(cid)
    for h, l in shas.items():
        if len(l) == 2 and (republishes.get(l[0]) == l[1] or republishes.get(l[1]) == l[0]):
            stats["gazette PDF identical to the G.O. it republishes (linked)"] += 1
        elif len(l) > 1: probs["same PDF under two IDs"].append(" = ".join(l))
    # relations
    rel = ST / "manifests" / "relations.jsonl"; known = set(ids)
    ef = ST / "manifests" / "efiles_index.json"   # synthetic e-file notes are valid relation sources
    if ef.exists():
        slugs = {re.sub(r"[^A-Z0-9]", "", e["file_no"].split("/")[0].upper()) + "-" + "-".join(e["file_no"].split("/")[1:3]).split("-")[0]
                 + "-" + e["file_no"].split("/")[2][:4] for e in json.loads(ef.read_text())}
        efile_src = lambda x: bool(x) and "-NOTE-" in x and any(x.endswith(sl) for sl in slugs)
    else:
        efile_src = lambda x: False
    if rel.exists():
        types = collections.Counter(); dangling = []
        for line in rel.read_text().splitlines():
            if not line.strip(): continue
            r = json.loads(line); types[r.get("type")] += 1
            if r.get("from") not in known and not efile_src(r.get("from")): dangling.append(r.get("from"))
            if r.get("to") is None: stats["relations unresolved (raw kept)"] += 1
            elif r["to"] in known: stats["relations resolved in corpus"] += 1
            else: stats["relations to orders not collected"] += 1
        stats.update({f"relations {k}": v for k, v in types.items()})
        if dangling: probs["relation 'from' not in corpus (re-run extract_relations)"] += sorted(set(dangling))
    # failed downloads not recovered
    fl = ST / "manifests" / "failed.jsonl"
    if fl.exists():
        have = {json.loads(p.read_text()).get("archive_identifier") for p in metas if p.exists()}
        lost = sorted({json.loads(l)["identifier"] for l in fl.read_text().splitlines() if l.strip()} - have)
        if lost: probs["failed downloads not recovered (retry later)"] += lost
    # report
    print(f"orders audited: {stats['orders']}")
    for k in sorted(k for k in stats if k != "orders"): print(f"  {k}: {stats[k]}")
    print("\nper dept/year (topic | cited):")
    rows = collections.defaultdict(lambda: [0, 0])
    for (dep, y, via), c in per.items(): rows[(dep, y)][0 if via == "topic" else 1] += c
    for (dep, y) in sorted(rows, key=lambda x: (str(x[0]), x[1]), reverse=False):
        print(f"  {dep} {y}: {rows[(dep, y)][0]} | {rows[(dep, y)][1]}")
    print("\nPROBLEMS" if probs else "\nno problems")
    for k, l in sorted(probs.items(), key=lambda x: -len(x[1])):
        print(f"  [{len(l)}] {k}: {', '.join(map(str, l[:8]))}{' …' if len(l) > 8 else ''}")
    (ST / "manifests" / "audit_report.json").write_text(json.dumps(
        {"stats": stats, "problems": {k: v for k, v in probs.items()}}, indent=2, default=str))

if __name__ == "__main__":
    main()
