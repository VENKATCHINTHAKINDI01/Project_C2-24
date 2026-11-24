"""Calibrate the L2 early-exit threshold on a REAL retriever, and check it on the holdout
(ADR-0061 and its 24 Nov 2026 addendum). Replaces the former `evaluate_holdout.py`.

The exit is measured exactly as the ladder runs it: one hit per order (best passage), the score
gap to the runner-up order (`--margin`), the attribute gate (`config/l2_safeguards.yaml`) and the
graph gate on the same graph the assistant walks. A threshold qualifies only if the LOW end of the
95% Wilson interval of its precision clears `--min-precision`. The calibration file records the
gap and the safeguards, and the API accepts it only if they match how it runs.

Usage (from backend/):
    # dry run of the method on the in-memory sandbox (no cost, never a calibration)
    env -u VIRTUAL_ENV uv run python ../evaluation/calibrate_l2.py --backend local --margin 0.03
    # the cloud L2 (BigQuery hybrid, asia-south1): BILLED — run only with the owner's approval
    env -u VIRTUAL_ENV uv run python ../evaluation/calibrate_l2.py --backend cloud --margin 0.03 \\
        --dataset ../evaluation/data/l2_calibration_set.json --write
    # check the written calibration on the family-disjoint holdout (billed on cloud)
    env -u VIRTUAL_ENV uv run python ../evaluation/calibrate_l2.py --backend cloud \\
        --holdout ../evaluation/data/l2_holdout_dataset.json --write

Before any query, every canonical ID the dataset names must resolve through L0 for that officer;
a dataset naming records that do not exist is refused. `--write` saves the report (and, for a
cloud calibration of at least 100 queries, `evaluation/data/l2_calibration.json`). Turning it on
stays a reviewed change: `runtime.yaml` (sandbox) or `L2_CALIBRATION=<file>` on deploy (cloud).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import subprocess
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
    CandidateEvaluation,
    QueryPrediction,
    ValidationDataset,
    calibrate_threshold,
    collect_predictions,
    evaluate_predictions_at_threshold,
    exits,
)
from app.retrieval.confidence_policy import SAFEGUARDS, L2ConfidencePolicy  # noqa: E402

CALIBRATION_OUTPUT = ROOT / "evaluation" / "data" / "l2_calibration.json"
DATA_DIR = ROOT / "evaluation" / "data"
REPORTS_DIR = ROOT / "evaluation" / "reports"
# 0.30, 0.40, 0.50, then 0.55 … 0.95 in steps of 0.01 (ADR-0061)
CANDIDATES = sorted(
    {round(x, 3) for x in [0.30, 0.40, 0.50] + [0.55 + 0.01 * i for i in range(41)]}
)
MIN_SAMPLE = 100  # below this a precision estimate is too loose to end the ladder on


def use_gcloud_user_credentials() -> None:
    """On a workstation without application-default credentials, use the gcloud user's token
    (refreshed from `gcloud auth print-access-token`). Cloud runs only."""
    import google.auth  # noqa: PLC0415
    import google.auth.credentials  # noqa: PLC0415
    import google.auth.exceptions  # noqa: PLC0415

    def token() -> str:
        cmd = ["gcloud", "auth", "print-access-token"]
        return subprocess.check_output(cmd).decode().strip()  # noqa: S603

    class GcloudCredentials(google.auth.credentials.Credentials):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self.token = token()

        def refresh(self, request: Any) -> None:
            self.token = token()

    try:
        google.auth.default()
    except google.auth.exceptions.DefaultCredentialsError:
        creds = GcloudCredentials()
        google.auth.default = lambda *a, **k: (creds, get_settings().gcp_project_id)


def missing_ids(dataset: ValidationDataset, exists: Any) -> list[str]:
    """Every ID the dataset names, checked through L0 for that query's officer."""
    out: list[str] = []
    checked: dict[tuple[str, str], bool] = {}
    for q in dataset.queries:
        for cid in (*q.relevant_canonical_ids, *q.distractor_canonical_ids):
            key = (q.user_id, cid)
            if key not in checked:
                checked[key] = exists(q.user_id, cid)
            if not checked[key]:
                out.append(f"{q.id}: {cid}")
    return out


def _row(c: CandidateEvaluation, mark: str = "") -> str:
    exited = c.tp + c.fp
    return (
        f"| {c.threshold:.3f}{mark} | {exited} | {c.tp} | {c.fp} | {c.fn} | {c.tn} | "
        f"{c.precision:.3f} | {c.precision_ci_low:.3f} | {c.recall:.3f} | "
        f"{c.termination_rate:.1%} |"
    )


_HEAD = [
    "| Threshold | Exits | TP | FP | FN | TN | Precision | 95% low | Recall | Ends at L2 |",
    "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
]


def _blocked(preds: list[QueryPrediction], th: float, margin: float | None) -> list[str]:
    over = [p for p in preds if p.top_score >= th]
    gap = sum(1 for p in over if margin is not None and p.runner_up_gap is not None
              and p.runner_up_gap < margin)  # fmt: skip
    graph = sum(1 for p in over if not p.gates_ok and "linked by" in (p.gate_note or ""))
    attr = sum(1 for p in over if not p.gates_ok and "linked by" not in (p.gate_note or ""))
    return [
        f"- Over the threshold: {len(over)}; kept at L3 by the score gap: {gap}, by the attribute "
        f"gate: {attr}, by the graph gate: {graph}",
    ]


def _by_dept(preds: list[QueryPrediction], th: float, margin: float | None) -> list[str]:
    lines = ["", "| Department | Queries | Exits | TP | FP |", "|:---|---:|---:|---:|---:|"]
    for d in sorted({p.category for p in preds}):
        ps = [p for p in preds if p.category == d]
        ex = [p for p in ps if exits(p, th, margin)]
        tp = sum(p.is_relevant_hit for p in ex)
        lines.append(f"| {d} | {len(ps)} | {len(ex)} | {tp} | {len(ex) - tp} |")
    return lines


def calibration_report(
    result: CalibrationResult, dataset: ValidationDataset, retriever: str,
    preds: list[QueryPrediction], margin: float | None,
) -> str:  # fmt: skip
    m = result.metadata
    policy = L2ConfidencePolicy.create(
        threshold=result.optimal_threshold, calibrated=True, metadata=m, margin=margin
    )
    c = result.selected_candidate
    no_answer = sum(1 for q in dataset.queries if not q.relevant_canonical_ids)
    lines = [
        f"# L2 early-exit calibration — {dt.date.today().isoformat()}",
        "",
        f"- Retriever measured: `{retriever}`",
        f"- Dataset: `{dataset.version}` (N = {result.sample_size}; {no_answer} with no answer in "
        f"the records) — {dataset.description}",
        f"- Measured as the ladder runs: one hit per order, score gap ≥ `{margin}`, safeguards "
        f"`{', '.join(m.safeguards) or 'none'}`",
        f"- Selected threshold: `{result.optimal_threshold:.3f}` — precision {c.precision:.3f}, "
        f"95% lower bound {c.precision_ci_low:.3f} (target ≥ {m.target_min_precision:.2f}), "
        f"recall {c.recall:.3f}, ends at L2 on {c.termination_rate:.1%}",
        f"- Exits: {c.tp} correct, {c.fp} wrong; {c.fn} correct top hits sent on to L3",
        f"- Policy state this would give: `{policy.state.value}`",
        *_blocked(preds, result.optimal_threshold, margin),
        "",
        "## Candidate thresholds",
        "",
        *_HEAD,
        *(
            _row(x, " ←" if x.threshold == result.optimal_threshold else "")
            for x in result.candidates
        ),
        "",
        "## By department (selected threshold)",
        *_by_dept(preds, result.optimal_threshold, margin),
    ]
    if result.sample_size < MIN_SAMPLE:
        lines += ["", f"Not usable: N < {MIN_SAMPLE}."]
    return "\n".join(lines) + "\n"


def holdout_report(
    preds: list[QueryPrediction], dataset: ValidationDataset, retriever: str,
    threshold: float, margin: float | None,
) -> str:  # fmt: skip
    at = evaluate_predictions_at_threshold(preds, threshold, margin)
    near = [evaluate_predictions_at_threshold(preds, t, margin) for t in CANDIDATES
            if abs(t - threshold) <= 0.05]  # fmt: skip
    lines = [
        f"# L2 holdout check — {dt.date.today().isoformat()}",
        "",
        f"- Retriever: `{retriever}` · holdout `{dataset.version}` (N = {len(preds)})",
        f"- Threshold `{threshold:.3f}`, score gap ≥ `{margin}`, "
        f"safeguards `{', '.join(SAFEGUARDS)}`",
        f"- Exits {at.tp + at.fp}: {at.tp} correct, {at.fp} wrong · precision {at.precision:.3f}, "
        f"95% lower bound {at.precision_ci_low:.3f} · ends at L2 on {at.termination_rate:.1%}",
        *_blocked(preds, threshold, margin),
        "",
        "## Around the threshold",
        "",
        *_HEAD,
        *(_row(x, " ←" if x.threshold == threshold else "") for x in near),
        "",
        "## By department",
        *_by_dept(preds, threshold, margin),
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--backend", choices=("local", "cloud"), required=True)
    ap.add_argument("--dataset", type=Path, default=DATA_DIR / "l2_validation_known_item.json")
    ap.add_argument("--holdout", type=Path, help="check a calibration on this holdout instead")
    ap.add_argument(
        "--threshold", type=float, help="with --holdout: default = the calibration file"
    )
    ap.add_argument("--margin", type=float, help="score gap to the runner-up order (e.g. 0.03)")
    ap.add_argument("--min-precision", type=float, default=0.90)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument(
        "--write", action="store_true", help="save the report, predictions, calibration"
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    margin = args.margin
    threshold = args.threshold
    if args.holdout and threshold is None:
        saved = json.loads(CALIBRATION_OUTPUT.read_text("utf-8"))
        threshold = float(saved["optimal_threshold"])
        margin = saved["metadata"].get("min_margin") if margin is None else margin
    dataset = ValidationDataset.load(args.holdout or args.dataset)

    settings = get_settings().model_copy(update={"sandbox": True})
    if args.backend == "cloud":
        if settings.retrieval_backend != "cloud":
            print("--backend cloud needs C2_RETRIEVAL_BACKEND=cloud and the cloud settings")
            return 2
        use_gcloud_user_credentials()
    app = create_app(settings)
    with TestClient(app):  # start-up builds the runtime (and the cloud rungs when configured)
        run = app.state.assist_runtime()
        adapter = app.state.adapter

        def store(uid: str) -> Any:
            return run.store_for(adapter.officer_context(uid))

        def scope(uid: str) -> Any:
            return scope_for(uid, store(uid), run.policy, run.classification)

        def exists(uid: str, cid: str) -> bool:
            return bool(run.tool_context(uid, store(uid)).index.exact(cid, scope(uid)))

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
        uid = dataset.queries[0].user_id
        graph = run.tool_context(uid, store(uid)).graph  # the graph the assistant walks
        preds = collect_predictions(dataset, retriever, scope, top_k=args.top_k, graph=graph)

    today = dt.date.today().isoformat()
    kind = "holdout" if args.holdout else "calibration"
    if args.holdout:
        assert threshold is not None
        text = holdout_report(preds, dataset, name, threshold, margin)
    else:
        result = calibrate_threshold(
            preds, CANDIDATES, min_precision=args.min_precision, dataset_version=dataset.version,
            retriever=name, min_margin=margin, safeguards=SAFEGUARDS,
        )  # fmt: skip
        text = calibration_report(result, dataset, name, preds, margin)
    print(text)
    if not args.write:
        return 0
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / f"{today}-l2-{kind}-{args.backend}.md").write_text(text, "utf-8")
    (DATA_DIR / f"l2_{kind}_predictions_{args.backend}.json").write_text(
        json.dumps([p.model_dump() for p in preds], indent=1) + "\n", "utf-8"
    )
    if args.holdout:
        return 0
    if args.backend == "cloud" and result.sample_size >= MIN_SAMPLE:
        CALIBRATION_OUTPUT.write_text(
            json.dumps(
                {"optimal_threshold": result.optimal_threshold,
                 "metadata": result.metadata.model_dump(mode="json")},
                indent=2,
            ) + "\n",
            "utf-8",
        )  # fmt: skip
        print(
            f"written: {CALIBRATION_OUTPUT.relative_to(ROOT)} (turning it on is a reviewed change)"
        )
    else:
        print("report only: a local stand-in or a small sample is never a calibration")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
