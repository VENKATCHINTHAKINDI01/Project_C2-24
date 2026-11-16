"""Noting agent on the sandbox files (ADR-0030): for each touchpoint 6 / 11 / 14 scenario file, the
first-cut points plus the model's note, checked line by line. SYNTHETIC data (mock_v1).

    cd backend
    env -u VIRTUAL_ENV uv run python ../evaluation/noting_live.py            # saved answers only
    C2_GCP_PROJECT_ID=<project> C2_GCP_REGION=asia-south1 \\
      env -u VIRTUAL_ENV uv run python ../evaluation/noting_live.py --live   # Gemini (billed)

--live sends one request per file (at most 4) and saves each answer, so a re-run costs nothing.
Writes evaluation/reports/<date>-noting[-label].md. What is scored: lines kept / removed by the
check, sections written, and any record outside the officer's access named (must be 0). Whether a
note reads well is for the officer to judge; the report prints each note for that.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.identifiers.canonical import InvalidCanonicalIdError, lookup_keys  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.unit.mock_access import MATRIX  # noqa: E402

CORPUS = ROOT / "data" / "synthetic" / "mock_v1"
REPORTS = ROOT / "evaluation" / "reports"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    settings = get_settings().model_copy(
        update={"sandbox": True, "llm_provider": "vertex" if a.live else "recorded"}
    )
    scen = json.loads((CORPUS / "ground_truth" / "touchpoint_scenarios.json").read_text("utf-8"))
    cases = list(
        dict.fromkeys(
            (s["user"], s["context"]["computer_no"])
            for s in scen["scenarios"]
            if s["touchpoint"] in (6, 11, 14) and "computer_no" in s["context"]
        )
    )
    with (CORPUS / "documents_index.csv").open(encoding="utf-8", newline="") as fh:
        idx = {r["canonical_id"]: r["id"] for r in csv.DictReader(fh)}

    def doc_id(cid: str) -> str | None:
        try:
            return next((idx[k] for k in lookup_keys(cid.split("#", 1)[0]) if k in idx), None)
        except InvalidCanonicalIdError:
            return None

    rows, md = [], []
    with TestClient(create_app(settings)) as client:
        for user, cno in cases:
            r = client.post(
                "/assist/first-cut", json={"computer_no": cno}, headers={"X-Sandbox-User": user}
            )
            body = r.json() if r.status_code == 200 else {}
            note = body.get("note") or {}
            text = body.get("note_text", f"http {r.status_code}")
            named = {d for m in re.findall(r"AP-[A-Z0-9-]+", text) if (d := doc_id(m))}
            bad = sorted(d for d in named if not MATRIX.get((d, user), False))
            kept = sum(len(s["lines"]) for s in note.get("sections", []))
            rows.append(
                {
                    "user": user,
                    "computer_no": cno,
                    "sections": [s["heading"] for s in note.get("sections", [])],
                    "lines_kept": kept,
                    "lines_removed": note.get("removed", 0),
                    "forbidden_named": bad,
                    "engine": note.get("engine"),
                }
            )
            md += [f"## {cno} as {user}", "", "```", text, "```", ""]
    summary = {
        "files": len(rows),
        "mode": "live" if a.live else "saved answers only",
        "notes_written": sum(bool(r["lines_kept"]) for r in rows),
        "lines_kept": sum(r["lines_kept"] for r in rows),
        "lines_removed": sum(r["lines_removed"] for r in rows),
        "forbidden_records_named": sum(len(r["forbidden_named"]) for r in rows),
    }
    day = dt.date.today().isoformat()
    stem = f"{day}-noting" + (f"-{a.label}" if a.label else "")
    REPORTS.mkdir(parents=True, exist_ok=True)
    head = [f"# Noting agent on the sandbox files — {day}", "", "SYNTHETIC data (mock_v1).", ""]
    head += [f"- {k.replace('_', ' ')}: **{v}**" for k, v in summary.items()]
    head += [
        "",
        "| File | Officer | Sections | Kept | Removed | Forbidden |",
        "|---|---|---|---:|---:|---:|",
    ]
    head += [
        f"| {r['computer_no']} | {r['user']} | {', '.join(r['sections']) or '—'} | "
        f"{r['lines_kept']} | {r['lines_removed']} | {len(r['forbidden_named'])} |"
        for r in rows
    ]
    (REPORTS / f"{stem}.md").write_text("\n".join(head + [""] + md) + "\n", "utf-8")
    (REPORTS / f"{stem}.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    for k, v in summary.items():
        print(f"{k}: {v}")
    print(f"report: evaluation/reports/{stem}.md")
    return 1 if summary["forbidden_records_named"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
