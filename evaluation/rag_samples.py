"""RAG answer quality on the golden questions of mock_v1 (plan §13.2 "RAG"; ADR-0050).

Asks each golden question as its own officer through POST /assist/ask (exactly as ask_golden.py
does), and keeps, for each answer, what the assistant actually used: the evidence package it sent
to Gemini (passage text and record) and the statements it showed with their citations. Then:

1. scores what needs no judge model (evaluation/harness/rag_metrics.py): citation correctness and
   completeness against the evidence package, context precision / recall by record;
2. writes the samples (`<date>-rag-samples[-label].jsonl`) that `ragas_score.py` scores with RAGAS
   (faithfulness, groundedness, answer relevance, context precision / recall, judged by Gemini).

    cd backend
    env -u VIRTUAL_ENV uv run python ../evaluation/rag_samples.py           # saved answers only
    C2_GCP_PROJECT_ID=<project> C2_GCP_REGION=asia-south1 \\
      env -u VIRTUAL_ENV uv run python ../evaluation/rag_samples.py --live  # asks Gemini (billed)

The package is read by wrapping the /assist/ask route's `ask` in this process only: the app is not
changed and never returns passage text to the officer beyond what it already shows. SYNTHETIC data
only. Writes evaluation/reports/<date>-rag-quality[-label].{md,json} and the samples file.
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

import app.agents.routes as routes  # noqa: E402
from app.agents.answer import Answer, AskTrace  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.identifiers.canonical import InvalidCanonicalIdError, lookup_keys  # noqa: E402
from app.main import create_app  # noqa: E402
from evaluation.ask_golden import confirm_held_scans  # noqa: E402
from evaluation.harness import rag_metrics as rm  # noqa: E402
from evaluation.harness.limits import NO_RATE_LIMITS, require_measured  # noqa: E402

CORPUS = ROOT / "data" / "synthetic" / "mock_v1"
REPORTS = ROOT / "evaluation" / "reports"
SUMMARY_KEYS = (
    "citation_correctness",
    "citation_completeness",
    "context_precision_by_record",
    "context_recall_by_record",
)


class Spy:
    """Keeps the last answer of the route's `ask` and the package it built, by passing it a
    trace (the route passes none). This process only; the answer itself is unchanged."""

    def __init__(self) -> None:
        self.real: Any = getattr(routes, "ask")  # noqa: B009 — not re-exported
        self.answer: Answer | None = None
        self.trace: AskTrace | None = None

    def __call__(self, *args: Any, **kw: Any) -> Answer:
        self.trace = kw.setdefault("trace", AskTrace())
        ans: Answer = self.real(*args, **kw)
        self.answer = ans
        return ans

    def reset(self) -> None:
        self.answer = self.trace = None


def sample(g: dict[str, Any], spy: Spy, record: Any) -> dict[str, Any]:
    """One golden question → what the assistant used and said, with record names."""
    ans, pkg = spy.answer, (spy.trace.package if spy.trace else None)
    items = pkg.items if pkg else ()
    # each passage as the model saw it: its record, status and level come with it (the prompt's
    # evidence attributes), so a statement such as "…, which is superseded" is judged against what
    # the model was actually told, not against the bare span (ADR-0050 addendum 3)
    contexts = [
        {
            "evidence_id": i.evidence_id,
            "canonical_id": i.canonical_id,
            "record": record(i.canonical_id),
            "status": i.status,
            "text": f"[{i.canonical_id} · status: {i.status} · level {i.hierarchy_level}]\n"
            + i.span_text,
        }
        for i in items
    ]
    statements = [
        {
            "text": s.text,
            "quote": s.quote,
            "source": s.source,
            "citations": [
                {
                    "evidence_id": c.evidence_id,
                    "canonical_id": c.canonical_id,
                    "record": record(c.canonical_id),
                }
                for c in s.citations
            ],
        }
        for s in (ans.statements if ans else ())
    ]
    return {
        "id": g["id"],
        "user": g["user"],
        "question": g["question"],
        "answer_key": reference_of(g),
        "expected_status": g.get("answer_status"),
        "expected": g.get("expected_docs", []),
        "status": str(ans.status) if ans else "not captured",
        "removed": ans.removed if ans else 0,
        "contexts": contexts,
        "statements": statements,
    }


CONFLICTS = json.loads((CORPUS / "ground_truth" / "conflicts.json").read_text("utf-8"))
_FILE = re.compile(r"\b[A-Z]{2,6}\d{2}-[A-Z0-9]+/\d+/\d{4}-[A-Z0-9.]+")


def reference_of(g: dict[str, Any]) -> str:
    """The reference RAGAS compares contexts with. A "check this file" question's key is only a
    list of flag letters ("Flags G, C, D."), which no passage can support or contradict: its
    reference is the planted conflicts' own descriptions from the answer key (conflicts.json) for
    the record that is the file's note. The key itself is unchanged."""
    key = str(g.get("answer_key", ""))
    m = _FILE.search(g["question"])
    if not (key.startswith("Flags") and m):
        return key
    texts = CORPUS / "ground_truth" / "text"
    rec = next(
        (
            c["in"]
            for c in CONFLICTS
            if (texts / f"{c['in']}.txt").exists()
            and m.group(0) in (texts / f"{c['in']}.txt").read_text("utf-8")[:400]
        ),
        None,
    )
    found = [f"{c['name']}: {c['detail']}" for c in CONFLICTS if c["in"] == rec]
    return " ".join(found) or key


def score(s: dict[str, Any]) -> dict[str, Any]:
    spans = {c["evidence_id"]: c["text"] for c in s["contexts"]}
    model = [st for st in s["statements"] if st["source"] == "evidence"]
    cited = {c["record"] for st in s["statements"] for c in st["citations"]}
    out: dict[str, Any] = {
        "id": s["id"],
        "status": s["status"],
        "model_statements": len(model),
        "removed": s["removed"],
        "citation_correctness": rm.share(
            sum(rm.citation_correct(st, spans) for st in model), len(model)
        ),
    }
    out.update(rm.record_scores({c["record"] for c in s["contexts"]}, cited, s["expected"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true", help="ask Gemini for answers not yet saved")
    ap.add_argument("--label", default="")
    a = ap.parse_args()
    settings = get_settings().model_copy(
        update={
            "sandbox": True,
            "llm_provider": "vertex" if a.live else "recorded",
            "state_store": "memory",
            **NO_RATE_LIMITS,  # evaluation/harness/limits.py
        }
    )
    with (CORPUS / "documents_index.csv").open(encoding="utf-8", newline="") as fh:
        idx = {r["canonical_id"]: r["id"] for r in csv.DictReader(fh)}

    def record(cid: str) -> str:
        """Answer-key name (D01…) of a record, or its canonical ID when it has none."""
        base = cid.split("#", 1)[0]
        try:
            return next((idx[k] for k in lookup_keys(base) if k in idx), base)
        except InvalidCanonicalIdError:
            return base

    golden = json.loads((CORPUS / "ground_truth" / "golden_questions.json").read_text("utf-8"))
    seed = json.loads((CORPUS / "eoffice" / "seed.json").read_text("utf-8"))
    spy = Spy()
    setattr(routes, "ask", spy)  # noqa: B010 — this process only (see docstring)
    samples: list[dict[str, Any]] = []
    statuses: list[int] = []
    try:
        with TestClient(create_app(settings)) as client:
            confirm_held_scans(client, seed)
            for g in golden:
                spy.reset()
                r = client.post(
                    "/assist/ask",
                    json={"question": g["question"]},
                    headers={"X-Sandbox-User": g["user"]},
                )
                statuses.append(r.status_code)
                s = sample(g, spy, record)
                if r.status_code != 200:
                    s["status"] = f"http {r.status_code}"
                samples.append(s)
    finally:
        setattr(routes, "ask", spy.real)  # noqa: B010

    require_measured(statuses, "rag_samples")
    answered = [s for s in samples if s["expected_status"] == "answered"]
    rows = [score(s) for s in answered]
    summary: dict[str, Any] = {
        "questions": len(samples),
        "mode": "live" if a.live else "saved answers only",
        "model": settings.gemini_model,
        "expected_answered": len(answered),
        "answered": sum(r["status"] == "answered" for r in rows),
        "model_statements": sum(r["model_statements"] for r in rows),
        "statements_removed_by_citation_check": sum(r["removed"] for r in rows),
    }
    for k in SUMMARY_KEYS:
        summary[k] = rm.mean([r[k] for r in rows])

    day = dt.date.today().isoformat()
    suffix = f"-{a.label}" if a.label else ""
    REPORTS.mkdir(parents=True, exist_ok=True)
    with (REPORTS / f"{day}-rag-samples{suffix}.jsonl").open("w", encoding="utf-8") as fh:
        for s in answered:
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
    stem = f"{day}-rag-quality{suffix}"
    (REPORTS / f"{stem}.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False), "utf-8"
    )

    def f(v: Any) -> str:
        return "—" if v is None else f"{v:.3f}" if isinstance(v, float) else str(v)

    md = [
        f"# RAG answer quality, no judge model — {day}",
        "",
        "SYNTHETIC data (mock_v1). Definitions: `evaluation/harness/rag_metrics.py`. Judge-model "
        "scores (RAGAS): `ragas_score.py` on the samples file.",
        "",
    ]
    md += [f"- {k.replace('_', ' ')}: **{f(v)}**" for k, v in summary.items()]
    md += [
        "",
        "| Q | Status | Statements | Cit. correct | Cit. complete | Ctx precision | Ctx recall |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    md += [
        f"| {r['id']} | {r['status']} | {r['model_statements']} | "
        f"{f(r['citation_correctness'])} | {f(r['citation_completeness'])} | "
        f"{f(r['context_precision_by_record'])} | {f(r['context_recall_by_record'])} |"
        for r in rows
    ]
    (REPORTS / f"{stem}.md").write_text("\n".join(md) + "\n", "utf-8")
    for k, v in summary.items():
        print(f"{k}: {f(v)}")
    print(f"report: evaluation/reports/{stem}.md · samples: {day}-rag-samples{suffix}.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
