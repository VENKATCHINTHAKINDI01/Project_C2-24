#!/usr/bin/env python3
"""Build the mock e-Office sandbox seed from the synthetic set v2 (ADR-0020, plan §11.6). SYNTHETIC output.

Usage (from the repo root):  python3 data/synthetic/tools/build_eoffice_seed_v2.py [--check]

Reads the rendered files in data/synthetic/mock_v1/efiles_v2/ (efiles/, directory/officers.yaml) and writes
  efiles_v2/eoffice/seed_v2.json          the sandbox Seed (same schema as the v1 seed.json)
  efiles_v2/eoffice/documents/*.txt       for ingestion: each file's correspondence pages, its note sheet (Green
                                          notes) and, for a pending file, the holder's Yellow draft note
  efiles_v2/eoffice/documents_index.csv   access tags of those pages (source-system columns only)
The real public G.O.s the notes cite are indexed separately by data_collection/tools/index_public_cited.py
(they live in the data root, outside the repo).

What the seed deliberately does NOT contain: scenario keys, planted conflicts, conflict types, cited-order
lists or anything else from ground_truth/ or scenarios/ (CLAUDE.md §9.2). The cited orders reach the
assistant only through the note text, as in a real file.
Mapping choices (synthetic, [To confirm]):
- role_rank on the v1 scale (ASO 0, SO 1, AS 2, JS 4, head 5), so access_policy.yaml applies unchanged;
- one section per profile: an Assistant Secretary over two sections gets the first (see PROGRESS.md);
- departments consulted by U.O. note (Finance FMU, GAD Ser.A, GAD Cabinet.II) appear as staff posts
  "POST-<dept>-<section>" without a sandbox login, like the v1 staff posts;
- file state: closed → closed, everything else open; a pending file is assigned to its holder.
Deterministic: the same inputs always give the same output.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
V2 = ROOT / "data" / "synthetic" / "mock_v1" / "efiles_v2"
OUT = V2 / "eoffice"
BANNER = "Mock e-Office sandbox — not NIC e-Office · synthetic data"
DOC_BANNER = "SYNTHETIC — not a real government file (C2-24 sandbox, efiles_v2).\n\n"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
AS_OF = dt.date(2025, 12, 31)

RANK = {1: 0, 2: 1, 3: 2, 5: 4, 6: 5}  # officers.yaml rank -> v1 role_rank scale
SCOPE = {"Section": "section", "Section Hierarchy": "section_hierarchy", "Department": "department",
         "Global": "global"}
SEC_CODE = {"HR-I": "HR.I", "HR-III": "HR.III", "BUDGET-I": "BUDGET.I", "SER-A": "SER.A",
            "CABINET-II": "CABINET.II", "SC-F": "SC.F", "SERVICES-II": "SER.II", "PROGRAM-I": "PROG.I",
            "EXAMS": "EXAMS"}  # the printed codes the renderer uses in file numbers (v1 uses the same form)
EXTERNAL = {  # consulted offices (renderer's movements.json "sent_to")
    "FIN01/FMU-GAD-I": ("FIN01", "FMU-GAD-I", "Deputy Secretary to Government (FMU), Finance (FMU-GAD-I)"),
    "FIN01/FMU-SE-I": ("FIN01", "FMU-SE-I", "Deputy Secretary to Government (FMU), Finance (FMU-SE-I)"),
    "GAD01/SER-A": ("GAD01", "SER.A", "Deputy Secretary to Government (Services), General Administration"),
    "GAD01/CABINET-II": ("GAD01", "CABINET.II", "Deputy Secretary to Government (Cabinet), General Administration"),
}
TS_RE = re.compile(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2} [AP]M$")
PARA_RE = re.compile(r"^(\d+)[.)]\s")
SOURCES = (
    "NIC eFile 7.0 User Manual (Ver.7.0): receipts, files, Green/Yellow notes, correspondence pages, movements",
    "efiles_v2 (ADR-0020): rendered by data_collection/tools/render_efiles_v2.py; note layout from mentor-shared "
    "samples (layout only, nothing copied)",
    "Assumed (synthetic): role ranks mapped to the v1 scale; one section per profile; consulted offices as staff "
    "posts without login; decided and reopened files are open; pending files assigned to their holder",
)


def ext_id(dest: str) -> str:
    return "POST-" + dest.replace("/", "-").replace(".", "-")


def ts(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%d/%m/%Y %I:%M %p").replace(tzinfo=IST)


def day(s: str, hh: int, mm: int) -> dt.datetime:
    return dt.datetime.strptime(s, "%d/%m/%Y").replace(hour=hh, minute=mm, tzinfo=IST)


def read_note(path: Path) -> tuple[str, str, dt.datetime, str]:
    """(colour, body text, signed at, signature block). Body = between 'Note # n' and the signature."""
    lines = path.read_text(encoding="utf-8").splitlines()
    colour = "yellow" if "<!-- yellow -->" in lines[:3] else "green"
    start = next(i for i, x in enumerate(lines) if x.startswith("Note # ")) + 1
    sig = max(i for i, x in enumerate(lines) if TS_RE.match(x))
    body = "\n".join(lines[start:sig]).strip("\n")
    return colour, body, ts(lines[sig]), "\n".join(lines[sig:]).strip()


def strip_banner(text: str) -> str:
    return "\n".join(x for x in text.splitlines() if not x.startswith("<!-- SYNTHETIC")).lstrip("\n")


def receipt_fields(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z. ]+?):\s*(.*)$", line)
        if m and m.group(1) in ("Receipt No.", "Diary Date", "Sender", "Letter Ref. No.", "U.O. Ref. No.",
                                "Main Category", "Subject", "Type"):
            out[m.group(1)] = m.group(2).strip()
    return out


def page_title(text: str, n: int, subject: str) -> str:
    if n == 1:
        return subject
    for line in strip_banner(text).splitlines():
        line = line.strip()
        if line.startswith("U.O.No."):
            return "U.O. Note " + line
        if re.search(r"\bNo\.?\s*\S+, dated", line) and not line.startswith("SYNTHETIC"):
            return line
    return f"Correspondence p.{n}"


def build() -> tuple[dict, list[dict], dict[str, str]]:
    officers = yaml.safe_load((V2 / "directory" / "officers.yaml").read_text(encoding="utf-8"))
    depts = officers["departments"]
    profiles = []
    for o in officers["officers"]:
        secs = [s for s in o["sections"] if s != "ALL"]
        scope = SCOPE[o["scope"]]
        section = SEC_CODE[secs[0]] if secs and scope in ("section", "section_hierarchy") else None
        dname = depts[o["dept"]]["name"].replace(" Department", "")
        post = f"{o['post']} ({section})" if section else f"{o['post']}, {dname}"
        profiles.append({"user_id": o["id"], "name": o["name"], "post": post, "role_rank": RANK[o["rank"]],
                         "department": o["dept"], "section": section, "clearance": o["clearance"],
                         "search_scopes": [scope], "login": True})
    for dest, (dept, sec, post) in sorted(EXTERNAL.items()):
        profiles.append({"user_id": ext_id(dest), "name": post, "post": post, "role_rank": 0, "department": dept,
                         "section": sec, "clearance": "RESTRICTED", "search_scopes": ["individual"],
                         "login": False})
    posts = {p["user_id"]: p["post"] for p in profiles}

    files, notes, corr, moves, receipts, docs = [], [], [], [], [], []
    assignments: dict[str, list[str]] = {}
    texts: dict[str, str] = {}
    later: dict[str, list[str]] = {}
    folders = sorted(p.parent for p in (V2 / "efiles").rglob("file.json"))
    for d in folders:
        f = json.loads((d / "file.json").read_text(encoding="utf-8"))
        for ref in json.loads((d / "links.json").read_text(encoding="utf-8")):
            later.setdefault(ref["file_no"], []).append(f["file_no"])
    for d in folders:
        f = json.loads((d / "file.json").read_text(encoding="utf-8"))
        comp, fno, sec = f["computer_no"], f["file_no"], SEC_CODE[f["section"]]
        safe = re.sub(r"[^A-Za-z0-9.-]+", "_", fno)
        mv = json.loads((d / "movements.json").read_text(encoding="utf-8"))
        # notes
        n_next = 1
        head = f"File No. {fno} (Computer No. {comp})\nSubject: {f['subject']}\n\n"
        sheet, draft = [], None
        note_movs = [m for m in mv if m["note"] is not None]
        for k, path in enumerate(sorted((d / "Note File1").glob("note-*.md")), start=1):
            colour, body, at, sign = read_note(path)
            if colour == "green":
                sheet.append(f"Note # {k}\n{body}\n\n{sign}\n")
            else:
                draft = f"[Draft note — Yellow Note, not yet confirmed]\nNote # {k}\n{body}\n\n{sign}\n"
            nums = [int(m.group(1)) for x in body.splitlines() if (m := PARA_RE.match(x))]
            para_from = nums[0] if nums else n_next
            n_next = (nums[-1] + 1) if nums else n_next
            author = note_movs[k - 1]["from"]
            green = colour == "green"
            notes.append({"note_id": f"{comp}-N{k}", "computer_no": comp, "note_no": k, "paragraph_from": para_from,
                          "state": "green" if green else "yellow", "author": author, "author_post": posts[author],
                          "text_source": "native", "source_uri": f"efiles_v2/{path.relative_to(V2).as_posix()}",
                          "versions": [{"version": 1, "text": body, "saved_at": at.isoformat(), "saved_by": author}],
                          "confirmed_at": at.isoformat() if green else None, "created_by_assistant": False})
            if not green:
                assignments.setdefault(author, []).append(fno)
        # movements (file sent to the next holder; consultations out and back)
        seq, last_at = 0, None
        for m in mv:
            if m.get("external"):
                to = ext_id(m["sent_to"])
                out_at = max(day(m["at"], 10, 0), (last_at or day(m["at"], 10, 0)) + dt.timedelta(minutes=10))
                back_at = day(m["returned"], 9, 45)
                for frm, too, when, rem in ((m["from"], to, out_at, m["remarks"]),
                                            (to, m["from"], back_at, "returned with U.O. note")):
                    seq += 1
                    moves.append({"computer_no": comp, "seq": seq, "from_user": frm, "to_user": too,
                                  "sent_at": when.isoformat(), "due_on": None, "priority": "normal", "remarks": rem,
                                  "sent_back": too != to})
                last_at = back_at
                continue
            if m["sent_to"] is None or m["sent_to"] == m["from"]:   # no movement for consecutive notes by one holder
                continue
            seq += 1
            when = ts(m["at"])
            moves.append({"computer_no": comp, "seq": seq, "from_user": m["from"], "to_user": m["sent_to"],
                          "sent_at": when.isoformat(), "due_on": None, "priority": "normal", "remarks": m["remarks"],
                          "sent_back": m["remarks"].startswith("returned")})
            last_at = when
        # correspondence pages (+ the receipt for p.1) and their text for ingestion
        rcomp = str(int(comp) + 1)
        for n, path in enumerate(sorted((d / "Correspondence").glob("R-*.md")), start=1):
            raw = path.read_text(encoding="utf-8")
            name = f"{safe}_{path.stem}.txt"
            texts[name] = DOC_BANNER + strip_banner(raw)
            docs.append({"id": f"{comp}-C{n}", "file": f"eoffice/documents/{name}", "department": f["department_code"],
                         "section": sec, "classification": f["classification"], "raw_reference": f"File No.{fno}"})
            corr.append({"correspondence_id": f"{comp}-C{n}", "computer_no": comp, "kind": "puc" if n == 1 else "fr",
                         "page_from": n, "page_to": n, "title": page_title(raw, n, f["subject"]), "canonical_id": None,
                         "receipt_id": rcomp if n == 1 else None})
            if n == 1:
                r = receipt_fields(raw)
                ref = r.get("Letter Ref. No.") or r.get("U.O. Ref. No.") or ""
                lm = re.match(r"^(.*?), dated (\d{2}-\d{2}-\d{4})$", ref)
                receipts.append({
                    "computer_no": rcomp, "receipt_no": r["Receipt No."], "nature": "E",
                    "diary_date": dt.datetime.strptime(r["Diary Date"], "%d-%m-%Y").date().isoformat(),
                    "sender": r["Sender"].removesuffix(" (synthetic)"),
                    "letter_ref": lm.group(1) if lm else (ref or None),
                    "letter_date": dt.datetime.strptime(lm.group(2), "%d-%m-%Y").date().isoformat() if lm else None,
                    "main_category": r["Main Category"], "subject": r["Subject"], "dealing_section": sec,
                    "source_uri": f"mock://efiles_v2/eoffice/documents/{name}", "put_in_file": comp,
                    "assumed_fields": []})
        for stem, text in (("NOTES", "\n".join(sheet)), ("DRAFT", draft)):
            if text:
                name = f"{safe}_{stem}.txt"
                texts[name] = DOC_BANNER + head + text
                docs.append({"id": f"{comp}-{stem}", "file": f"eoffice/documents/{name}",
                             "department": f["department_code"], "section": sec,
                             "classification": f["classification"], "raw_reference": f"File No.{fno}"})
        files.append({"computer_no": comp, "file_no": fno, "nature": "E", "file_head": fno.split("/")[0],
                      "subject": f["subject"], "description": "", "department": f["department_code"],
                      "dealing_section": sec, "category": f["section_label"], "classification": f["classification"],
                      "state": "closed" if f["status"] == "closed" else "open",
                      "created_by": mv[0]["from"] if mv else None, "created_on": f["opened"],
                      "previous_references": [x["file_no"] for x in json.loads((d / "links.json").read_text())],
                      "later_references": sorted(later.get(fno, [])), "linked_files": []})
    seed = {"synthetic": True, "banner": BANNER, "corpus": "efiles_v2", "as_of": AS_OF.isoformat(),
            "sources": list(SOURCES), "profiles": profiles,
            "assignments": {u: sorted(v) for u, v in sorted(assignments.items())},
            "files": files, "notes": notes, "correspondence": corr, "movements": moves, "receipts": receipts}
    return seed, docs, texts


def render_index(docs: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["id", "file", "department", "section", "classification", "raw_reference"],
                       lineterminator="\n")
    w.writeheader()
    w.writerows(docs)
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the outputs are out of date")
    args = ap.parse_args()
    seed, docs, texts = build()
    want = {OUT / "seed_v2.json": json.dumps(seed, ensure_ascii=False, indent=1) + "\n",
            OUT / "documents_index.csv": render_index(docs)}
    want.update({OUT / "documents" / k: v for k, v in texts.items()})
    if args.check:
        stale = [p for p, t in want.items() if not p.exists() or p.read_text(encoding="utf-8") != t]
        extra = set((OUT / "documents").glob("*.txt")) - set(want) if (OUT / "documents").exists() else set()
        if stale or extra:
            print(f"out of date: {len(stale)} stale, {len(extra)} extra — run without --check", file=sys.stderr)
            return 1
        return 0
    (OUT / "documents").mkdir(parents=True, exist_ok=True)
    for p, t in want.items():
        p.write_text(t, encoding="utf-8")
    print(f"seed_v2.json: {len(seed['profiles'])} profiles, {len(seed['files'])} files, {len(seed['notes'])} notes, "
          f"{len(seed['movements'])} movements, {len(seed['correspondence'])} pages, {len(seed['receipts'])} receipts; "
          f"{len(texts)} documents indexed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
