#!/usr/bin/env python3
"""Build the mock e-Office sandbox seed from mock corpus v1 (plan §11.6). SYNTHETIC output.

Usage (from the repo root):  python3 data/synthetic/tools/build_eoffice_seed.py [--check]

Grounding (field shapes, not content):
- NIC eFile 7.0 User Manual (Ver.7.0): a receipt has a Computer No. and a Receipt No. of the form
  "sequence no./creation year/dealing_section_name"; files are Electronic/Physical, Non-SFS files use
  File-Heads; notes are Green (confirmed) or Yellow (versioned draft), numbered, signed by post;
  movement history records sender, recipient, time and remarks.
- Mock corpus v1 (`manifest.json`, `users.csv`, note headers "Note # n" and
  "name / post / dd/mm/yyyy hh:mm AM" in the e-file documents).

What the seed deliberately does NOT contain: relations, citations, conflicts, decisions or golden
answers (they stay in ground_truth/ for evaluation). Scanned notes carry no text (ingestion must OCR).
Values the corpus does not state are marked in `assumed_fields` / `sources`.
Deterministic: the same inputs always give the same seed.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "data" / "synthetic" / "mock_v1"
OUT = CORPUS / "eoffice" / "seed.json"
BANNER = "Mock e-Office sandbox — not NIC e-Office · synthetic data"

SIGN_RE = re.compile(r"^(?P<name>.+?) / (?P<post>.+?) / (?P<ts>\d{2}/\d{2}/\d{4} \d{2}:\d{2} [AP]M)$")
NOTE_RE = re.compile(r"^Note # (?P<no>\d+)$")
PARA_RE = re.compile(r"^(?P<n>\d+)\.\s")
NATIVE = {"native_pdf", "docx", "xlsx"}
CATEGORY = {"ESTT.I": "Establishment", "WORKS": "Works", "VIG": "Vigilance"}
DEPT_NAME = {"FIN01": "Finance", "GAD01": "General Administration", "USD01": "Urban Services"}
RECEIPT_COMPUTER_NO_START = 9_100_001  # clearly synthetic range, above every corpus Computer No.


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _ts(raw: str) -> str:
    return (
        dt.datetime.strptime(raw, "%d/%m/%Y %I:%M %p")
        .replace(tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))
        .isoformat()
    )


def _date(raw: str) -> str:
    return dt.datetime.strptime(raw, "%d-%m-%Y").date().isoformat()


def _pages(path: Path) -> int:
    """Page count without third-party libraries: PDF page objects; 1 for docx/xlsx."""
    if path.suffix.lower() != ".pdf":
        return 1
    return max(1, len(re.findall(rb"/Type\s*/Page(?![s])", path.read_bytes())))


def _profiles(users: list[dict[str, str]]) -> tuple[list[dict], dict[str, str]]:
    """Sandbox users from users.csv; e-Office search scope per plan §11.4 (DS and above:
    department; others: section) — the same mock rule the tests use."""
    profiles, by_post = [], {}
    for u in users:
        rank = int(u["role_rank"])
        profiles.append(
            {
                "user_id": u["user_id"],
                "name": u["label"],
                "post": u["designation"],
                "role_rank": rank,
                "department": u["department"],
                "section": None if u["section"] == "ALL" else u["section"],
                "clearance": u["clearance"],
                "search_scopes": ["department"] if rank >= 3 else ["section"],
                "login": True,
            }
        )
        by_post[u["designation"]] = u["user_id"]
    return profiles, by_post


def _staff_post(post: str, dept: str, sec: str, clearance: str) -> dict:
    """A post that signs notes but has no sandbox login (e.g. Assistant Section Officer)."""
    slug = re.sub(r"[^A-Z0-9]+", "-", post.upper()).strip("-")
    return {
        "user_id": f"POST-{slug}",
        "name": post,
        "post": post,
        "role_rank": 0,
        "department": dept,
        "section": sec,
        "clearance": clearance,
        "search_scopes": ["individual"],
        "login": False,
    }


def _notes_in(text: str) -> list[dict]:
    """Split an e-file document into notes: number, paragraphs, text, signature."""
    notes, cur = [], None
    for line in text.splitlines():
        if m := NOTE_RE.match(line.strip()):
            cur = {"no": int(m["no"]), "lines": []}
            notes.append(cur)
            continue
        if cur is None:
            continue
        if m := SIGN_RE.match(line.strip()):
            cur.update(name=m["name"], post=m["post"], ts=_ts(m["ts"]))
            cur = None
            continue
        cur["lines"].append(line)
    for n in notes:
        paras = [int(m["n"]) for ln in n["lines"] if (m := PARA_RE.match(ln.strip()))]
        n["para_from"] = paras[0] if paras else 1
        n["text"] = "\n".join(n["lines"]).strip()
    return notes


def build() -> dict:
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    users = _rows(CORPUS / "users.csv")
    profiles, by_post = _profiles(users)
    staff: dict[str, dict] = {}
    files: dict[str, dict] = {}
    notes, correspondence, movements, receipts = [], [], [], []
    statuses: dict[str, set[str]] = {}

    docs = manifest["documents"]
    for d in docs:
        if d["dept"] != "USD01" or not re.match(r"^USD01-[A-Z0-9]+/\d+/\d{4}-", d["file_no"] or ""):
            continue  # sandbox = the Urban Services secretariat's own e-files
        cno, fno, sec = d["computer_no"], d["file_no"], d["sec"]
        statuses.setdefault(cno, set()).add(d["status"])
        text = (CORPUS / "ground_truth" / "text" / f"{d['id']}.txt").read_text(encoding="utf-8")
        doc_notes = _notes_in(text)
        f = files.setdefault(
            cno,
            {
                "computer_no": cno,
                "file_no": fno,
                "nature": "E",
                "file_head": fno.split("/")[0],
                "subject": d["subject"],
                "description": "",
                "department": d["dept"],
                "dealing_section": sec,
                "category": CATEGORY[sec],
                "classification": d["classification"],
                "state": "open",
                "created_by": None,  # set from the first note; None if the corpus has no note
                "created_on": _date(d["date"]),
                "previous_references": [],
                "later_references": [],
                "linked_files": [],
            },
        )
        if not doc_notes:  # order / report / annexure issued in the file: correspondence
            correspondence.append(
                {
                    "correspondence_id": f"{cno}-C{d['id']}",
                    "computer_no": cno,
                    "kind": "puc",
                    "page_from": 1,
                    "page_to": _pages(CORPUS / d["file"]),
                    "title": d["subject"],
                    "canonical_id": d["canonical_id"],
                    "receipt_id": None,
                }
            )
            continue
        for n in doc_notes:
            author = by_post.get(n["post"])
            if author is None:
                sp = _staff_post(n["post"], d["dept"], sec, d["classification"])
                staff.setdefault(sp["user_id"], sp)
                author = sp["user_id"]
            needs_ocr = d["fmt"] not in NATIVE
            notes.append(
                {
                    "note_id": f"{cno}-N{n['no']}",
                    "computer_no": cno,
                    "note_no": n["no"],
                    "paragraph_from": n["para_from"],
                    "state": "green",
                    "author": author,
                    "author_post": n["post"],
                    "text_source": "needs_ocr" if needs_ocr else "native",
                    "source_uri": f"mock_v1/{d['file']}",
                    "versions": [
                        {
                            "version": 1,
                            "text": None if needs_ocr else n["text"],
                            "saved_at": n["ts"],
                            "saved_by": author,
                        }
                    ],
                    "confirmed_at": n["ts"],
                    "created_by_assistant": False,
                }
            )
        first = min(notes[-len(doc_notes) :], key=lambda n: n["note_no"])
        if f["created_by"] is None or first["note_no"] == 1:
            f["created_by"] = first["author"]
            f["created_on"] = first["confirmed_at"][:10]

    # file state: closed only when every document in it is decided (manifest status); else open
    for cno, sts in statuses.items():
        files[cno]["state"] = "closed" if sts == {"decided"} else "open"

    # movements: a confirmed note is followed by sending the file to the author of the NEXT note
    # number; across a gap in note numbers (notes not in the corpus) no movement is invented
    for cno in sorted(files):
        chain = sorted((n for n in notes if n["computer_no"] == cno), key=lambda n: n["note_no"])
        seq = 0
        for a, b in zip(chain, chain[1:], strict=False):
            if a["author"] == b["author"] or b["note_no"] != a["note_no"] + 1:
                continue
            seq += 1
            movements.append(
                {
                    "computer_no": cno,
                    "seq": seq,
                    "from_user": a["author"],
                    "to_user": b["author"],
                    "sent_at": a["confirmed_at"],
                    "due_on": None,
                    "priority": "normal",
                    "remarks": f"Submitted after Note #{a['note_no']}",
                    "sent_back": False,
                }
            )

    # receipts: orders of other departments received in the Urban Services secretariat (touchpoint 4)
    seq_by_year: dict[str, int] = {}
    received = sorted(
        (d for d in docs if d["dept"] in {"FIN01", "GAD01"}),
        key=lambda d: (_date(d["date"]), d["id"]),
    )
    for i, d in enumerate(received):
        day = _date(d["date"])
        year = day[:4]
        seq_by_year[year] = seq_by_year.get(year, 0) + 1
        ref = d["raw_reference"].split(", Dt.")[0]
        receipts.append(
            {
                "computer_no": str(RECEIPT_COMPUTER_NO_START + i),
                "receipt_no": f"{seq_by_year[year]}/{year}/ESTT.I",
                "nature": "E",
                "diary_date": day,
                "sender": f"{d['issuing_authority']}, {DEPT_NAME[d['dept']]} Department",
                "letter_ref": ref,
                "letter_date": day,
                "main_category": d["doc_type"],
                "subject": d["subject"],
                "dealing_section": "ESTT.I",
                "source_uri": f"mock_v1/{d['file']}",
                "put_in_file": None,
                "assumed_fields": ["diary_date", "dealing_section", "computer_no"],
            }
        )

    assignments = {
        u["user_id"]: sorted(f for f in u["assigned_files"].split(";") if f)
        for u in users
        if u["assigned_files"]
    }
    return {
        "synthetic": True,
        "banner": BANNER,
        "corpus": "mock_v1",
        "as_of": manifest["as_of"],
        "sources": [
            "NIC eFile 7.0 User Manual (Ver.7.0): receipt Computer No. + Receipt No. "
            "'sequence no./creation year/dealing_section_name'; E/P nature; Non-SFS file heads; "
            "Green/Yellow notes; movement history",
            "mock_v1 manifest.json, users.csv and note headers (synthetic corpus)",
            "Assumed (synthetic): receipt diary date = order date; receipt dealing section ESTT.I; "
            f"receipt Computer Nos from {RECEIPT_COMPUTER_NO_START}; search scope by rank "
            "(plan §11.4); movement = file sent to the next note's author (none across note-number gaps); "
            "files without notes have no creator; a file is closed only when all its documents are decided",
        ],
        "profiles": profiles + [staff[k] for k in sorted(staff)],
        "assignments": assignments,
        "files": [files[k] for k in sorted(files)],
        "notes": notes,
        "correspondence": correspondence,
        "movements": movements,
        "receipts": receipts,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if seed.json is out of date")
    args = ap.parse_args()
    text = json.dumps(build(), ensure_ascii=False, indent=1) + "\n"
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("seed.json is out of date: rerun build_eoffice_seed.py", file=sys.stderr)
            return 1
        print("seed.json up to date")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
