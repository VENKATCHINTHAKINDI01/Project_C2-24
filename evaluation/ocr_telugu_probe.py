"""Investigation: why Document AI did not read the Telugu photo D16 (11 Nov 2026 run).

EVALUATION ONLY (reads the hand transcription). Live calls, roughly 1 page each (cents in all).
Tries the same image with different language hints and with every processor version available to
`c2-ocr` in the region. Reports word recall against the transcription, the detected languages and
the confidence. Writes a report and does NOT touch the OCR cache.

Usage (Mac, gcp extra installed):
  uv run python ../evaluation/ocr_telugu_probe.py --project P --location asia-south1 --processor ID
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

from app.ingestion.document_store import media_type  # noqa: E402
from app.ingestion.ocr import parse_document  # noqa: E402
from evaluation.ocr_scans import CORPUS, REPORTS, recall  # noqa: E402
from evaluation.run_eval import free_name  # noqa: E402

DOC = "D16"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project", required=True)
    ap.add_argument("--location", required=True)
    ap.add_argument("--processor", required=True)
    args = ap.parse_args()

    from google.cloud import documentai_v1 as d

    client = d.DocumentProcessorServiceClient(
        client_options={"api_endpoint": f"{args.location}-documentai.googleapis.com"}
    )
    proc = client.processor_path(args.project, args.location, args.processor)
    versions = [
        (v.name, v.display_name, str(v.state.name))
        for v in client.list_processor_versions(parent=proc)
    ]

    import csv

    with (CORPUS / "documents_index.csv").open(encoding="utf-8") as f:
        row = next(r for r in csv.DictReader(f) if r["id"] == DOC)
    data = (CORPUS / row["file"]).read_bytes()
    mime = media_type(data, row["file"])
    truth = (CORPUS / "ground_truth" / "text" / f"{DOC}.txt").read_text("utf-8")

    trials: list[tuple[str, str, list[str] | None]] = [
        ("default version", proc, None),
        ("default version", proc, ["te"]),
        ("default version", proc, ["te", "en"]),
    ]
    trials += [
        (f"{disp} ({state})", name, ["te"]) for name, disp, state in versions if state == "DEPLOYED"
    ]

    results: list[dict[str, Any]] = []
    for label, name, hints in trials:
        opts = d.ProcessOptions()
        if hints:
            opts.ocr_config = d.OcrConfig(hints=d.OcrConfig.Hints(language_hints=hints))
        try:
            res = client.process_document(
                request=d.ProcessRequest(
                    name=name,
                    raw_document=d.RawDocument(content=data, mime_type=mime),
                    process_options=opts,
                )
            )
        except Exception as exc:  # noqa: BLE001 — record and carry on with the next trial
            results.append({"trial": label, "hints": hints, "error": type(exc).__name__})
            continue
        doc = d.Document.to_dict(res.document)
        page = parse_document(doc, label, [1]).pages[0]
        results.append(
            {
                "trial": label,
                "processor_version": name.rsplit("/", 1)[-1],
                "hints": hints,
                "confidence": page.confidence,
                "languages": list(page.languages),
                "recall": recall(truth, page.text),
                "first_line": page.text.splitlines()[0][:60] if page.text else "",
            }
        )

    rep = {
        "suite": "ocr-telugu-probe",
        "doc": DOC,
        "run_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "versions": versions,
        "trials": results,
    }
    name = free_name(REPORTS, f"{dt.date.today().isoformat()}-ocr-telugu-probe")
    (REPORTS / f"{name}.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), "utf-8")
    lines = [
        f"# Telugu OCR probe — {DOC} (SYNTHETIC photo) — {rep['run_at'][:10]}",
        "",
        "| Trial | Version | Hints | Conf. | Recall | Languages | First line |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for r in results:
        if "error" in r:
            lines.append(f"| {r['trial']} | — | {r['hints']} | — | — | error: {r['error']} | |")
        else:
            lines.append(
                f"| {r['trial']} | {r['processor_version']} | {r['hints']} | {r['confidence']} | "
                f"{r['recall']} | {', '.join(r['languages'])} | {r['first_line']} |"
            )
    (REPORTS / f"{name}.md").write_text("\n".join(lines) + "\n", "utf-8")
    print("\n".join(lines))
    print(f"\nReport: evaluation/reports/{name}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
