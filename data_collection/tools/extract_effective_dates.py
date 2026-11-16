"""Data collection plan item 2: record each order's STATED effective date in its meta.json (ADR-0006, plan §6.1).

The rule is the backend's (`backend/app/ingestion/metadata.py`, `_stated_effective_from`), kept identical here
because these tools run without the backend:
  - the subject's "with effect from <date>" first; else the operative part's own commencement ("These orders shall
    come into force with effect from …", "w.e.f.", "take effect from …");
  - several different dates in the same place (e.g. one per category of employee) or "with immediate effect"
    → no stated date (nothing is guessed).

Fields written (only where effective_from_source is still "assumed_issue_date"; extracted or verified values are
never overwritten):
  stated_effective_from        the date the order states (may be before its issue: retrospective)
  stated_effective_evidence    {method, text}: the words it was read from
  effective_from               the stated date, effective_from_source "stated_in_order"
Orders that state none keep effective_from = issue date ("assumed_issue_date").

  python tools/extract_effective_dates.py            # report only
  python tools/extract_effective_dates.py --write
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import ROOT  # noqa: E402

ST = ROOT / "staging"
MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"), 1)}
WEF = re.compile(
    r"(?:with\s+effect\s+from|w\.\s*e\.\s*f\.?|(?:shall\s+)?come\s+into\s+force\s+(?:with\s+effect\s+)?"
    r"(?:from|on)|take\s+effect\s+(?:from|on))\s*:?\s*(?:the\s+)?"
    r"(?P<d>\d{1,2}\s*[-./]\s*\d{1,2}\s*[-./]\s*(?:19|20)\d{2}"
    r"|\d{1,2}\s*(?:st|nd|rd|th)?\s+(?:day\s+of\s+)?[A-Za-z]{3,9},?\s+(?:19|20)\d{2})",
    re.I,
)
OPERATIVE = re.compile(r"^\s*(?:O\s*R\s*D\s*E\s*R|ORDER)\s*[:.\-]|^\s*NOTIFICATION\s*$", re.M)


def to_date(raw: str) -> dt.date | None:
    raw = re.sub(r"\s+", " ", raw).strip()
    try:
        if m := re.fullmatch(r"(\d{1,2})\s*[-./]\s*(\d{1,2})\s*[-./]\s*(\d{4})", raw):
            return dt.date(int(m[3]), int(m[2]), int(m[1]))
        if m := re.fullmatch(r"(\d{1,2})\s*(?:st|nd|rd|th)?\s+(?:day of\s+)?([A-Za-z]{3,9}),?\s+(\d{4})", raw):
            mon = MONTHS.get(m[2][:3].lower())
            return dt.date(int(m[3]), mon, int(m[1])) if mon else None
    except ValueError:
        return None
    return None


def stated(subject: str, text: str) -> tuple[dt.date | None, str]:
    op = OPERATIVE.search(text)
    body = text[op.end():] if op else (text.split("ORDER", 1)[1] if "ORDER" in text else text)
    for where, part in (("subject", subject or ""), ("operative text", body)):
        flat = re.sub(r"\s+", " ", part)
        hits = [(d, m.group(0)) for m in WEF.finditer(flat) if (d := to_date(m["d"]))]
        dates = {d for d, _ in hits}
        if len(dates) == 1:
            return hits[0][0], f"{where}: {hits[0][1]}"
        if dates:
            return None, f"{where}: {len(dates)} different dates — none taken"
    return None, ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()
    stats, retro, later = collections.Counter(), 0, []
    for mp in sorted((ST / "rule-library").rglob("meta.json")):
        m = json.loads(mp.read_text())
        if m.get("effective_from_source") not in (None, "assumed_issue_date"):
            stats["kept (extracted or verified earlier)"] += 1
            continue
        f = mp.parent / ((m.get("files") or {}).get("ocr") or "ocr.txt")
        text = f.read_text(errors="ignore") if f.exists() else ""
        d, why = stated(m.get("subject") or "", text)
        if d is None:
            stats["no single stated date" if why else "none stated"] += 1
            continue
        issue = dt.date.fromisoformat(str(m["date"]))
        stats["stated"] += 1
        if d < issue:
            retro += 1
        elif d > issue:
            later.append((m["canonical_id"], str(issue), d.isoformat()))
        if a.write:
            m.update(stated_effective_from=d.isoformat(),
                     stated_effective_evidence={"method": m.get("ocr_source") or "text layer", "text": why[:200]},
                     effective_from=d.isoformat(), effective_from_source="stated_in_order")
            mp.write_text(json.dumps(m, ensure_ascii=False, indent=2))
    for k, v in stats.most_common():
        print(f"{v:>5}  {k}")
    print(f"       of the stated: {retro} retrospective (before issue), {len(later)} later than issue:")
    for cid, i, d in later[:40]:
        print(f"         {cid:<34} issued {i}  in force from {d}")
    print("written" if a.write else "report only — add --write to record")


if __name__ == "__main__":
    main()
