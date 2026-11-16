"""AP e-Gazette (apegazette.cgg.gov.in) — search, list, and (optionally) download a few gazettes.

How the site works (inspected 18 Oct 2026): GET /searchAllGazette gives a session cookie and a hidden _csrf token;
the search form (id searchGazetteForm) POSTs to searchAllGazettes with departmentId, gazeeteTypeId (1 Extraordinary,
2 Weekly), gazeetePartId (9 = Part IV-B), year, month1, fromdate, todate, gazetteno, abstract1. Results open with
uploadGazette_view?filePath=…  The captcha on the page belongs to the officer login, not to search.

Default is a DRY RUN: one GET + one search POST, results listed, nothing downloaded.
  python tools/collect_gazette.py --options                              # print department / type / part lists
  python tools/collect_gazette.py --dept FINANCE --type 1 --year 2024              # list (dry run)
  python tools/collect_gazette.py --dept FINANCE --type 1 --year 2024 --pick 9     # save result no. 9 only
Batch mode for Rules / Acts (owner OK 12 Nov 2026): every department x year x gazette type, keeping only rows
whose abstract is about Rules, Regulations, Acts, Ordinances or Codes (skip_topics still apply). Dry run by default;
--download saves them (10 s between requests, stops after 3 errors in a row). Candidates are also written to
staging/manifests/gazette_candidates.jsonl.
  python tools/collect_gazette.py --batch                                   # dry run: FIN, GAD, School Education, 2016-2025
  python tools/collect_gazette.py --batch --dept LAW --years 2016-2025      # one department (repeat --dept for more)
  python tools/collect_gazette.py --batch --download --limit 5              # test: save 5
  python tools/collect_gazette.py --batch --download --limit 0              # save all candidates
Notes (tested 18 Oct 2026): only the YEAR filter returns results; date ranges (DDMMYYYY) return nothing.
Download links are signed tokens tied to the search; the stable key is the file path inside the token.
Raw result page is saved to staging/manifests/egazette_last_search.html so the parser can be checked.
"""
import argparse, base64, json, re, time
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, quote
import requests
from common import load_scope, topic_decision, canonical_id, sha256, now, write_json, append_jsonl, provenance, CANONICAL_RE, LEVEL

from common import ROOT  # data root (C2_DC_DATA_ROOT, ADR-0006)
ST = ROOT / "staging"
BASE = "https://apegazette.cgg.gov.in/"
UA = "c2-24-fellowship-research/0.1 (public G.O. corpus; contact via GitHub VENKATCHINTHAKINDI01)"
DELAY = 10
txt = lambda x: re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", x or ""))).strip()

def get_form(s):
    r = s.get(BASE + "searchAllGazette", timeout=40); r.raise_for_status(); h = r.text
    f = re.search(r'<form\b[^>]*id="searchGazetteForm"[^>]*>(.*?)</form>', h, re.I | re.S)
    if not f: raise SystemExit("search form not found — the page changed; re-run tools/inspect_form.py")
    tag = re.search(r'<form\b[^>]*id="searchGazetteForm"[^>]*>', h, re.I).group(0)
    action = (re.search(r'action="([^"]*)"', tag) or [None, "searchAllGazettes"])[1]
    body = f.group(1)
    hidden = dict(re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', body, re.I))
    hidden.update({k: v for v, k in re.findall(r'<input[^>]*type="hidden"[^>]*value="([^"]*)"[^>]*name="([^"]+)"', body, re.I)})
    selects = {}
    for sel in re.finditer(r'<select\b[^>]*name="([^"]+)"[^>]*>(.*?)</select>', body, re.I | re.S):
        selects[sel.group(1)] = [(v, txt(l)) for v, l in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', sel.group(2), re.I | re.S)]
    dates = [re.sub(r"\s+", " ", t) for t in re.findall(r'<input[^>]*name="(?:fromdate|todate)"[^>]*>', body, re.I)]
    return urljoin(BASE, action), hidden, selects, dates

def pick(options, want):
    if want is None: return ""
    for v, l in options:
        if want == v or want.upper() == l.upper() or l.upper().startswith(want.upper()): return v
    raise SystemExit(f"'{want}' not in options: {[l for _, l in options][:40]} …")

MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
LEAD = re.compile(r"(?i)^(?:from|dated?|dt\.?)\s+")   # "G.O.Ms.No.18, FROM FINANCE" -> "FINANCE"
GO_IN = re.compile(r"G\.?O\.?\s*(Ms|Rt)\.?\s*No\.?\s*(\d+)\s*,?\s*([A-Za-z .&]+?)\s*\(", re.I)

def file_key(token):
    """Signed download token -> stable file path inside it (/Uploads/APGAZETTE/gazettes/<id>.pdf)."""
    try:
        payload = token.split(".")[1]; payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("sub") or token
    except Exception:
        return token

def pub_date(cell):
    m = re.search(r"(\d{1,2})-([a-z]{3})-((?:19|20)\d{2})", cell or "", re.I)
    if m and m.group(2).lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{2})[-/.](\d{2})[-/.]((?:19|20)\d{2})", cell or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None

def part_code(cell):   # "Extraordinary / PART IV-B" -> "EIVB", "Weekly / Part I" -> "WI"
    kind = "E" if "extra" in (cell or "").lower() else "W" if "week" in (cell or "").lower() else "X"
    if "rules supplement" in (cell or "").lower(): kind += "RS"   # e.g. "Rules Supplement to Part I" -> "ERSI"
    m = re.search(r"part\s*([IVX]+(?:\s*-?\s*[A-Z])?)", cell or "", re.I)
    return kind + (re.sub(r"[^A-Z]", "", m.group(1).upper()) if m else "")

def gazette_kind(part, abstract, act):
    """What the gazette carries decides its level (CLAUDE.md hierarchy): Act text (Part IV-B / --act) = 2,
    statutory rules notified = 3, everything else (commencement notices, republished G.O.s, notifications) = 4."""
    a = (abstract or "").lower()
    if act or "IV" in part_code(part): return "ACT", LEVEL["ACT"]
    if re.search(r"\brules?\b[^.]{0,80}\b(notified|amendment|issued)|amendment[s]? to the [^.]{0,120}\brules\b", a) \
            and "commencement" not in a:
        return "RULE", LEVEL["RULE"]
    return "NOTIFICATION", LEVEL["GOMS"]

def pdf_text(path):
    try:
        from pypdf import PdfReader
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages)
    except Exception:
        return ""

def parse_results(h):
    """Columns (18 Oct 2026): S.No | Type/Part | Department | Abstract | Date of Publication | Gazette No |
    Issue No | Notification No | Download(openDocument('<token>'))"""
    body = h.split("<tbody", 1)[-1] if "<tbody" in h else h
    rows = []
    for tr in re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.I | re.S):
        cells = [txt(c) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", tr, re.I | re.S)]
        tok = re.search(r"openDocument\(\s*'([^']+)'", tr)
        if not (tok and len(cells) >= 8): continue
        go = GO_IN.search(cells[3])
        rows.append({"sno": cells[0], "part": cells[1], "dept": cells[2], "abstract": cells[3],
                     "date": pub_date(cells[4]), "gazette_no": re.sub(r"\D", "", cells[5]) or None,
                     "issue_no": cells[6], "notification_no": cells[7], "token": tok.group(1),
                     "file": file_key(tok.group(1)),
                     "republishes": (f"G.O.{go.group(1).title()}.No.{go.group(2)}, {LEAD.sub('', go.group(3).strip())}"
                                     if go else None)})
    return rows

def republished_id(rep, year, scope):
    """'G.O.Ms.No.18, FINANCE' + gazette year -> AP-FIN01-GOMS-18-2024 (only when the department is in scope)."""
    from common import dept_code_for
    m = re.match(r"G\.O\.(Ms|Rt)\.No\.(\d+), (.+)", rep or "")
    dc = dept_code_for(m.group(3), scope) if m else None
    return canonical_id(dc, "GO" + m.group(1).upper(), m.group(2), year) if (dc and year) else None

def held_index():
    """gazette file keys already saved, and G.O. canonical IDs already held (to mark republished G.O.s)."""
    files, ids = set(), set()
    for p in (ST / "rule-library").rglob("meta.json"):
        try:
            m = json.loads(p.read_text()); ids.add(m.get("canonical_id"))
            if m.get("gazette_file"): files.add(m["gazette_file"])
        except Exception: pass
    return files, ids

# Batch filter, tightened after the first dry run (12 Nov 2026: 637 -> 238 candidates). "Act" alone matched bans under
# the Public Security Act, pipeline declarations and holidays; "Rules Supplement" parts also carry ordinary G.O.s.
RULES = re.compile(r"\brules\b|\brule\s+\d|\bregulations\b|\bcode\b|\bmanual\b|\bbye-?laws?\b", re.I)
ACT_CHANGE = re.compile(r"\b(?:act|ordinance)\b[^.]{0,80}\b(?:coming into force|commencement|come into force|amendment|amended)", re.I)
NOISE = re.compile(r"\belection|\bholiday|\bdeclaration of (?:the )?(?:premises|repeater|motor|sub-?station)|public security act|takeover", re.I)
DEFAULT_DEPTS = ["FINANCE", "GENERAL ADMINISTRATION", "SCHOOL EDUCATION"]
APPROPRIATION = re.compile(r"appropriation|vote[- ]on[- ]account", re.I)

def select(row, scope):
    """Batch filter: Rules / Acts and notifications about them. skip_topics (individual cases) still win."""
    keep, why = topic_decision(row["abstract"], scope, all_topics=True)
    if not keep: return None, why
    if APPROPRIATION.search(row["abstract"] or ""): return None, "appropriation / vote on account (not kept, scope.yaml)"
    a = row["abstract"] or ""
    if NOISE.search(a): return None, "election / holiday / declaration / ban / takeover"
    if row.get("dept_name", "") not in ("", *DEFAULT_DEPTS):   # other departments (e.g. LAW): Acts, or rules on our topics
        if not (ACT_CHANGE.search(a) or topic_decision(a, scope)[0]): return None, "other department, not on our topics"
    kind, _ = gazette_kind(row["part"], a, None)
    if kind in ("ACT", "RULE"): return kind, "rules/act"
    if RULES.search(a) or ACT_CHANGE.search(a): return "NOTIFICATION", "about rules / an Act coming into force or amended"
    return None, "not about rules/acts"

def save_row(s, action, row, scope, files, act=None, via="manual-target"):
    """Download one result (its token belongs to the search just made) and file it. Returns a status line."""
    if row["file"] in files: return f"already held ({row['file']})"
    if not (row["gazette_no"] and row["date"]): return "gazette number/date unreadable — not saved"
    url = BASE + "uploadGazette_view?filePath=" + quote(row["token"], safe="")
    time.sleep(DELAY)
    try:
        pdf = s.get(url, timeout=90, headers={"Referer": action})
    except requests.RequestException as e:
        append_jsonl(ST / "manifests" / "failed.jsonl", {"source": "egazette", "url": row["file"], "error": str(e)[:200], "at": now()})
        raise
    if not pdf.content.startswith(b"%PDF"):
        return f"not a PDF (HTTP {pdf.status_code}, {pdf.headers.get('content-type')}) — token may have expired; not saved"
    year = row["date"][:4]; pc = part_code(row["part"])
    cid = canonical_id("GAZ", "GAZETTE", row["gazette_no"], year, filecode=pc)
    assert CANONICAL_RE.match(cid), cid
    kind, level = gazette_kind(row["part"], row["abstract"], act)
    meta = {"canonical_id": cid, "doc_type": "Gazette", "instrument": f"A.P. Gazette {row['part']}",
            "number": row["gazette_no"], "date": row["date"], "date_raw": None,
            "department_code": "GAZ", "department_name": "A.P. GAZETTE", "publishing_department": row["dept"],
            "subject": row["abstract"], "issue_no": row["issue_no"], "notification_no": row["notification_no"],
            "republishes": row["republishes"],
            "republishes_id": republished_id(row["republishes"], year, scope), "act_number": act,
            "gazette_kind": kind, "hierarchy_level": level,
            "classification": "UNCLASSIFIED", "status": "unknown", "effective_from": row["date"], "effective_to": None,
            "effective_from_source": "assumed_issue_date",
            "read_list": [], "language": "en/te", "origin": "public", "source_name": "AP e-Gazette",
            # The site serves files only through a signed token from a search; the stable reference is the
            # file path inside it, so source_url = site + that path (cite with gazette no./part/date).
            "source_url": BASE.rstrip("/") + row["file"], "source_url_direct": False,
            "gazette_file": row["file"], "official_url": None,
            "verification_status": "pending", "parse_confidence": "medium",
            "files": {"original": "order.pdf", "ocr": None},
            "collector": "tools/collect_gazette.py", "collected_via": via, "collected_at": now()}
    folder = ST / "rule-library" / "gazette" / "GAZ" / year / cid
    if folder.exists():
        other = json.loads((folder / "meta.json").read_text())
        if other.get("gazette_file") == row["file"]: return f"{cid} exists — not overwritten"
        # Gazette numbers repeat within a part and year (No.914 of 2022: 25 Jan and 7 Sep). Owner rule, 13 Nov 2026:
        # only the repeat gets the publication date, as memos do (AP-GAZ-GAZETTE-EI-914-2022-D20220907).
        first_id = cid
        cid = canonical_id("GAZ", "GAZETTE", row["gazette_no"], year, filecode=pc, date=row["date"])
        assert CANONICAL_RE.match(cid), cid
        meta.update({"canonical_id": cid, "id_note": f"number repeats {first_id} (published {other.get('date')}); "
                                                      "publication date added to the ID"})
        folder = ST / "rule-library" / "gazette" / "GAZ" / year / cid
        if folder.exists(): return f"{cid} exists — not overwritten"
    folder.mkdir(parents=True)
    (folder / "order.pdf").write_bytes(pdf.content)
    meta["sha256"] = sha256(folder / "order.pdf")
    text = pdf_text(folder / "order.pdf")
    body = re.sub(r"(?i)part\s+i+\s+extraordinary|registered no\.[^\n]*|notifications by government[-x ]*", "", text).strip()
    if len(body) > 300:
        (folder / "ocr.txt").write_text(text); meta["files"]["ocr"] = "ocr.txt"; meta["ocr_source"] = "PDF text layer (pypdf)"
    else:
        meta["needs_ocr"] = True   # body is a scanned image (seen in Gazette No.137 of 2024) -> Document AI
    write_json(folder / "meta.json", meta); provenance(ST, meta, "web:egazette")
    files.add(row["file"])
    return (f"saved {cid} ({len(pdf.content):,} bytes; {kind}, level {level}; "
            f"{'text layer' if meta['files']['ocr'] else 'scanned body: needs Document AI'})"
            f"{'  republishes ' + row['republishes'] if row['republishes'] else ''}")

def years_of(spec):
    a_, _, b_ = spec.partition("-")
    return [str(y) for y in range(int(b_ or a_), int(a_) - 1, -1)]

def batch(a):
    scope = load_scope(); files, _ = held_index()
    depts = a.dept_list or DEFAULT_DEPTS
    types = [t.strip() for t in a.types.split(",") if t.strip()]
    cand_path = ST / "manifests" / "gazette_candidates.jsonl"
    cand_path.parent.mkdir(parents=True, exist_ok=True); cand_path.write_text("")   # this run's list only
    s = requests.Session(); s.headers["User-Agent"] = UA
    saved = found = errors = 0
    for dept in depts:
        for year in years_of(a.years):
            for typ in types:
                try:
                    action, hidden, selects, _ = get_form(s)
                    try:
                        data = dict(hidden)
                        data.update({"departmentId": pick(selects.get("departmentId", []), dept),
                                     "gazeeteTypeId": pick(selects.get("gazeeteTypeId", []), typ),
                                     "gazeetePartId": "", "year": year, "month1": "", "fromdate": "", "todate": "",
                                     "gazetteno": "", "abstract1": ""})
                    except SystemExit as e:   # department name not on the site: say so, go on
                        print(f"!! {dept}: {e}"); break
                    time.sleep(DELAY)
                    r = s.post(action, data=data, timeout=60, headers={"Referer": BASE + "searchAllGazette"})
                    r.raise_for_status(); errors = 0
                except requests.RequestException as e:
                    errors += 1
                    append_jsonl(ST / "manifests" / "failed.jsonl", {"source": "egazette", "url": f"search {dept} {year} {typ}", "error": str(e)[:200], "at": now()})
                    print(f"!! search failed {dept} {year} type {typ}: {e}")
                    if errors >= 3: raise SystemExit("3 errors in a row — stopping (re-run later; held files are skipped)")
                    continue
                rows = parse_results(r.text)
                for row in rows: row["dept_name"] = dept
                picked = [(row, *select(row, scope)) for row in rows]
                picked = [(row, k, why) for row, k, why in picked if k]
                print(f"== {dept} {year} type {typ}: {len(rows)} results, {len(picked)} about rules/acts")
                for row, kind, why in picked:
                    found += 1
                    held = row["file"] in files
                    print(f"   {row['date'] or '????-??-??'} {part_code(row['part']):<5} No.{row['gazette_no'] or '?':<5} "
                          f"{kind:<12} {row['abstract'][:90]}{'  [held]' if held else ''}")
                    append_jsonl(cand_path, {"dept": dept, "year": year, "type": typ, "date": row["date"], "part": row["part"],
                                             "gazette_no": row["gazette_no"], "kind": kind, "abstract": row["abstract"],
                                             "file": row["file"], "held": held, "listed_at": now()})
                    if a.download and not held and (a.limit == 0 or saved < a.limit):
                        try:
                            msg = save_row(s, action, row, scope, files, via="gazette-batch")
                            errors = 0
                        except requests.RequestException as e:
                            errors += 1; msg = f"download failed (logged): {e}"
                            if errors >= 3: raise SystemExit("3 errors in a row — stopping (re-run later; held files are skipped)")
                        saved += msg.startswith("saved"); print("      ->", msg)
    print(f"\n{found} candidates listed (also in {cand_path.relative_to(ROOT)}); saved {saved}"
          + ("" if a.download else "  — dry run: add --download (with --limit N to test)"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--options", action="store_true", help="print the department / type / part lists and exit")
    ap.add_argument("--dept", action="append", help="department name or id, e.g. FINANCE, 'GENERAL ADMINISTRATION', 27 "
                                                    "(batch: repeat for several)")
    ap.add_argument("--type", default="1", help="gazette type id/name (1 Extraordinary, 2 Weekly)")
    ap.add_argument("--part", help="gazette part id/name, e.g. 9 (Part IV-B)")
    ap.add_argument("--year"); ap.add_argument("--month")
    ap.add_argument("--from", dest="dfrom"); ap.add_argument("--to", dest="dto")
    ap.add_argument("--number", help="gazette number"); ap.add_argument("--text", help="search text (abstract)")
    ap.add_argument("--pick", help="result numbers to save, e.g. 9 or 9,12 (test phase: 1-2). Without it: dry run")
    ap.add_argument("--act", help="if the saved gazette publishes an Act, its Act number (recorded, not guessed)")
    ap.add_argument("--batch", action="store_true", help="Rules/Acts across departments x years (dry run unless --download)")
    ap.add_argument("--years", default="2016-2025", help="batch: year range, e.g. 2016-2025")
    ap.add_argument("--types", default="1,2", help="batch: gazette types, 1 Extraordinary, 2 Weekly")
    ap.add_argument("--download", action="store_true", help="batch: save the candidates")
    ap.add_argument("--limit", type=int, default=5, help="batch: max files to save (0 = no cap)")
    a = ap.parse_args()
    a.dept_list, a.dept = a.dept, (a.dept[-1] if a.dept else None)
    if a.batch:
        return batch(a)
    s = requests.Session(); s.headers["User-Agent"] = UA
    action, hidden, selects, dates = get_form(s)
    if a.options:
        print("hidden fields:", list(hidden)); print("date inputs:", dates)
        for name, opts in selects.items():
            print(f"\n{name} ({len(opts)})")
            for v, l in opts: print(f"   {v:<6} {l}")
        return
    data = dict(hidden)
    data.update({"departmentId": pick(selects.get("departmentId", []), a.dept),
                 "gazeeteTypeId": pick(selects.get("gazeeteTypeId", []), a.type),
                 "gazeetePartId": pick(selects.get("gazeetePartId", []), a.part),
                 "year": a.year or "", "month1": a.month or "", "fromdate": a.dfrom or "", "todate": a.dto or "",
                 "gazetteno": a.number or "", "abstract1": a.text or ""})
    if not data["departmentId"]: raise SystemExit("--dept is required (the site refuses a search without a department)")
    print("search:", {k: v for k, v in data.items() if k != "_csrf" and v})
    time.sleep(DELAY)
    try:
        r = s.post(action, data=data, timeout=60, headers={"Referer": BASE + "searchAllGazette"})
    except requests.RequestException as e:
        append_jsonl(ST / "manifests" / "failed.jsonl", {"source": "egazette", "url": action, "error": str(e)[:200], "at": now()})
        raise SystemExit(f"search failed: {e} (logged to failed.jsonl)")
    out = ST / "manifests" / "egazette_last_search.html"; out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(r.text)
    rows = parse_results(r.text)
    print(f"HTTP {r.status_code} · {len(rows)} results · raw page: {out.relative_to(ROOT)}")
    if not rows:
        print("no results parsed — check the raw page (search may need a different date format; date inputs:", dates, ")")
        return
    files, ids = held_index()
    scope = load_scope()
    for i, row in enumerate(rows, 1):
        flags = []
        if row["file"] in files: flags.append("held")
        ok, why = topic_decision(row["abstract"], scope)
        flags.append(("topic: " + why) if ok else "skip-topic")
        if row["republishes"]:
            gid = republished_id(row["republishes"], (row["date"] or "")[:4], scope)
            flags.append(("republishes " + row["republishes"]) + (" — G.O. already held" if gid in ids else ""))
        print(f"{i:>3}. {row['date'] or '????-??-??'} {part_code(row['part']):<5} No.{row['gazette_no'] or '?':<5} "
              f"{row['abstract'][:95]}  [{'; '.join(flags)}]")
    if not a.pick:
        print("\ndry run — add --pick N (the result number) to save one; --act N if it publishes an Act"); return
    picks = [int(x) for x in a.pick.split(",") if x.strip()]
    saved = 0
    for n in picks[:2]:   # test phase: at most 2 per run
        if not 1 <= n <= len(rows): print(f"no result {n}"); continue
        try:
            msg = save_row(s, action, rows[n - 1], scope, files, act=a.act)
        except requests.RequestException as e:
            print("download failed (logged):", e); break
        saved += msg.startswith("saved"); print(f"{n}: {msg}")
    print(f"saved {saved}")

if __name__ == "__main__":
    main()
