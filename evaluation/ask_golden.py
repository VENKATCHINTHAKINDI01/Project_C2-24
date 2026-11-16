"""First cited answer (M4) on the golden questions of mock_v1: each question is asked as its own
officer through POST /assist/ask, and the answer is scored against the answer key's documents.

    cd backend
    env -u VIRTUAL_ENV uv run python ../evaluation/ask_golden.py            # saved answers only
    C2_GCP_PROJECT_ID=<project> C2_GCP_REGION=asia-south1 \\
      env -u VIRTUAL_ENV uv run python ../evaluation/ask_golden.py --live   # asks Gemini (billed)

--live sends one request per question that has evidence (at most 24) and saves each answer under
data/synthetic/mock_v1/llm/<model>/, so a second run costs nothing. SYNTHETIC data only.
Writes evaluation/reports/<date>-ask-golden[-label].{md,json}.

What is scored (nothing here judges the wording of an answer):
- cited: a statement survived the citation check (cites a passage, quote found in it);
- on key: at least one cited record is one of the question's expected records;
- forbidden: a record the officer must not see is named anywhere in the response (must be 0);
- expected no-answer questions must give no statement.

Before asking, scans held for OCR review are confirmed UNCHANGED by a simulated reviewer through
the production endpoints (GET /assist/review/ocr, POST …/confirm), exactly as the evaluation
harness does (`evaluation/harness/stack.py`): the recorded Document AI text, no corrections. A scan
without a recorded reading stays held. `--no-confirm-ocr` asks with the scans still held.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.identifiers.canonical import InvalidCanonicalIdError, lookup_keys  # noqa: E402
from app.main import create_app  # noqa: E402

CORPUS = ROOT / "data" / "synthetic" / "mock_v1"
REPORTS = ROOT / "evaluation" / "reports"
ID_RX = re.compile(r"AP-[A-Z]{2,6}\d{2}-[A-Z]+-[A-Z0-9-]+")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true", help="ask Gemini for answers not yet saved")
    ap.add_argument("--label", default="")
    ap.add_argument("--no-confirm-ocr", action="store_true", help="leave held scans unconfirmed")
    a = ap.parse_args()
    settings = get_settings().model_copy(
        update={
            "sandbox": True,
            "llm_provider": "vertex" if a.live else "recorded",
            "state_store": "memory",
        }
    )
    with (CORPUS / "documents_index.csv").open(encoding="utf-8", newline="") as fh:
        idx = {r["canonical_id"]: r["id"] for r in csv.DictReader(fh)}
    golden = json.loads((CORPUS / "ground_truth" / "golden_questions.json").read_text("utf-8"))

    def doc_id(cid: str) -> str | None:
        try:
            return next((idx[k] for k in lookup_keys(cid.split("#", 1)[0]) if k in idx), None)
        except InvalidCanonicalIdError:
            return None

    rows: list[dict[str, Any]] = []
    seed = json.loads((CORPUS / "eoffice" / "seed.json").read_text("utf-8"))
    with TestClient(create_app(settings)) as client:
        confirmed = 0
        if not a.no_confirm_ocr:  # SIMULATED reviewer, recorded text unchanged (see docstring)
            for p in seed["profiles"]:
                if not p.get("login"):
                    continue
                hdr = {"X-Sandbox-User": p["user_id"]}
                for item in client.get("/assist/review/ocr", headers=hdr).json().get("items", []):
                    detail = client.get(f"/assist/review/ocr/{item['item_id']}", headers=hdr).json()
                    if not detail.get("has_draft"):
                        continue
                    r = client.post(
                        f"/assist/review/ocr/{item['item_id']}/confirm",
                        json={
                            "corrected_text": detail["draft_text"],
                            "reason": "EVAL simulated reviewer: recorded OCR confirmed unchanged",
                        },
                        headers=hdr,
                    )
                    confirmed += r.status_code == 200
        for g in golden:
            r = client.post(
                "/assist/ask",
                json={"question": g["question"]},
                headers={"X-Sandbox-User": g["user"]},
            )
            out = r.json() if r.status_code == 200 else {"status": f"http {r.status_code}"}
            cited = sorted(
                {
                    d
                    for s in out.get("statements", [])
                    for c in s["citations"]
                    if (d := doc_id(c["canonical_id"]))
                }
            )
            named = {d for m in ID_RX.finditer(json.dumps(out)) if (d := doc_id(m.group(0)))}
            package = sorted({d for c in out.get("documents", []) if (d := doc_id(c))})
            rows.append(
                {
                    "id": g["id"],
                    "user": g["user"],
                    "expected_status": g.get("answer_status"),
                    "status": out.get("status"),
                    "engine": out.get("engine"),
                    "statements": [s["text"] for s in out.get("statements", [])],
                    "quotes": [s["quote"] for s in out.get("statements", [])],
                    "review_needed": len(out.get("review_needed", [])),
                    "removed": out.get("removed", 0),
                    "cited": cited,
                    "expected": g.get("expected_docs", []),
                    "on_key": bool(set(cited) & set(g.get("expected_docs", []))),
                    "package": package,
                    "expected_in_package": bool(set(package) & set(g.get("expected_docs", []))),
                    "forbidden_named": sorted(named & set(g.get("forbidden_docs", []))),
                    "message": out.get("message"),
                }
            )
    want = [r for r in rows if r["expected_status"] == "answered"]
    none = [r for r in rows if r["expected_status"] != "answered"]
    summary = {
        "questions": len(rows),
        "mode": "live" if a.live else "saved answers only",
        "scans_confirmed_by_simulated_reviewer": confirmed,
        "model": settings.gemini_model,
        "expected_answered": len(want),
        "expected_record_in_evidence_package": sum(r["expected_in_package"] for r in want),
        "answered_with_checked_citation": sum(r["status"] == "answered" for r in want),
        "answered_on_key": sum(r["status"] == "answered" and r["on_key"] for r in want),
        "not_run": sum(r["status"] == "not_run" for r in rows),
        "expected_no_answer": len(none),
        "no_answer_kept": sum(not r["statements"] for r in none),
        "statements_removed_by_citation_check": sum(r["removed"] for r in rows),
        "forbidden_records_named": sum(len(r["forbidden_named"]) for r in rows),
    }
    day = dt.date.today().isoformat()
    stem = f"{day}-ask-golden" + (f"-{a.label}" if a.label else "")
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{stem}.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False), "utf-8"
    )
    md = [f"# Cited answers on the golden questions — {day}", "", "SYNTHETIC data (mock_v1).", ""]
    md += [f"- {k.replace('_', ' ')}: **{v}**" for k, v in summary.items()]
    md += [
        "",
        "| Q | Officer | Expected | Got | Cited | On key | Removed |",
        "|---|---|---|---|---|---|---:|",
    ]
    md += [
        f"| {r['id']} | {r['user']} | {r['expected_status']} | {r['status']} | "
        f"{', '.join(r['cited']) or '—'} | {'yes' if r['on_key'] else '—'} | {r['removed']} |"
        for r in rows
    ]
    (REPORTS / f"{stem}.md").write_text("\n".join(md) + "\n", "utf-8")
    for k, v in summary.items():
        print(f"{k}: {v}")
    print(f"report: evaluation/reports/{stem}.md")
    return 1 if summary["forbidden_records_named"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
