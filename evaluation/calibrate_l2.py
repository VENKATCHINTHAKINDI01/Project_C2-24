"""Calibrate the L2 early-exit threshold on a REAL retriever (ADR-0061 and its 24 Nov addendum).

Usage (from backend/):
    # the cloud L2 (BigQuery hybrid, asia-south1) — billed embedding calls; deploy session only
    env -u VIRTUAL_ENV uv run python ../evaluation/calibrate_l2.py --backend cloud \\
        --dataset ../evaluation/data/l2_validation_known_item.json --write
    # the in-memory keyword stand-in — a dry run of the method; never written to runtime.yaml
    env -u VIRTUAL_ENV uv run python ../evaluation/calibrate_l2.py --backend local

Every score comes from `retriever.search` with the officer's scope. Before any query, every
canonical ID the dataset names must resolve through L0 for that officer: a dataset that names
records which do not exist (the 20 Nov set named 8 such IDs) is refused. The output says which
retriever was measured; `L2ConfidencePolicy.create` only accepts measured, cloud scores that meet
the target precision as a calibration. `--write` saves the report and
`evaluation/data/l2_calibration.json`; copying it into `runtime.yaml` stays a reviewed change.
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

from fastapi.testclient import TestClient  # noqa: E402

from app.auth.policy import scope_for  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.retrieval.calibration import (  # noqa: E402
    CalibrationResult,
    ValidationDataset,
    calibrate_threshold,
    collect_predictions,
)
from app.retrieval.confidence_policy import L2ConfidencePolicy  # noqa: E402

CALIBRATION_OUTPUT = ROOT / "evaluation" / "data" / "l2_calibration.json"
REPORTS_DIR = ROOT / "evaluation" / "reports"
CANDIDATES = [round(0.30 + 0.025 * i, 3) for i in range(27)]  # 0.300 … 0.950
MIN_SAMPLE = 100  # below this a precision estimate is too loose to end the ladder on


def missing_ids(dataset: ValidationDataset, exists: Any) -> list[str]:
    """Every ID the dataset names, checked through L0 for that query's officer."""
    out: list[str] = []
    for q in dataset.queries:
        for cid in (*q.relevant_canonical_ids, *q.distractor_canonical_ids):
            if not exists(q.user_id, cid):
                out.append(f"{q.id}: {cid}")
    return out


def report(result: CalibrationResult, dataset: ValidationDataset, retriever: str) -> str:
    policy = L2ConfidencePolicy.create(
        threshold=result.optimal_threshold, calibrated=True, metadata=result.metadata
    )
    m = result.metadata
    lines = [
        f"# L2 early-exit calibration — {dt.date.today().isoformat()}",
        "",
        f"- Retriever measured: `{retriever}`",
        f"- Dataset: `{dataset.version}` (N = {result.sample_size}) — {dataset.description}",
        f"- Selected threshold: `{result.optimal_threshold:.3f}`",
        f"- Precision {m.precision:.4f} (target ≥ {m.target_min_precision:.2f}) · recall "
        f"{m.recall:.4f} · F1 {m.f1:.4f}",
        f"- Ends at L2: {m.termination_rate:.1%} · wrong top hit accepted: "
        f"{m.false_termination_rate:.1%} · relevant but escalated: "
        f"{m.unnecessary_escalation_rate:.1%}",
        f"- Policy state this would give: `{policy.state.value}`",
        "",
        "| Threshold | P | R | F1 | Ends at L2 | False exit |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for c in result.candidates:
        mark = " ←" if c.threshold == result.optimal_threshold else ""
        lines.append(
            f"| {c.threshold:.3f}{mark} | {c.precision:.3f} | {c.recall:.3f} | {c.f1:.3f} | "
            f"{c.termination_rate:.1%} | {c.false_termination_rate:.1%} |"
        )
    if result.sample_size < MIN_SAMPLE:
        lines += ["", f"Not usable: N < {MIN_SAMPLE}."]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backend", choices=("local", "cloud"), required=True)
    ap.add_argument(
        "--dataset",
        type=Path,
        default=ROOT / "evaluation" / "data" / "l2_validation_known_item.json",
    )
    ap.add_argument("--min-precision", type=float, default=0.90)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--write", action="store_true", help="save the report and calibration json")
    args = ap.parse_args()

    dataset = ValidationDataset.load(args.dataset)
    settings = get_settings().model_copy(update={"sandbox": True})
    if args.backend == "cloud" and settings.retrieval_backend != "cloud":
        print("--backend cloud needs C2_RETRIEVAL_BACKEND=cloud and the cloud settings")
        return 2
    app = create_app(settings)
    with TestClient(app):  # start-up builds the runtime (and the cloud rungs when configured)
        run = app.state.assist_runtime()
        adapter = app.state.adapter

        def scope(uid: str) -> Any:
            return scope_for(uid, run.store_for(adapter.officer_context(uid)), run.policy,
                             run.classification)  # fmt: skip

        def exists(uid: str, cid: str) -> bool:
            ctx = run.tool_context(uid, run.store_for(adapter.officer_context(uid)))
            return bool(ctx.index.exact(cid, scope(uid)))

        gone = missing_ids(dataset, exists)
        if gone:
            print(f"Refused: {len(gone)} canonical ID(s) in the dataset do not resolve:")
            print("\n".join(f"  {g}" for g in gone[:40]))
            return 1
        if args.backend == "cloud":
            if run.cloud is None or run.cloud.l2 is None:
                print("No cloud L2 in this runtime (embedding model / BigQuery not configured)")
                return 2
            retriever, name = run.cloud.l2, f"bigquery-hybrid@{settings.gcp_region}"
        else:
            retriever, name = run.l2, "keyword stand-in (in-memory sandbox)"
        preds = collect_predictions(dataset, retriever, scope, top_k=args.top_k)

    result = calibrate_threshold(
        preds,
        CANDIDATES,
        min_precision=args.min_precision,
        dataset_version=dataset.version,
        retriever=name,
    )
    text = report(result, dataset, name)
    print(text)
    if args.write:
        today = dt.date.today().isoformat()
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / f"{today}-l2-calibration-{args.backend}.md").write_text(text, "utf-8")
        if args.backend == "cloud" and result.sample_size >= MIN_SAMPLE:
            CALIBRATION_OUTPUT.write_text(
                json.dumps(
                    {
                        "optimal_threshold": result.optimal_threshold,
                        "metadata": result.metadata.model_dump(),
                    },
                    indent=2,
                )
                + "\n",
                "utf-8",
            )
            print(
                f"written: {CALIBRATION_OUTPUT.relative_to(ROOT)} (copy to runtime.yaml by review)"
            )
        else:
            print("report only: a local stand-in or a small sample is never a calibration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
