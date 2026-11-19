"""Outsider leakage suite on synthetic set v2 (plan §9.4, §12.4; CLAUDE.md §4, §9.4).

Every one of the 21 sandbox officers asks about every one of the e-Files through every assistant
and sandbox path. Each response is searched for any file the INDEPENDENT access matrix
(`efiles_v2/access_matrix.csv`, written by the data tools, not by the application) denies to
that officer: by file number and by the identifiers of the file's papers. Pass bar: zero.

    cd backend
    env -u VIRTUAL_ENV uv run python ../evaluation/leakage_v2.py \
        --public-dir ~/Documents/c2-24-corpus
        [--users V01,V08] [--jobs 4] [--label x] [--no-write]

No model is called (the answer path is exercised up to the evidence package: what would be sent
to the model is what the response lists). Exit code 1 on any disclosure.
Writes evaluation/reports/<date>-leakage-v2[-label].{md,json}.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import csv
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from evaluation.harness.limits import NO_RATE_LIMITS, require_measured  # noqa: E402
from evaluation.harness.quoting_model import QuotingModel  # noqa: E402

V2 = ROOT / "data" / "synthetic" / "mock_v1" / "efiles_v2"
REPORTS = ROOT / "evaluation" / "reports"


def sweep(
    users: list[str], public_dir: Path, answerer: str = "none"
) -> tuple[dict[str, dict[str, int]], list[dict[str, str]], int, dict[str, int]]:
    """One process: its own sandbox app, the given officers, every file, every path."""
    seed = json.loads((V2 / "eoffice" / "seed_v2.json").read_text("utf-8"))
    with (V2 / "access_matrix.csv").open(encoding="utf-8", newline="") as fh:
        matrix = {r["file_no"]: r for r in csv.DictReader(fh)}
    files = seed["files"]
    cno_of = {f["file_no"]: f["computer_no"] for f in files}
    settings = get_settings().model_copy(
        update={
            "sandbox": True,
            "sandbox_seed": "v2",
            "sandbox_public_corpus_dir": public_dir,
            "llm_provider": "none",
            "state_store": "memory",
            **NO_RATE_LIMITS,  # evaluation/harness/limits.py
        }
    )
    paths: dict[str, dict[str, int]] = collections.defaultdict(
        lambda: {"checks": 0, "disclosures": 0}
    )
    found: list[dict[str, str]] = []
    statuses: list[int] = []  # a 429 / 5xx check disclosed nothing because it measured nothing
    controls = 0  # allowed files seen by number: proves the search for file numbers can fire
    t0 = time.time()
    app = create_app(settings)
    with TestClient(app) as client:
        run = app.state.assist_runtime()
        if answerer == "quote":  # answers get cached, so the cache paths are really exercised
            run.llm = QuotingModel()
        for uid in users:
            hdr = {"X-Sandbox-User": uid}
            # what this officer must never see: file numbers and paper identifiers of denied files
            denied = {fn: cno_of[fn] for fn, row in matrix.items() if row[uid] != "ALLOW"}
            needles = [(fn, fn) for fn in denied] + [(fn, f'"{c}-') for fn, c in denied.items()]

            def record(
                path: str, case: str, resp: Any, uid: str = uid, needles: Any = needles
            ) -> None:
                statuses.append(resp.status_code)
                text = resp.text
                bad = sorted({fn for fn, needle in needles if needle in text})
                paths[path]["checks"] += 1
                paths[path]["disclosures"] += len(bad)
                found.extend({"path": path, "user": uid, "case": case, "file": fn} for fn in bad)

            def post(url: str, body: dict[str, Any], hdr: dict[str, str] = hdr) -> Any:
                return client.post(url, json=body, headers=hdr)

            record("sandbox: file list", "list", client.get("/sandbox/files", headers=hdr))
            record("sandbox: receipt list", "list", client.get("/sandbox/receipts", headers=hdr))
            record("assist: notices", "notices", client.get("/assist/notices", headers=hdr))
            # entity resolution (ADR-0058): every officer asks about every officer, by name and
            # by officer ID; records naming them are told only within the asker's scope
            for prof in seed["profiles"]:
                record(
                    "assist: ask about an officer (name)",
                    prof["user_id"],
                    post("/assist/ask", {"question": f"Which notes did {prof['name']} sign?"}),
                )
                record(
                    "assist: ask about an officer (ID)",
                    prof["user_id"],
                    post("/assist/ask", {"question": f"Notes signed by {prof['user_id']}"}),
                )
            for f in files:
                cno, fn, subj = f["computer_no"], f["file_no"], f["subject"][:300]
                allowed = matrix[fn][uid] == "ALLOW"
                r = client.get(f"/sandbox/files/{cno}", headers=hdr)
                if not allowed and r.status_code == 200:
                    paths["sandbox: open file"]["disclosures"] += 1
                    found.append(
                        {"path": "sandbox: open file", "user": uid, "case": cno, "file": fn}
                    )
                controls += allowed and r.status_code == 200 and fn in r.text
                record("sandbox: open file", cno, r)
                record("assist: search by subject", cno, post("/assist/search", {"query": subj}))
                record(
                    "assist: ask (evidence package)", cno, post("/assist/ask", {"question": subj})
                )
                first = post("/assist/chat", {"message": subj})
                record("assist: chat", cno, first)
                # the same question in other words (ADR-0053): served from the cache only within
                # this officer's scope; another officer's answer must never come back this way
                record(
                    "assist: chat reworded repeat",
                    cno,
                    post("/assist/chat", {"message": f"Please, {subj} now"}),
                )
                # graph reasoning (ADR-0056): an order's history and its links to other
                # departments, told from the order and link records without the model
                record(
                    "assist: ask order history",
                    cno,
                    post("/assist/ask", {"question": f"How have the orders on {subj} changed?"}),
                )
                record(
                    "assist: ask cross-department links",
                    cno,
                    post(
                        "/assist/ask",
                        {"question": f"Which other departments refer to the orders on {subj}?"},
                    ),
                )
                record(
                    "assist: ask file history",
                    cno,
                    post(
                        "/assist/ask",
                        {"question": f"How have the orders cited in File No.{fn} changed?"},
                    ),
                )
                talk = first.json() if first.status_code == 200 else {}
                record(
                    "assist: chat follow-up + draft",
                    cno,
                    post(
                        "/assist/chat",
                        {
                            "message": "Draft the noting using that precedent.",
                            "session_id": talk.get("session_id"),
                            "computer_no": cno,
                        },
                    ),
                )
                record(
                    "assist: reference by file number", cno, post("/assist/reference", {"text": fn})
                )
                for name in (
                    "presend",
                    "file-so-far",
                    "link-suggestions",
                    "first-cut",
                    "dfa",
                    "brief",
                ):
                    record(f"assist: {name}", cno, post(f"/assist/{name}", {"computer_no": cno}))
                # drafting from the file (ADR-0060): file facts, carried references, related
                # files, order history and people beside a note on this file
                record(
                    "assist: draft prepare (note)",
                    cno,
                    post(
                        "/assist/draft/prepare", {"computer_no": cno, "format_id": "note_proposal"}
                    ),
                )
                record(
                    "assist: note reference",
                    cno,
                    post("/assist/note-reference", {"computer_no": cno, "text": subj}),
                )
                for suffix in ("NOTES", "C1"):
                    record(
                        "assist: document by identifier",
                        f"{cno}-{suffix}",
                        client.get(f"/assist/documents/{cno}-{suffix}", headers=hdr),
                    )
            print(
                f"  {uid}: {sum(p['checks'] for p in paths.values())} checks, "
                f"{len(found)} disclosures, {time.time() - t0:.0f}s",
                flush=True,
            )

    require_measured(statuses, "leakage_v2")  # in each worker, before anything is scored
    cache = run.stores.cache.stats()
    usage = {
        "answer_cache_hits": int(cache.get("hits", 0)),
        "reworded_hits": int(run.stores.reworded.hits),
    }
    return {k: dict(v) for k, v in paths.items()}, found, controls, usage


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--public-dir", type=Path, required=True)
    ap.add_argument("--users", default="", help="comma-separated officer IDs (default: all)")
    ap.add_argument("--jobs", type=int, default=1, help="processes (officers are split evenly)")
    ap.add_argument("--label", default="")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument(
        "--answerer",
        choices=["none", "quote"],
        default="none",
        help="quote: a deterministic stand-in model (evaluation/harness/quoting_model.py) so "
        "answers are cached and the cache paths, exact and reworded, are exercised (ADR-0053)",
    )
    a = ap.parse_args(argv)

    seed = json.loads((V2 / "eoffice" / "seed_v2.json").read_text("utf-8"))
    files = seed["files"]
    users = [p["user_id"] for p in seed["profiles"] if p["login"]]
    if a.users:
        users = [u for u in users if u in set(a.users.split(","))]
    public_dir = a.public_dir.expanduser()
    jobs = max(1, min(a.jobs, len(users)))
    parts = [users[i::jobs] for i in range(jobs)]
    if jobs == 1:
        results = [sweep(users, public_dir, a.answerer)]
    else:
        with concurrent.futures.ProcessPoolExecutor(jobs) as pool:
            results = list(pool.map(sweep, parts, [public_dir] * jobs, [a.answerer] * jobs))
    paths: dict[str, dict[str, int]] = {}
    found: list[dict[str, str]] = []
    controls = 0
    usage: dict[str, int] = {}
    for ps, fs, c, u in results:
        for name, hits in u.items():
            usage[name] = usage.get(name, 0) + hits
        for k, v in ps.items():
            cur = paths.setdefault(k, {"checks": 0, "disclosures": 0})
            cur["checks"] += v["checks"]
            cur["disclosures"] += v["disclosures"]
        found += fs
        controls += c
    total = sum(p["disclosures"] for p in paths.values())
    summary = {
        "answerer": a.answerer,
        **usage,
        "officers": len(users),
        "files": len(files),
        "checks": sum(p["checks"] for p in paths.values()),
        "disclosures": total,
        "controls_seen": controls,  # allowed files found by number (the search can fire)
        "pass": total == 0 and controls > 0,
    }
    report = {"summary": summary, "paths": dict(paths), "disclosures": found[:500]}
    day = dt.date.today().isoformat()
    stem = f"{day}-leakage-v2" + (f"-{a.label}" if a.label else "")
    if not a.no_write:
        REPORTS.mkdir(parents=True, exist_ok=True)
        (REPORTS / f"{stem}.json").write_text(json.dumps(report, indent=1), "utf-8")
        md = [
            f"# Outsider leakage on set v2 — {day}",
            "",
            "SYNTHETIC data. Every officer × every e-File × every path; each response searched "
            "for files the independent access matrix denies. Pass bar: 0.",
            "",
            f"- Officers: **{summary['officers']}**, files: **{summary['files']}**, checks: "
            f"**{summary['checks']}**, disclosures: **{total}** → "
            f"**{'PASS' if summary['pass'] else 'FAIL'}**",
            f"- Answers: `{a.answerer}`; answer-cache hits {usage.get('answer_cache_hits', 0)}, "
            f"reworded-repeat hits {usage.get('reworded_hits', 0)}",
            f"- Control: {controls} allowed files were found by number in the same responses.",
            "",
            "| Path | Checks | Disclosures |",
            "|---|---:|---:|",
        ]
        md += [f"| {k} | {v['checks']} | {v['disclosures']} |" for k, v in sorted(paths.items())]
        (REPORTS / f"{stem}.md").write_text("\n".join(md) + "\n", "utf-8")
        print(f"report: evaluation/reports/{stem}.md")
    print(f"leakage v2: {total} disclosures / {summary['checks']} checks; controls {controls}")
    print(f"answerer {a.answerer}; cache hits {usage}")
    for d in found[:8]:
        print("  !", d)
    return 0 if summary["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
