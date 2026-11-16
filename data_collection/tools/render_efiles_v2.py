"""Stage 3 of the synthetic set v2 (ADR-0020): render one SYNTHETIC e-File folder per scenario in scenarios.yaml.

Layout per file (public NIC e-Office references, [To confirm] with the department; v1 generator's folder names):
  file.json          file no., computer no., subject, section, classification, status (open / decided / closed / reopened)
  Correspondence/    R-001.md receipt (diary details) + R-002/3.md labelled SYNTHETIC lower instruments (G / B / C cases)
  Note File1/        note-NNN.md: Green notes in movement order, signed "time / NAME / DESIGNATION"; a pending file
                     ends with the current holder's Yellow (draft) note
  Drafts/            DFA-001.md in the layout of our real G.O.s (Abstract … Read the following … ORDER … BY ORDER AND IN
                     THE NAME OF THE GOVERNOR OF ANDHRA PRADESH … To / Copy to), version 1.0, unsigned
  GO/link.json       the real orders cited (canonical IDs; for type E the unresolved reference)
  movements.json     from / to / at / remarks for every movement
  links.json         Link File / Previous References (type D precedent, touchpoints 5 and 9)
Outputs next to them: directory/officers.json, access_matrix.csv, ground_truth/efiles_v2_conflicts.json (EVAL ONLY),
manifests/efiles_v2_index.json.

Rules kept from v1: every statement about a real order is either its citation or a quote verified at stage 1/2;
everything else is about the synthetic case and says so (banner). Names of people and offices in the cases are invented.

  python tools/render_efiles_v2.py --sample 3     # render 3 files (one per department) into efiles_v2/_sample/
  python tools/render_efiles_v2.py                # render all (refuses if efiles_v2/efiles/ is not empty)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import random
import re
import shutil
import sys
import time
import zlib
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import ROOT, write_json  # noqa: E402

ST = ROOT / "staging"
V2 = HERE.parents[1] / "data" / "synthetic" / "mock_v1" / "efiles_v2"
BANNER = "<!-- SYNTHETIC — not a real government file. Cites real public G.O.s. (C2-24 efiles_v2) -->\n"
FILE_HEAD = {  # e-File head per section, in the real form "<DEPT>-<SECTION CODE>0<SUBJECT CODE>" (e.g. FIN01-FMU0MISC/284/2026-
              # FMU-GAD-I in a mentor-shared sample); section and subject codes here are mock — [To confirm]
    ("FIN01", "HR-I"): ("FIN01-HRPLG0REC", "HR.I"), ("FIN01", "HR-III"): ("FIN01-HRPEN0PEN", "HR.III"),
    ("FIN01", "BUDGET-I"): ("FIN01-BUDG0BRO", "BUDGET.I"),
    ("GAD01", "SER-A"): ("GAD01-SERA0SER", "SER.A"), ("GAD01", "CABINET-II"): ("GAD01-CABN0BR", "CABINET.II"),
    ("GAD01", "SC-F"): ("GAD01-SCF0ACB", "SC.F"),
    ("ESE01", "SERVICES-II"): ("ESE01-SERV20TRF", "SER.II"), ("ESE01", "PROGRAM-I"): ("ESE01-PROG10RTE", "PROG.I"),
    ("ESE01", "EXAMS"): ("ESE01-EXAM0EXM", "EXAMS"),
}
OFFICES = {
    "FIN01": ["Director of Treasuries and Accounts, Vijayawada", "District Treasury, Guntur", "Pay and Accounts Office, Vijayawada",
              "District Treasury, Kakinada", "Director of Works Accounts, Vijayawada"],
    "GAD01": ["Commissioner of Land Administration", "District Collector, Krishna", "A.P. Public Service Commission",
              "Director General, Anti-Corruption Bureau", "Commissioner, Information and Public Relations"],
    "ESE01": ["Commissioner of School Education, Amaravati", "District Educational Officer, Krishna",
              "Regional Joint Director of School Education, Kakinada", "Director of Government Examinations",
              "District Educational Officer, Guntur"],
}
# Inter-department U.O. notes (AP Secretariat practice: a proposal with a financial implication goes to the Finance
# Department for concurrence; Finance's FMU sections each serve one administrative department, e.g. "FMU-GAD-I" in a
# mentor-shared sample). Section codes and U.O. number shape are mock — [To confirm].
FMU = {"GAD01": ("FMU-GAD-I", "General Administration"), "ESE01": ("FMU-SE-I", "School Education")}
FIN_MATTER = re.compile(r"allowance|relief|pay\b|pay scale|scales? of pay|remuneration|honorari|incentive|arrear|"
                        r"creation of (?:\w+ )?posts?|sanction|grant|budget|fund|expenditure|scheme|reimburse|"
                        r"financial|cost|stipend|compensation|"
                        # matters that create posts or fill them (Finance permission / concurrence)
                        r"creation of new department|recruitment to various posts|recruitment test|up-?gradation", re.I)
GAD_SERVICES = re.compile(r"service rules|subordinate service|adhoc rules|regulation of transfers\) rules|"
                          r"public service commission|age limit|age relaxation|deputation|seniority", re.I)
CABINET = re.compile(r"revised pay scales|new pension system|district restructuring|\bpolicy\b", re.I)
# Who is consulted, in the order the file goes out: Finance (cost / posts), then General Administration (Services) on
# service and recruitment rules, then the Council of Ministers through General Administration (Cabinet). A department
# never consults itself; restricted sections and pending files are left out. AP Secretariat practice — [To confirm].
CONSULTS = {
    "FIN": {"by": ("GAD01", "ESE01"), "match": FIN_MATTER, "days": (3, 10),
            "ask": "Concurrence of Finance Department may be obtained.", "for": "concurrence",
            "remarks": "referred to Finance Department for concurrence (U.O.)"},
    "GADSER": {"by": ("FIN01", "ESE01"), "match": GAD_SERVICES, "days": (5, 15), "for": "views",
               "ask": "Views of General Administration (Ser.A) Department may be obtained.",
               "remarks": "referred to General Administration (Ser.A) Department for views (U.O.)"},
    "CABINET": {"by": ("FIN01", "ESE01"), "match": CABINET, "days": (10, 30), "for": "approval of the Council of Ministers",
                "ask": "The proposal may be placed before the Council of Ministers through General Administration "
                       "(Cabinet.II) Department.",
                "remarks": "Cabinet memorandum sent to General Administration (Cabinet.II) Department (U.O.)"},
}
GAD_REMARKS = ["have no objection to the proposal", "agree with the proposal, subject to the draft rules being vetted by "
               "the Law Department", "agree with the proposal, subject to the condition that the rules are notified "
               "in the A.P. Gazette before they are given effect"]
UO_SENDERS = ["School Education (Prog.I) Department", "General Administration (Ser.A) Department",
              "School Education (Services.II) Department", "General Administration (Cabinet.II) Department"]
CONDITIONS = ["", "", " subject to the condition that the expenditure shall be met from within the budget provision for "
              "the current financial year", " subject to the condition that no additional financial commitment is "
              "created without the prior concurrence of the Finance Department"]
SECTION_OFFICES = {   # the sender must fit the matter (an ACB letter on APPSC recruitment reads wrong)
    "HR-I": ["Director of Treasuries and Accounts, Vijayawada", "Pay and Accounts Office, Vijayawada"],
    "HR-III": ["Director of Treasuries and Accounts, Vijayawada", "District Treasury, Guntur", "District Treasury, Kakinada"],
    "SER-A": ["A.P. Public Service Commission", "Commissioner of Land Administration", "District Collector, Krishna"],
    "CABINET-II": ["Housing Department", "Planning Department", "Municipal Administration and Urban Development Department"],
    "SC-F": ["Director General, Anti-Corruption Bureau", "Vigilance Commission"],
    "SERVICES-II": ["Commissioner of School Education, Amaravati", "Regional Joint Director of School Education, Kakinada",
                    "District Educational Officer, Krishna", "District Educational Officer, Guntur"],
    "PROGRAM-I": ["Commissioner of School Education, Amaravati", "State Project Director, Samagra Shiksha",
                  "District Educational Officer, Krishna"],
    "EXAMS": ["Director of Government Examinations", "Commissioner of School Education, Amaravati"],
}
PEOPLE = ["Ch. Suresh Babu", "T. Padmavathi", "V. Rama Krishna", "N. Haritha", "K. Nageswara Rao", "P. Swathi",
          "A. Venkata Ramana", "J. Lalitha Kumari", "S. Mohan Rao", "Y. Bhavani", "L. Kiran Kumar", "R. Sailaja"]


def load_meta():
    out = {}
    for p in (ST / "rule-library").rglob("meta.json"):
        m = json.loads(p.read_text())
        out[m["canonical_id"]] = m
    return out


def dmy(iso: str, sep: str = "-") -> str:
    return dt.date.fromisoformat(iso).strftime(f"%d{sep}%m{sep}%Y")


ROMAN = {"I", "II", "III", "IV", "V", "VI", "VII", "VIII"}


def pretty_section(raw: str) -> str:
    """GOIR section field -> the form printed in G.O.s: 'SERVICES-II' -> 'Services.II', 'HR-1-PLG-POLICY' -> 'HR.1-Plg-Policy'."""
    parts = re.split(r"([-,& ]+)", raw.strip())
    out = []
    for p in parts:
        if p.upper() in ROMAN or p.isdigit() or re.fullmatch(r"[A-F]", p):
            if out and out[-1] == "-":
                out[-1] = "."
            out.append(p.upper())
        elif re.fullmatch(r"[A-Z]{2,4}", p) and p not in ("PLG", "TFR", "AND", "SER"):
            out.append(p)                                     # acronyms: HR, PC, TA, SC, GPF
        else:
            out.append(p.title() if p.strip("-,& ") else p)
    return "".join(out)


PRECEDENTS: set[str] = set()      # scenario keys that a type D file points to (set in main)
DISPOSAL = {True: "It is proposed that the request may be allowed in terms of the orders cited above.",
            False: "It is proposed that the request may be rejected, as it is not covered by the orders cited above."}


def usual_allow(sc) -> bool:
    """The section's usual disposal on a subject: fixed by the subject itself (no random draw), so every file on
    the same matter in the same section agrees — except a type D file, which takes the opposite."""
    return zlib.crc32(f"{sc['section']}|{sc['subject']}".encode()) % 2 == 0


PRINTED: dict[str, str] = {}      # the current scenario's `cite_raw` (set in render)


def cite(cid: str, meta: dict) -> str:
    """Citation as a note writes it; parses back to the same canonical ID (checked in main)."""
    m = meta.get(cid)
    if m is None and cid in PRINTED:                         # type E: the reference exactly as a real order printed it
        return PRINTED[cid]
    if m is None:                                            # type E without a printed form (fallback)
        g = re.match(r"AP-([A-Z0-9]+)-(GOMS|GORT|GOP)-(\d+)-(\d{4})", cid)
        return f"G.O.{'Ms' if g and g.group(2) == 'GOMS' else 'Rt' if g and g.group(2) == 'GORT' else 'P'}.No.{g.group(3)}, dated {g.group(4)}" if g else cid
    if cid.startswith("AP-GAZ"):
        return f"A.P. Gazette ({m.get('instrument', '').replace('A.P. Gazette ', '')}) No.{m['number']}, dated {dmy(m['date'], '.')}"
    kind = "Rt" if "-GORT-" in cid else "Ms"
    sec = pretty_section(m.get("section") or "")
    dept = {"FIN01": "Finance", "GAD01": "General Administration", "ESE01": "School Education"}.get(m["department_code"], m["department_code"])
    return f"G.O.{kind}.No.{int(m['number'])}, {dept} ({sec}) Department, dated {dmy(m['date'], '.')}"


def ts(day: dt.date, i: int, rng) -> str:
    h = 10 + (i % 5) * 1 + rng.randint(0, 1)
    return f"{day.strftime('%d/%m/%Y')} {((h - 1) % 12) + 1:02d}:{rng.randint(0, 59):02d} {'AM' if h < 12 else 'PM'}"


def classification(sc, officers) -> str:
    if officers["departments"][sc["dept"]]["sections"][sc["section"]].get("restricted"):
        return "CONFIDENTIAL"
    if re.search(r"transfer|pension|disciplin|age relax|deputation", sc["subject"], re.I):
        return "RESTRICTED"
    return "UNCLASSIFIED"


def matter(subject: str) -> str:
    """A receipt is about a matter, not a G.O.: strip the order-abstract tail ('– Orders – Issued.', 'Amendment')
    and a leading 'Rules -'."""
    s = re.sub(r"^\s*Rules\s*[-–—]\s*", "", subject.strip(), flags=re.I)
    tail = re.compile(r"[\s\-–—]+(?:Amendments?|Notification|Orders?|Issued|Reg|Certain)[\s.\-–—]*$", re.I)
    while tail.search(s):
        s = tail.sub("", s)
    return s.rstrip(" .-–—")


KIND_PREFIX = {"Proceedings": "Rc.No.", "Circular": "Circular Memo No.", "Memo": "Memo No.", "Instruction": "Memo No."}


def real_number(d: dict, dept: str) -> str:
    """A synthetic lower instrument's number in the real printed form ("Circular Memo No.<code>/<n>/<year>"),
    so the ordinary pipeline reads it (owner, 13 Nov 2026). The code starts with SYN: never a real number."""
    m = re.match(r"(?:Rc|Cir|Memo|Lr)\.No\.SYN-(\d+)(?:/([A-Za-z0-9]+))?/(\d{4})$", d["number"])
    if not m:
        raise SystemExit(f"synthetic number not in the expected form: {d['number']!r}")
    wing = (m[2] or "GEN").upper()
    return f"{KIND_PREFIX.get(d['kind'], 'Memo No.')}SYN{dept}-{wing}/{int(m[1])}/{m[3]}"


def note_paras(sc, meta, person, office, rng) -> list[str]:
    """The dealing hand's note. Statements about real orders are citations (or quotes already verified)."""
    c = sc.get("conflict") or {}
    cites = [cite(x, meta) for x in sc["cite"]]
    personal = re.search(r"transfer|pension|teacher|headmaster|candidate|employee|individual|deputation|premium|"
                         r"school assistant|allowance|relief", sc["subject"], re.I)
    paras = [f"It is submitted that a reference has been received from the {office} regarding \"{sc['subject']}\""
             + (f" in respect of {person}" if personal else "") + " (PUC, p.1)."]
    if c.get("type") in ("G", "B"):
        d1 = sc["synthetic_doc"]
        paras.append(f"The {d1['issuer'].replace(' (SYNTHETIC)', '')} in {real_number(d1, sc['dept'])}, Dated: {dmy(d1['date'])} "
                     f"(Correspondence, p.2) has instructed that: \"{d1['text']}\"")
        if sc.get("synthetic_doc_2"):
            d2 = sc["synthetic_doc_2"]
            paras.append(f"Further, {real_number(d2, sc['dept'])}, Dated: {dmy(d2['date'])} (Correspondence, p.3) states: "
                         f"\"{d2['text']}\"")
        paras.append(f"The relevant orders are in {cites[0]} (copy placed in References). The case has been examined "
                     f"in the light of the instructions at p.2.")
    elif c.get("type") == "C":
        paras.append(f"The orders on the subject are in {cites[0]} (copy placed in References).")
        paras.append(f"It is proposed that {sc['proposal']}.")
    elif c.get("type") == "D":
        # the earlier file proposed the section's usual disposal; this note proposes the opposite and does not refer to it
        paras.append(f"The orders on the subject are in {', '.join(cites)} (copies placed in References). "
                     f"No earlier file on the subject is available in the section.")
        paras.append(DISPOSAL[not usual_allow(sc)])
    elif c.get("type") == "E":
        paras.append(f"The proposal relies on {cites[0]} (copy not available in the section).")
    else:  # A / F / clean
        rel = " read with ".join(cites)
        paras.append(f"The orders on the subject are contained in {rel} (copies placed in References).")
        if sc["kind"] == "CLEAN" or sc["key"] in PRECEDENTS:      # a disposal a later file can be compared with
            paras.append(DISPOSAL[usual_allow(sc)])
        if sc["kind"] == "F" and "%" in c.get("reason", ""):
            rate = re.search(r"at ([\d.]+)%", c["reason"])
            if rate:
                paras.append(f"The arrears have been worked out at {rate.group(1)}% as per the said orders; the statement "
                             f"is placed in Documents.")
    paras.append("Approval Requested\n   a) Approval for the proposal at the paras above.\n"
                 + ("   b) Approval for the draft orders placed in the draft section." if rng.random() < 0.6 else
                    "   b) Orders on the action to be taken."))
    paras.append("Submitted for orders.")
    return paras


def dfa(sc, meta, sec_label, dept_name, head_post, rng) -> str:
    """Draft for Approval in the layout of the real G.O.s (unnumbered, unsigned, version 1.0)."""
    reads = "\n".join(f"{i + 1}. {cite(x, meta)}." for i, x in enumerate(sc["cite"]))
    return (BANNER + "DRAFT FOR APPROVAL — version 1.0 (unsigned)\n\n"
            "GOVERNMENT OF ANDHRA PRADESH\nABSTRACT\n\n"
            f"{sc['subject']} – Orders – Issued.\n\n"
            f"{dept_name.upper()} ({sec_label}) DEPARTMENT\n\n"
            f"G.O.Ms.No.      Dated:   -  -{sc['date'][:4]}\n"
            f"Read the following:-\n{reads}\n2. From the reference received (PUC).\n\n*****\n\nORDER:\n\n"
            f"1. In the circumstances stated in the reference read above, Government, after careful examination of the "
            f"matter, hereby order as proposed in the file.\n\n"
            "2. The authorities concerned shall take further action accordingly.\n\n"
            "(BY ORDER AND IN THE NAME OF THE GOVERNOR OF ANDHRA PRADESH)\n\n"
            f"{head_post.upper()}\n\nTo\nThe individual / authority concerned (through proper channel).\n"
            "Copy to the Section concerned.\nSF/SC.\n")


def render(sc, i, meta, officers, outdir: Path, rng, key_to_file) -> tuple[dict, dict | None, dict]:
    PRINTED.clear()
    PRINTED.update(sc.get("cite_raw") or {})
    sc = dict(sc, subject=matter(sc["subject"]))
    dept, sec = sc["dept"], sc["section"]
    head, sec_code = FILE_HEAD[(dept, sec)]
    year = sc["date"][:4]
    file_no = f"{head}/{10 + i}/{year}-{sec_code}"
    comp_no = str({"FIN01": 3_100_000, "GAD01": 3_200_000, "ESE01": 3_300_000}[dept] + i * 7919)
    offs = {o["id"]: o for o in officers["officers"]}
    dinfo = officers["departments"][dept]
    folder = outdir / dept / sec / re.sub(r"[^A-Za-z0-9.-]+", "_", file_no)   # files are overwritten, never deleted
    for sub in ("Correspondence", "Note File1", "Drafts", "GO", "Documents"):
        (folder / sub).mkdir(parents=True, exist_ok=True)

    d0 = dt.date.fromisoformat(sc["date"])
    recv = d0 - dt.timedelta(days=rng.randint(3, 12))
    person = PEOPLE[i % len(PEOPLE)]
    pool = SECTION_OFFICES.get(sec) or OFFICES[dept]
    office = pool[i % len(pool)]
    uo_in = sec == "BUDGET-I"            # budget release requests reach Finance from a department by U.O. note
    if uo_in:
        office = UO_SENDERS[i % len(UO_SENDERS)]
    receipt_no = f"{2000 + i * 13}/{year}-{sec_code}"
    (folder / "Correspondence" / "R-001.md").write_text(
        BANNER + f"Receipt No.: {receipt_no}\nDiary Date: {dmy(recv.isoformat())}\nDelivery Mode: e-Office\n"
        f"Type: {'U.O. Note' if uo_in else 'Letter'}\nLanguage: English\nSender: {office} (synthetic)\n"
        + (f"U.O. Ref. No.: U.O.No.SYN-{100 + i}/{year}, dated {dmy((recv - dt.timedelta(days=2)).isoformat())}\n" if uo_in else
           f"Letter Ref. No.: Lr.No.SYN-{100 + i}/{year}, dated {dmy((recv - dt.timedelta(days=2)).isoformat())}\n")
        + f"Main Category: {dinfo['sections'][sec]['label']}\nSubject: {sc['subject']} – Reg.\n\n"
        + (f"(Synthetic U.O. note) The {office} requests the orders of the Finance Department on the above "
           f"subject.\n" if uo_in else
           f"(Synthetic letter) The {office} requests orders on the above subject in respect of {person}.\n"))
    for n, k in ((2, "synthetic_doc"), (3, "synthetic_doc_2")):
        if sc.get(k):
            d = sc[k]
            (folder / "Correspondence" / f"R-00{n}.md").write_text(
                BANNER + f"SYNTHETIC — not a real order\n\n{d['issuer']}\n{d['kind'].upper()}\n"
                f"{real_number(d, sc['dept'])}, Dated: {dmy(d['date'])}\n\n"
                f"Sub: {sc['subject']}\n\n{d['text']}\n")

    paras = note_paras(sc, meta, person, office, rng)
    chain = [offs[x] for x in sc["movement"]]
    status = "decided"
    if 16 in sc["touchpoints"]:
        status = "closed"
    if 17 in sc["touchpoints"]:
        status = "reopened"
    # "open": a demo holdback file, always still moving (no random draw, so earlier files keep theirs)
    pending = bool(sc.get("open")) or ((6 in sc["touchpoints"]) and rng.random() < 0.5 and status == "decided")
    if pending:
        status = "open"
    # Note flow as in the mentor-shared samples (13 Nov 2026; layout only, nothing copied): paragraph numbers run on
    # through the whole note file; the dealing hand writes "1)", "2)" …; a senior officer forwards with an empty note
    # (signature only) or a short remark "N. …"; the submitting officer writes "Sir, submitted for approval of Para N
    # with regard to …"; a "Pl discuss." comes back as a resubmission; the deciding officer writes "Para N - agreed." or
    # "Approved."; a file still pending ends with the holder's Yellow note.
    short = sc["subject"] if len(sc["subject"]) <= 90 else sc["subject"][:90].rsplit(" ", 1)[0].rstrip(" ,–-") + " …"
    if pending:   # the file is still moving up: it stops with an officer below the head, who holds a Yellow note
        chain = chain[: rng.randint(2, max(2, len(chain) - 1))]
    ask = len(paras) - 1                                      # number of the "Approval Requested" para
    seq: list[tuple[dict, list[str], str]] = [(chain[0], paras, ")")]
    mids = chain[1:-1]
    discuss = rng.random() < 0.3 and len(mids) >= 1
    for j, o in enumerate(mids):
        if j == 0:
            seq.append((o, [f"Sir, submitted for approval of Para {{ask}} with regard to {short}."], ")"))
        elif discuss and j == len(mids) - 1:
            seq += [(o, ["Pl discuss."], "."),
                    (chain[0], ["As discussed, the position is placed below and the relevant G.Os are included in the TOC "
                                "for kind reference. Resubmitted for approval of Para {ask}."], ")"),
                    (o, [], ".")]
        else:
            seq.append((o, [], "."))                          # forwarded without remarks (signature only)
    if pending:
        # the holder's Yellow note restates what goes up, so the pre-send check (touchpoint 11) has the reference
        basis = cite(sc["cite"][0], meta) if sc["cite"] else "the orders cited above"
        seq.append((chain[-1], [f"Para {{ask}} may kindly be seen. The proposal rests on {basis}. Submitted for approval."],
                    ")" if chain[-1]["rank"] <= 2 else "."))
    restricted = dinfo["sections"][sec].get("restricted")
    consults = [] if (pending or restricted or len(chain) < 2) else \
        [c for c, r in CONSULTS.items() if dept in r["by"] and r["match"].search(sc["subject"])]
    if consults:   # head agrees and orders the consultations; each goes out by U.O. note and the dealing hand
                   # records the reply; then the file goes up again and the head approves
        asks = [CONSULTS[c]["ask"] for c in consults]
        if len(asks) > 1 and consults[-1] == "CABINET":
            asks[-1] = "Thereafter, the proposal may be placed before the Council of Ministers through General " \
                       "Administration (Cabinet.II) Department."
        seq.append((chain[-1], ["Para {ask} - agreed. " + " ".join(asks)], "."))
        for c in consults:
            seq.append((chain[0], ["@" + c], ")"))
        if mids:
            seq.append((mids[0], [], "."))
        seq.append((chain[-1], ["Approved. Issue orders."], "."))
    elif not pending:
        seq.append((chain[-1], [rng.choice(["Para {ask} - agreed.", "Approved.", "Approved. Issue orders."])], "."))
    corr_p = 2 + sum(1 for k in ("synthetic_doc", "synthetic_doc_2") if sc.get(k))   # next Correspondence page
    consulted: list[dict] = []
    order_para = 0
    movements, n = [], 1
    clock = dt.datetime.combine(d0, dt.time(10, rng.randint(0, 50)))
    # a clean file must be finished before the next change to its cited orders (builder's close_by): it moves
    # quickly (minutes, consultations back in a day). Same random draws, so no other file changes.
    quick = bool(sc.get("close_by"))
    for k, (o, lines, style) in enumerate(seq):
        if k:                                   # time only moves forward: 20 min to 5 h per movement, office hours
            step = rng.randint(20, 300)
            clock += dt.timedelta(minutes=step // 5 if quick else step)
            if clock.hour >= 18:
                clock = dt.datetime.combine(clock.date() + dt.timedelta(days=1), dt.time(10, rng.randint(0, 50)))
            while clock.weekday() == 6:
                clock += dt.timedelta(days=1)
        if len(lines) == 1 and lines[0].startswith("@"):   # a consultation: days out, then the reply is recorded
            c = lines[0][1:]
            rule = CONSULTS[c]
            adm = dinfo["name"].replace(" Department", "")
            sent = clock.date()
            days = rng.randint(*rule["days"])
            clock += dt.timedelta(days=1 if quick else days)
            while clock.weekday() == 6:
                clock += dt.timedelta(days=1)
            ret = clock.date()
            p_ = f"R-{corr_p:03d}.md"
            if c == "FIN":
                fmu = FMU[dept][0]
                to_dept, uo = f"Finance ({fmu})", f"FIN01-FMU0MISC/{40 + i}/{ret.year}-{fmu}"
                cond = rng.choice(CONDITIONS)
                body_txt = f"Finance Department have examined the proposal at Para {ask} of the note file and concur with it{cond}."
                sig, dest = "DEPUTY SECRETARY TO GOVERNMENT (FMU)", f"FIN01/{fmu}"
                rec = (f"Finance ({fmu}) Department have concurred with the proposal{cond}")
            elif c == "GADSER":
                to_dept, uo = "General Administration (Ser.A)", f"GAD01-SERA0SER/{500 + i}/{ret.year}-SER.A"
                cond = rng.choice(GAD_REMARKS)
                body_txt = (f"General Administration (Ser.A) Department have examined the proposal at Para {ask} of the "
                            f"note file and {cond}.")
                sig, dest = "DEPUTY SECRETARY TO GOVERNMENT (SERVICES)", "GAD01/SER-A"
                rec = f"General Administration (Ser.A) Department {cond}"
            else:
                to_dept, uo = "General Administration (Cabinet.II)", f"GAD01-CABN0BR/{500 + i}/{ret.year}-CABINET.II"
                meet = ret - dt.timedelta(days=rng.randint(1, 3))
                # after the file went out, not after the reply, never on a Sunday
                days_ok = [sent + dt.timedelta(days=j) for j in range(1, (ret - sent).days + 1)
                           if (sent + dt.timedelta(days=j)).weekday() != 6]
                meet = max((d for d in days_ok if d <= meet), default=days_ok[0] if days_ok else ret)
                item = rng.randint(5, 60)
                cond = ""
                body_txt = (f"The Council of Ministers, at its meeting held on {dmy(meet.isoformat(), '.')}, considered "
                            f"the memorandum of the {adm} Department (Item No.{item}) and approved the proposal.")
                sig, dest = "DEPUTY SECRETARY TO GOVERNMENT (CABINET)", "GAD01/CABINET-II"
                rec = (f"The Council of Ministers approved the proposal at its meeting held on "
                       f"{dmy(meet.isoformat(), '.')} (Item No.{item}), as communicated by General Administration "
                       f"(Cabinet.II) Department")
            (folder / "Correspondence" / p_).write_text(
                BANNER + "SYNTHETIC — not a real order\n\nGOVERNMENT OF ANDHRA PRADESH\n"
                f"{to_dept.upper()} DEPARTMENT\n\nU.O. NOTE\n\nU.O.No.{uo}, dated {dmy(ret.isoformat(), '.')}\n\n"
                f"Sub: {sc['subject']} – Reg.\nRef: {adm} Department, File No.{file_no}, dated "
                f"{dmy(sent.isoformat(), '.')}.\n* * *\n\n{body_txt}\n\n{sig}\n\nTo\nThe {adm} Department.\n")
            last = c == consults[-1]
            lines = [f"As ordered at Para {order_para}, the file was referred to the {to_dept} Department on "
                     f"{dmy(sent.isoformat(), '.')} for {rule['for']}. {rec} vide U.O.No.{uo}, dated "
                     f"{dmy(ret.isoformat(), '.')} (Correspondence, p.{corr_p})."]
            if last:
                lines.append("Submitted for issue of orders.")
            consulted.append({"with": c, "uo_no": uo, "department": to_dept, "sent": sent.isoformat(),
                              "returned": ret.isoformat(), "conditional": bool(cond) and "no objection" not in cond,
                              "correspondence": p_})
            movements.append({"note": None, "from": o["id"], "name": o["name"], "designation": o["post"],
                              "at": sent.strftime("%d/%m/%Y"), "sent_to": dest, "external": True,
                              "returned": ret.strftime("%d/%m/%Y"), "remarks": rule["remarks"]})
            corr_p += 1
        when = clock.strftime("%d/%m/%Y %I:%M %p")
        body = []
        if lines and "agreed. " in lines[0] and consults:
            order_para = n
        for line in lines:
            body.append(f"{n}{style} {line.replace('{ask}', str(ask))}")
            n += 1
        refs = "\n".join(f"{r + 1}. {cite(x, meta)}." for r, x in enumerate(sc["cite"]))
        head_txt = (f"Sub: {sc['subject']} – Reg.\nRef:\n{refs}\n{len(sc['cite']) + 1}. Receipt No. {receipt_no}, "
                    f"dated {dmy(recv.isoformat(), '.')}.\n* * *\n" if k == 0 else "")
        colour = "yellow" if (pending and k == len(seq) - 1) else "green"
        name = o["name"].upper() + (", I.A.S" if o["rank"] >= 5 else "")       # mock service tag for JS / head
        (folder / "Note File1" / f"note-{k + 1:03d}.md").write_text(
            BANNER + f"<!-- {colour} -->\nNote # {k + 1}\n{head_txt}" + "\n".join(body) +
            f"\n\n{when}\n{name}\n{o['post'].upper()}\n")
        nxt = seq[k + 1][0] if k + 1 < len(seq) else None
        remark = ("returned for discussion" if lines == ["Pl discuss."] else "approved" if nxt is None and not pending
                  else "pending" if nxt is None else "for approval" if nxt["rank"] > o["rank"] else "returned")
        movements.append({"note": k + 1, "from": o["id"], "name": o["name"], "designation": o["post"], "at": when,
                          "sent_to": nxt["id"] if nxt else None, "remarks": remark})
    if 14 in sc["touchpoints"] or rng.random() < 0.3:
        (folder / "Drafts" / "DFA-001.md").write_text(
            dfa(sc, meta, sec_code, dinfo["name"].replace(" Department", ""), chain[-1]["post"], rng))
    write_json(folder / "GO" / "link.json", sc["cite"])
    write_json(folder / "movements.json", movements)
    prec = key_to_file.get(sc.get("precedent"))
    links = [{"file_no": prec, "type": "Previous Reference"}] if prec else []
    write_json(folder / "links.json", links)
    info = {"file_no": file_no, "computer_no": comp_no, "subject": f"{sc['subject']} – Reg.", "department_code": dept,
            "section": sec, "section_label": dinfo["sections"][sec]["label"],
            "classification": classification(sc, officers), "status": status, "opened": recv.isoformat(),
            "scenario": sc["key"], "touchpoints": sc["touchpoints"], "origin": "synthetic",
            "banner": "Synthetic — not a real government file", "cites": sc["cite"]}
    if consulted:
        info["consultations"] = consulted
    if uo_in:
        info["received_by"] = "U.O. Note"
    write_json(folder / "file.json", info)
    gt = None
    if sc.get("conflict"):
        c = dict(sc["conflict"])
        if c["type"] == "D":
            c["cited"] = key_to_file.get(c["cited"], c["cited"])
        gt = {"file_no": file_no, "scenario": sc["key"], "note": 1, **c}
    return {"file_no": file_no, "folder": str(folder.relative_to(V2)), "scenario": sc["key"],
            "conflict": (sc.get("conflict") or {}).get("type")}, gt, info


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="render N files per department into efiles_v2/_sample/")
    ap.add_argument("--overwrite", action="store_true",
                    help="write over an existing render (same seed, same paths); files this run did not write are "
                         "listed as stale and the run fails, so nothing old is left unnoticed")
    a = ap.parse_args()
    started = time.time() - 2
    meta = load_meta()
    officers = yaml.safe_load((V2 / "directory" / "officers.yaml").read_text())
    plan = yaml.safe_load((V2 / "scenarios" / "scenarios.yaml").read_text())["departments"]
    rng = random.Random(20261113)
    out = V2 / ("_sample" if a.sample else "efiles")
    if not a.sample and not a.overwrite and out.exists() and any(out.rglob("file.json")):
        sys.exit("efiles_v2/efiles already has files; move them aside first, or use --overwrite")

    PRECEDENTS.update(s["precedent"] for items in plan.values() for s in items if s.get("precedent"))
    key_to_file, index, gts, infos, i = {}, [], [], [], 0
    for dept, items in plan.items():
        chosen = items
        if a.sample:   # one conflict of a hand-picked type, one A/F, one clean
            pick = [next((s for s in items if s.get("hand_reviewed")), None),
                    next((s for s in items if s["kind"] in ("A", "F")), None),
                    next((s for s in items if s["kind"] == "CLEAN"), None)]
            chosen = [s for s in pick if s][: a.sample]
        for sc in chosen:
            for c in sc["cite"]:
                if sc.get("conflict", {}) and (sc["conflict"] or {}).get("type") == "E":
                    continue
                if c not in meta:
                    sys.exit(f"{sc['key']}: cites {c}, not in the corpus")
            row, gt, info = render(sc, i, meta, officers, out, rng, key_to_file)
            key_to_file[sc["key"]] = row["file_no"]
            index.append(row); infos.append(info)
            if gt:
                gts.append(gt)
            i += 1

    # directory + access matrix (mock rules, plan §11.4): Section -> own sections; Section Hierarchy -> own sections;
    # Department -> whole department; Global -> all. Clearance must reach the file's classification.
    rank = {"UNCLASSIFIED": 0, "RESTRICTED": 1, "CONFIDENTIAL": 2, "SECRET": 3}
    write_json(out.parent / ("_sample_directory" if a.sample else "directory") / "officers.json",
               [dict(o, origin="synthetic") for o in officers["officers"]])
    mpath = out.parent / ("_sample_access_matrix.csv" if a.sample else "access_matrix.csv")
    with open(mpath, "w", newline="") as fh:
        ids = [o["id"] for o in officers["officers"]]
        w = csv.writer(fh)
        w.writerow(["file_no", "classification", "dept", "section", *ids])
        for f in infos:
            row = []
            for o in officers["officers"]:
                scope_ok = (o["scope"] == "Global" or (o["dept"] == f["department_code"] and
                            (o["scope"] == "Department" or f["section"] in o["sections"] or "ALL" in o["sections"])))
                row.append("ALLOW" if scope_ok and rank[o["clearance"]] >= rank[f["classification"]] else "DENY")
            w.writerow([f["file_no"], f["classification"], f["department_code"], f["section"], *row])
    gtdir = out.parent / ("_sample_ground_truth" if a.sample else "ground_truth")
    write_json(gtdir / "efiles_v2_conflicts.json", gts)               # EVAL ONLY — never read by backend/app
    write_json(out.parent / ("_sample_manifests" if a.sample else "manifests") / "efiles_v2_index.json", index)
    print(f"{len(index)} files rendered into {out.relative_to(V2.parents[3])}; {len(gts)} planted conflicts")
    for r in index:
        print(f"  {r['scenario']:<22} {r['conflict'] or 'clean':<6} {r['file_no']}")
    if a.overwrite and not a.sample:
        stale = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file() and p.stat().st_mtime < started)
        if stale:
            print(f"STALE: {len(stale)} files under efiles/ were not written by this run:")
            for p in stale[:40]:
                print("  ", p)
            sys.exit(1)


if __name__ == "__main__":
    main()
