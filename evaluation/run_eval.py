"""Run the evaluation harness on the reference stack and write a report (plan §13).

    cd backend && uv run python ../evaluation/run_eval.py            # writes evaluation/reports/
    cd backend && uv run python ../evaluation/run_eval.py --no-write # print the summary only
    ... run_eval.py --label after-fix --compare ../evaluation/reports/2026-11-04-baseline.json

Exit code 1 if the leakage pass bar (zero disclosures, CLAUDE.md §9.4) is not met.
EVALUATION ONLY — synthetic mock corpus v1; uncalibrated test thresholds; keyword stand-in for
Vertex AI Search; hand transcriptions stand in for Document AI on scanned pages.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.retrieval.ladder import LadderConfig  # noqa: E402
from evaluation.harness.stack import build_stack  # noqa: E402
from evaluation.harness.suites import Harness  # noqa: E402

SLOTS = ROOT / "evaluation" / "slots_v1.json"
REPORTS = ROOT / "evaluation" / "reports"


def run_all(slots_path: Path = SLOTS) -> dict[str, Any]:
    slots = json.loads(slots_path.read_text("utf-8"))
    lc = slots["ladder_config"]
    cfg = LadderConfig(
        l2_top_k=lc["l2_top_k"], l2_min_score=lc["l2_min_score"], l3_max_hops=lc["l3_max_hops"]
    )
    stack = build_stack(cfg)
    h = Harness(stack, slots)
    retrieval = h.retrieval()
    conflict = h.conflict()
    leakage = h.leakage()
    touch = h.touchpoints(retrieval, conflict)
    return {
        "meta": {
            "run_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
            "corpus": "mock_v1 (SYNTHETIC)",
            "slots": slots["version"],
            "ladder_config": lc,
            "stack": {
                "indexed": len(stack.cid_of),
                "held_files": stack.held,
                "indexed_from_transcription": list(stack.transcribed),
                "not_indexed": list(stack.not_indexed),
                "l2": "keyword stand-in (BM25-style), not Vertex AI Search",
                "rules": h.rules.status.value,
            },
        },
        "retrieval": retrieval,
        "conflict": conflict,
        "leakage": leakage,
        "touchpoints": touch,
    }


def _f(x: object) -> str:
    return f"{x:.3f}" if isinstance(x, float) else ("—" if x is None else str(x))


def to_markdown(r: dict[str, Any]) -> str:
    meta, ret, con, lk, tp = (
        r["meta"],
        r["retrieval"],
        r["conflict"],
        r["leakage"],
        r["touchpoints"],
    )
    s = ret["summary"]
    lines = [
        f"# Evaluation report — {meta['run_at']}",
        "",
        "**SYNTHETIC mock corpus v1. Baseline on the reference stack, not on GCP.** "
        "L2 is a keyword stand-in; thresholds are uncalibrated test values; scanned pages are "
        "indexed from hand transcriptions standing in for Document AI + reviewer confirmation; "
        f"type-C rules are `{meta['stack']['rules']}` (testing only).",
        "",
        f"- Indexed: {meta['stack']['indexed']} documents · from transcription: "
        f"{', '.join(meta['stack']['indexed_from_transcription']) or 'none'} · not indexed: "
        f"{', '.join(meta['stack']['not_indexed']) or 'none'}",
        f"- Slots: {meta['slots']} · ladder config: {meta['ladder_config']}",
        "",
        "## Leakage (pass bar: zero)",
        "",
        f"**{lk['summary']['disclosures']} disclosures in {lk['summary']['checks']} checks — "
        f"{'PASS' if lk['summary']['pass'] else 'FAIL'}**",
        "",
        "| Path | Checks | Disclosures |",
        "|---|---:|---:|",
        *[f"| {k} | {v['checks']} | {v['disclosures']} |" for k, v in lk["paths"].items()],
        "",
        "## Retrieval (golden questions)",
        "",
        "| Metric | Value |",
        "|---|---:|",
        *[
            f"| {k} | {_f(s[k])} |"
            for k in (
                "answerable_questions",
                "recall@5",
                "recall@10",
                "precision@5",
                "mrr",
                "ndcg@10",
                "full_recall_questions",
                "ladder_level_accuracy",
                "ladder_level_questions",
                "no_answer_questions",
                "no_answer_with_forbidden_docs",
                "no_answer_retrieved_nothing",
            )
        ],
        f"| answer_status_accuracy | {s['answer_status_accuracy']} |",
        "",
        "| Q | User | Intent | Level (exp → got) | Recall@10 | Missing | Note |",
        "|---|---|---|---|---:|---|---|",
    ]
    for q in ret["questions"]:
        miss = sorted(set(q["expected_docs"]) - set(q["ranked"]))
        lines.append(
            f"| {q['id']} | {q['user']} | {q['intent']} | {q['expected_level']} → {q['level']} | "
            f"{_f(q.get('recall@10'))} | {', '.join(miss) or '—'} | {q['note'] or ''} |"
        )
    d = con["summary"]["deterministic_A_C_E_F"]
    lines += [
        "",
        "## Conflicts (pre-send, touchpoint 11)",
        "",
        f"Deterministic types A/C/E/F: TP {d['tp']} · FP {d['fp']} · FN {d['fn']} · precision "
        f"{_f(d['precision'])} · recall {_f(d['recall'])} · F1 {_f(d['f1'])}. Clean controls: "
        f"{con['summary']['clean_control_false_flags']} false flags. "
        f"{con['summary']['note']}.",
        "",
        "| Type | TP | FP | FN | Precision | Recall | Status |",
        "|---|---:|---:|---:|---:|---:|---|",
        *[
            f"| {t} | {v['tp']} | {v['fp']} | {v['fn']} | {_f(v['precision'])} | "
            f"{_f(v['recall'])} | {'implemented' if v['implemented'] else v['status']} |"
            for t, v in con["per_type"].items()
        ],
        "",
        "| Draft | User | Outcome | Expected | Flagged | Missed | False | Status unconfirmed |",
        "|---|---|---|---|---|---|---|---|",
        *[
            f"| {x['draft']}{' (control)' if x['control'] else ''} | {x['user']} | {x['outcome']} "
            f"| {','.join(x['expected_types']) or '—'} | {','.join(x['flagged_types']) or '—'} "
            f"| {','.join(x['missed']) or '—'} | {','.join(x['false_flags']) or '—'} "
            f"| {','.join(x['status_unconfirmed']) or '—'} |"
            for x in con["runs"]
        ],
        "",
        "## Touchpoint scenarios",
        "",
        f"{tp['summary']['run']} of {tp['summary']['scenarios']} run here, "
        f"{tp['summary']['passed']} passed; the rest need the sandbox screen flow (P8).",
        "",
        "| Scenario | Touchpoint | Result |",
        "|---|---|---|",
        *[
            f"| {x['id']} | {x['touchpoint']} | "
            f"{('PASS' if x['pass'] else 'FAIL') if x['run'] else 'not run — ' + x['why']} |"
            for x in tp["scenarios"]
        ],
        "",
    ]
    return "\n".join(lines)


HEADLINE = (
    ("leakage disclosures", ("leakage", "summary", "disclosures")),
    ("leakage checks", ("leakage", "summary", "checks")),
    ("recall@5", ("retrieval", "summary", "recall@5")),
    ("recall@10", ("retrieval", "summary", "recall@10")),
    ("precision@5", ("retrieval", "summary", "precision@5")),
    ("mrr", ("retrieval", "summary", "mrr")),
    ("ndcg@10", ("retrieval", "summary", "ndcg@10")),
    ("ladder-level accuracy", ("retrieval", "summary", "ladder_level_accuracy")),
    ("conflicts A/C/E/F precision", ("conflict", "summary", "deterministic_A_C_E_F", "precision")),
    ("conflicts A/C/E/F recall", ("conflict", "summary", "deterministic_A_C_E_F", "recall")),
    ("clean-control false flags", ("conflict", "summary", "clean_control_false_flags")),
    ("touchpoints passed", ("touchpoints", "summary", "passed")),
)


def _get(r: dict[str, Any], path: tuple[str, ...]) -> Any:
    for k in path:
        r = r.get(k, {}) if isinstance(r, dict) else {}
    return None if r == {} else r


def compare(new: dict[str, Any], old: dict[str, Any], old_name: str) -> str:
    rows = [f"## Compared with `{old_name}`", "", "| Metric | Before | Now |", "|---|---:|---:|"]
    rows += [f"| {n} | {_f(_get(old, p))} | {_f(_get(new, p))} |" for n, p in HEADLINE]
    return "\n".join(rows) + "\n"


def free_name(folder: Path, name: str) -> str:
    """Never overwrite a report (a baseline is evidence): `<name>`, else `<name>-2`, `-3`, …"""
    taken = {p.stem for p in folder.glob("*")}
    if name not in taken:
        return name
    n = 2
    while f"{name}-{n}" in taken:
        n += 1
    return f"{name}-{n}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--no-write", action="store_true", help="print the summary, write no files")
    ap.add_argument("--label", default="baseline", help="report name: <date>-<label>.{md,json}")
    ap.add_argument("--compare", type=Path, help="an earlier report .json to compare against")
    args = ap.parse_args(argv)
    report = run_all()
    md = to_markdown(report)
    if args.compare:
        old = json.loads(args.compare.read_text("utf-8"))
        md = md.replace(
            "\n## Leakage", "\n" + compare(report, old, args.compare.name) + "\n## Leakage", 1
        )
        print(compare(report, old, args.compare.name))
    if not args.no_write:
        REPORTS.mkdir(parents=True, exist_ok=True)
        name = free_name(REPORTS, f"{dt.date.today().isoformat()}-{args.label}")
        (REPORTS / f"{name}.json").write_text(
            json.dumps(report, indent=1, default=str, ensure_ascii=False), "utf-8"
        )
        (REPORTS / f"{name}.md").write_text(md, "utf-8")
        print(f"wrote {REPORTS / (name + '.md')}")
    lk = report["leakage"]["summary"]
    r = report["retrieval"]["summary"]
    c = report["conflict"]["summary"]["deterministic_A_C_E_F"]
    print(
        f"leakage: {lk['disclosures']} disclosures / {lk['checks']} checks"
        f" · recall@10 {_f(r['recall@10'])} · MRR {_f(r['mrr'])}"
        f" · ladder-level acc {_f(r['ladder_level_accuracy'])}"
        f" · conflicts A/C/E/F P {_f(c['precision'])} R {_f(c['recall'])}"
    )
    return 0 if lk["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
