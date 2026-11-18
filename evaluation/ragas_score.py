"""RAGAS scores of the assistant's answers, judged by Gemini on Vertex AI (plan §13; ADR-0050).

Reads the samples written by `rag_samples.py` (question, the evidence package's passages, the
statements shown, the answer key) and scores each answered question with RAGAS 0.4.4:

- faithfulness: share of the answer's claims that the passages support;
- response groundedness: how well the answer as a whole is grounded in the passages;
- answer relevancy: how well the answer addresses the question (judge + embeddings);
- context precision (with reference): are the passages that matter ranked first;
- context recall: share of the answer key's points that the passages cover.

Faithfulness and groundedness are scored on the model-written statements only: the "order
records" statements come from the temporal engine, not from the passages, and are checked there.

Runs in its own throwaway environment, so RAGAS and its dependencies never enter the backend
(`jsonref` is needed by instructor to read Gemini's structured answers; without it every metric
fails with ConfigurationError):

    uv run --no-project --with ragas==0.4.4 --with google-genai --with jsonref \\
      python evaluation/ragas_score.py evaluation/reports/<date>-rag-samples.jsonl          # plan
    C2_GCP_PROJECT_ID=<project> C2_GCP_REGION=asia-south1 \\
    uv run --no-project --with ragas==0.4.4 --with google-genai --with jsonref \\
      python evaluation/ragas_score.py evaluation/reports/<date>-rag-samples.jsonl --live   # billed

Without --live nothing is called: it prints what would be scored. --live calls Gemini (billed;
the owner runs it) with Application Default Credentials, in the project's region. Every judge
and embedding call is cached in evaluation/.ragas_cache (git-ignored), so a second run of the
same samples costs nothing. SYNTHETIC data only. Writes evaluation/reports/<date>-ragas[-label].
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "evaluation" / "reports"
CACHE = ROOT / "evaluation" / ".ragas_cache"
RAGAS_VERSION = "0.4.4"
METRICS = (
    "faithfulness",
    "response_groundedness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
)

Scorer = Callable[[dict[str, Any]], Awaitable[float]]


def inputs(sample: Mapping[str, Any]) -> dict[str, Any] | None:
    """RAGAS inputs for one sample, or None when there is nothing to score (no statement shown
    or no passage sent)."""
    statements = list(sample.get("statements", ()))
    contexts = [c["text"] for c in sample.get("contexts", ()) if c.get("text")]
    if not statements or not contexts:
        return None
    model = [s["text"] for s in statements if s.get("source") == "evidence"]
    return {
        "user_input": sample["question"],
        "response": "\n".join(s["text"] for s in statements),
        "model_response": "\n".join(model),
        "retrieved_contexts": contexts,
        "reference": sample.get("answer_key") or "",
    }


def scorers(model: str, embed_model: str, project: str, location: str) -> dict[str, Scorer]:
    """The judge: Gemini on Vertex AI in the project's region, cached on disk."""
    from google import genai
    from ragas.cache import DiskCacheBackend
    from ragas.embeddings import GoogleEmbeddings
    from ragas.llms import llm_factory
    from ragas.metrics import collections as rc

    client = genai.Client(vertexai=True, project=project, location=location)
    cache = DiskCacheBackend(cache_dir=str(CACHE))
    llm = llm_factory(model, provider="google", client=client, cache=cache)
    emb = GoogleEmbeddings(client=client, model=embed_model, cache=cache)
    faith = rc.Faithfulness(llm=llm)
    grounded = rc.ResponseGroundedness(llm=llm)
    relevant = rc.AnswerRelevancy(llm=llm, embeddings=emb)
    precision = rc.ContextPrecisionWithReference(llm=llm)
    recall = rc.ContextRecall(llm=llm)

    async def f(x: dict[str, Any]) -> float:
        r = await faith.ascore(
            user_input=x["user_input"],
            response=x["model_response"],
            retrieved_contexts=x["retrieved_contexts"],
        )
        return float(r.value)

    async def g(x: dict[str, Any]) -> float:
        r = await grounded.ascore(
            response=x["model_response"], retrieved_contexts=x["retrieved_contexts"]
        )
        return float(r.value)

    async def a(x: dict[str, Any]) -> float:
        r = await relevant.ascore(user_input=x["user_input"], response=x["response"])
        return float(r.value)

    async def p(x: dict[str, Any]) -> float:
        r = await precision.ascore(
            user_input=x["user_input"],
            reference=x["reference"],
            retrieved_contexts=x["retrieved_contexts"],
        )
        return float(r.value)

    async def c(x: dict[str, Any]) -> float:
        r = await recall.ascore(
            user_input=x["user_input"],
            retrieved_contexts=x["retrieved_contexts"],
            reference=x["reference"],
        )
        return float(r.value)

    return {
        "faithfulness": f,
        "response_groundedness": g,
        "answer_relevancy": a,
        "context_precision": p,
        "context_recall": c,
    }


def applicable(name: str, x: Mapping[str, Any]) -> bool:
    if name in ("faithfulness", "response_groundedness"):
        return bool(x["model_response"])
    if name in ("context_precision", "context_recall"):
        return bool(x["reference"])
    return True


async def score_all(
    samples: Sequence[Mapping[str, Any]], fns: Mapping[str, Scorer], concurrency: int = 4
) -> list[dict[str, Any]]:
    """One row per sample. A metric that fails on a sample is recorded as None with the error
    type (never a made-up score), and the run goes on."""
    gate = asyncio.Semaphore(concurrency)

    async def one(s: Mapping[str, Any]) -> dict[str, Any]:
        row: dict[str, Any] = {"id": s["id"], "errors": {}}
        x = inputs(s)
        for name in METRICS:
            row[name] = None
            if x is None or name not in fns or not applicable(name, x):
                continue
            async with gate:
                try:
                    row[name] = round(await fns[name](x), 4)
                except Exception as exc:  # noqa: BLE001 — recorded per metric, run continues
                    row["errors"][name] = type(exc).__name__
        return row

    return list(await asyncio.gather(*(one(s) for s in samples)))


def means(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for m in METRICS:
        got = [r[m] for r in rows if r.get(m) is not None]
        out[m] = round(sum(got) / len(got), 4) if got else None
    return out


def report(
    rows: Sequence[Mapping[str, Any]],
    meta: Mapping[str, Any],
    baseline: Mapping[str, Any] | None,
    stem: str,
) -> Path:
    mean = means(rows)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{stem}.json").write_text(
        json.dumps({"meta": meta, "means": mean, "rows": rows}, indent=1), "utf-8"
    )

    def f(v: Any) -> str:
        return "—" if v is None else f"{v:.3f}"

    md = [f"# RAGAS scores — {meta['date']}", ""]
    md += [f"- {k.replace('_', ' ')}: {v}" for k, v in meta.items() if k != "date"]
    md += ["", "| Metric | Mean" + (" | Baseline |" if baseline else " |")]
    md += ["|---|---:" + ("|---:|" if baseline else "|")]
    for m in METRICS:
        line = f"| {m.replace('_', ' ')} | {f(mean[m])}"
        md.append(line + (f" | {f(baseline.get(m))} |" if baseline else " |"))
    md += ["", "| Q | " + " | ".join(METRICS) + " | Errors |"]
    md += ["|---|" + "---:|" * len(METRICS) + "---|"]
    md += [
        f"| {r['id']} | "
        + " | ".join(f(r[m]) for m in METRICS)
        + f" | {', '.join(f'{k}: {v}' for k, v in r['errors'].items()) or '—'} |"
        for r in rows
    ]
    path = REPORTS / f"{stem}.md"
    path.write_text("\n".join(md) + "\n", "utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("samples", type=Path)
    ap.add_argument("--live", action="store_true", help="call the Gemini judge (billed)")
    ap.add_argument("--label", default="")
    ap.add_argument("--limit", type=int, default=0, help="score the first N samples only")
    ap.add_argument("--compare", type=Path, help="an earlier ragas report (.json)")
    ap.add_argument("--judge-model", default=os.environ.get("C2_GEMINI_MODEL", "gemini-3.5-flash"))
    ap.add_argument("--embedding-model", default="gemini-embedding-001")
    a = ap.parse_args()
    samples = [json.loads(line) for line in a.samples.read_text("utf-8").splitlines() if line]
    if a.limit:
        samples = samples[: a.limit]
    scorable = [s for s in samples if inputs(s) is not None]
    print(f"{len(samples)} samples, {len(scorable)} with statements and passages to score")
    if not a.live:
        print("plan only: nothing called. Add --live to score with the Gemini judge (billed).")
        return 0
    project = os.environ.get("C2_GCP_PROJECT_ID")
    location = os.environ.get("C2_GEMINI_LOCATION") or os.environ.get("C2_GCP_REGION")
    if not (project and location):
        print("set C2_GCP_PROJECT_ID and C2_GCP_REGION (the judge runs in the project's region)")
        return 2
    fns = scorers(a.judge_model, a.embedding_model, project, location)
    rows = asyncio.run(score_all(samples, fns))
    day = dt.date.today().isoformat()
    meta = {
        "date": day,
        "samples": a.samples.name,
        "scored": len(scorable),
        "ragas": RAGAS_VERSION,
        "judge": f"{a.judge_model} on Vertex AI ({location})",
        "embeddings": a.embedding_model,
        "note": "SYNTHETIC data; the judge is the same model family as the answering model",
    }
    baseline = json.loads(a.compare.read_text("utf-8"))["means"] if a.compare else None
    path = report(rows, meta, baseline, f"{day}-ragas" + (f"-{a.label}" if a.label else ""))
    for k, v in means(rows).items():
        print(f"{k}: {v}")
    errors = sum(len(r["errors"]) for r in rows)
    print(f"metric errors: {errors} · report: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
