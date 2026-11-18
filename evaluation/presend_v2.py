"""Pre-send check (touchpoint 11) on every file of synthetic set v2, scored against its planted
conflicts.

    cd backend
    DATA=~/Documents/c2-24-corpus
    env -u VIRTUAL_ENV uv run python ../evaluation/presend_v2.py --public-dir $DATA --count
        # how many Gemini questions the B / G check asks, and how many are not yet saved
        # (only those would be sent and paid on --live); nothing is sent
    env -u VIRTUAL_ENV uv run python ../evaluation/presend_v2.py --public-dir $DATA --live
        # asks Gemini (billed, your gcloud login); answers cached in data/synthetic/mock_v1/llm/
    env -u VIRTUAL_ENV uv run python ../evaluation/presend_v2.py --public-dir $DATA
        # default: replays the cached answers only (no calls)

Each file is checked as its department head (Department scope) on the latest note. A planted
conflict counts as found when a flag of its type is raised; a clean file counts as falsely flagged
when any flag is raised. Writes evaluation/reports/<date>-presend-v2[-label].md/.json.
EVALUATION ONLY: synthetic files on real public orders; uncalibrated sandbox values; mock type C.
"""

from __future__ import annotations

import argparse
import collections
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

from app.agents.llm import LLMError, RecordedLLM  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402
from evaluation.harness.limits import NO_RATE_LIMITS, RefusedError  # noqa: E402

V2 = ROOT / "data" / "synthetic" / "mock_v1" / "efiles_v2"
REPORTS = ROOT / "evaluation" / "reports"
HEAD = {"FIN01": "V07", "GAD01": "V14", "ESE01": "V21"}


class Counter:
    """--count: answers nothing; counts the questions and how many already have a saved answer
    (those cost nothing on a live run). The check is then incomplete."""

    name = "count-only"

    def __init__(self, saved: Any = None) -> None:
        self.saved = saved  # RecordedLLM over the cache, or None
        self.n = self.new = 0
        self.chars = self.new_chars = 0

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        self.n += 1
        self.chars += len(system) + len(user)
        try:
            if self.saved is None:
                raise LLMError("no cache")
            self.saved.generate_json(prompt_id=prompt_id, system=system, user=user, schema=schema)
        except LLMError:
            self.new += 1
            self.new_chars += len(system) + len(user)
        raise LLMError("count only")


class Reasons:
    """Passes questions through and keeps why any failed (the error type only, never text)."""

    def __init__(self, inner: Any) -> None:
        self.inner, self.name = inner, getattr(inner, "name", "llm")
        self.failed: collections.Counter[str] = collections.Counter()

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            out: dict[str, Any] = self.inner.generate_json(
                prompt_id=prompt_id, system=system, user=user, schema=schema
            )
            return out
        except LLMError as exc:
            self.failed[str(exc)] += 1
            raise


HINTS = {
    "RefreshError": "sign-in expired: run `gcloud auth application-default login`",
    "DefaultCredentialsError": "not signed in: run `gcloud auth application-default login`",
    "PermissionDenied": "the account lacks Vertex AI access on this project",
    "NotFound": "model or region not available: check C2_GEMINI_MODEL / C2_GCP_REGION",
    "ResourceExhausted": "quota reached: wait and re-run (saved answers are kept)",
    "no recorded answer": "not yet saved: run with --live",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--public-dir", type=Path, required=True, help="data root with staging/rule-library"
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--count", action="store_true")
    mode.add_argument("--recorded", action="store_true")
    ap.add_argument("--label", default="")
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()

    provider = "vertex" if a.live else "recorded"
    settings = get_settings().model_copy(
        update={
            "sandbox": True,
            "sandbox_seed": "v2",
            "sandbox_public_corpus_dir": a.public_dir.expanduser(),
            "llm_provider": provider,
            "state_store": "memory",
            **NO_RATE_LIMITS,  # ~200 checks per simulated head in a burst (harness/limits.py)
        }
    )
    app = create_app(settings)
    client = TestClient(app)
    run = app.state.assist_runtime()
    counter = None
    reasons = None
    if not a.count and run.llm is not None:
        reasons = Reasons(run.llm)
        run.llm = reasons
    if a.count:
        counter = Counter(RecordedLLM(settings.llm_recorded_dir, settings.gemini_model))
        run.llm = counter
    gt = json.loads(
        (V2 / "ground_truth" / "efiles_v2_conflicts.json").read_text()
    )  # evaluation only
    seed = json.loads((V2 / "eoffice" / "seed_v2.json").read_text())
    planted = {g["file_no"]: g["type"] for g in gt}

    score: collections.Counter[tuple[str, str]] = collections.Counter()
    refused: collections.Counter[int] = collections.Counter()  # a refused check measured nothing
    incomplete, rows = 0, []
    for f in seed["files"]:
        r = client.post(
            "/assist/presend",
            json={"computer_no": f["computer_no"]},
            headers={"X-Sandbox-User": HEAD[f["department"]]},
        )
        if r.status_code != 200:
            refused[r.status_code] += 1
        body = r.json() if r.status_code == 200 else {}
        types = sorted({x.get("type") for x in body.get("flags", [])})
        if any("contradiction check" in g for g in body.get("fact_gaps", [])):
            incomplete += 1
        t = planted.get(f["file_no"], "clean")
        hit = "found" if t in types else ("other flag" if types else "nothing")
        score[(t, hit)] += 1
        rows.append({"file_no": f["file_no"], "planted": t, "flags": types})

    if counter is not None:
        print(
            f"B / G check: {counter.n} questions (~{counter.chars // 4:,} input tokens), "
            f"{counter.n - counter.new} already saved, {counter.new} not yet saved "
            f"(~{counter.new_chars // 4:,} input tokens; only these would be sent and paid, "
            f"{settings.gemini_model}). Nothing was sent."
        )
        return 0
    if refused:  # every head may open every file of the department: any non-200 is a failure
        raise RefusedError(f"presend_v2: checks refused with HTTP {dict(refused)}; no report")
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    lines = [
        f"# Pre-send on synthetic set v2 — {now}",
        "",
        f"Model for B / G: `{settings.gemini_model}` ({provider}); files where the B / G check "
        f"was incomplete: {incomplete}. EVALUATION ONLY (synthetic files, real public orders, "
        "uncalibrated sandbox values, mock type C rules).",
        "",
        "| Planted | Files | Found | Other flag | Nothing |",
        "|---|---:|---:|---:|---:|",
    ]
    for t in ["A", "B", "C", "D", "E", "F", "G", "clean"]:
        n = sum(v for (tt, _), v in score.items() if tt == t)
        other, none = score[(t, "other flag")], score[(t, "nothing")]
        found = "—" if t == "clean" else score[(t, "found")]
        note = " (false flags)" if t == "clean" else ""
        lines.append(f"| {t} | {n} | {found} | {other}{note} | {none} |")
    if reasons is not None and reasons.failed:
        lines += [
            "",
            "Questions that got no answer (the B / G check is incomplete for those files):",
        ]
        for why, n in reasons.failed.most_common():
            hint = next((h for k, h in HINTS.items() if k in why), "")
            lines.append(f"- {n} × {why}" + (f" — {hint}" if hint else ""))
    print("\n".join(lines))
    if not a.no_write:
        stem = f"{dt.date.today().isoformat()}-presend-v2" + (f"-{a.label}" if a.label else "")
        REPORTS.mkdir(parents=True, exist_ok=True)
        (REPORTS / f"{stem}.md").write_text("\n".join(lines) + "\n")
        (REPORTS / f"{stem}.json").write_text(
            json.dumps(
                {
                    "model": settings.gemini_model,
                    "provider": provider,
                    "incomplete": incomplete,
                    "unanswered": dict(reasons.failed) if reasons is not None else {},
                    "score": {f"{k[0]}|{k[1]}": v for k, v in sorted(score.items())},
                    "files": rows,
                },
                indent=1,
            )
        )
        print(f"wrote {REPORTS / stem}.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
