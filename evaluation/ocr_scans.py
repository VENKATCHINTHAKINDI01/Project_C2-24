"""OCR accuracy suite on the synthetic scans (CLAUDE.md §9.3 "OCR/extraction accuracy"; plan §4.2).

EVALUATION ONLY: reads the hand transcriptions in `ground_truth/text`. Application code never does.

For every corpus file with image-only pages:
1. OCR exactly those pages with Document AI (ADR-0017, asia-south1). Responses are cached in
   `data/synthetic/mock_v1/ocr/documentai/<sha256>.json`, so a file is billed once and later runs
   are free and reproducible.
2. Compare the merged text (native pages + OCR pages) with the hand transcription: word error rate
   and character similarity, after whitespace normalisation.
3. Check that the fields that matter survive OCR: is the canonical ID read from the OCR text
   the same as the one read from the transcription?
4. Record per-page OCR confidence next to the error rates. That table is the evidence for
   calibrating `ingestion.extraction_confidence_min`, which stays null until the owner approves a
   value (CLAUDE.md §9.4).

Live calls need `--live` plus project, region and processor (flags or C2_* env). Without `--live`,
only cached responses are used, and a file with no cached response is reported as not run.
Synthetic data only: no department data is sent anywhere.
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.config import REPO_ROOT  # noqa: E402
from app.identifiers.resolver import load_departments  # noqa: E402
from app.ingestion.detect import detect_file  # noqa: E402
from app.ingestion.document_store import media_type  # noqa: E402
from app.ingestion.extract import PageSource, extract_native  # noqa: E402
from app.ingestion.metadata import extract_metadata  # noqa: E402
from app.ingestion.ocr import (  # noqa: E402
    CachingOcr,
    DocumentAiOcr,
    OcrEngine,
    OcrError,
    RecordedOcr,
    load_recorded,
    version_dir,
)
from evaluation.run_eval import free_name  # noqa: E402

CORPUS = REPO_ROOT / "data" / "synthetic" / "mock_v1"
CACHE_ROOT = CORPUS / "ocr" / "documentai"  # one folder per OCR model version
V1 = "pretrained-ocr-v1.0-2020-09-23"  # processor default in asia-south1 (11 Nov 2026)
REPORTS = ROOT / "evaluation" / "reports"


def _norm(text: str) -> str:
    """Whitespace, dash variants and "Dt. 17" vs "Dt.17" are layout, not reading errors."""
    text = re.sub(r"[\u2010-\u2015\u2212]", "-", text)
    text = re.sub(r"(?<=[.:])[ \t]+(?=\d)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def recall(ref: str, hyp: str) -> float:
    """Share of reference words OCR recovered, in order. Unlike WER, it does not count text the
    transcription left out (signature blocks, distribution lists, footers) as errors."""
    r, h = _norm(ref).split(), _norm(hyp).split()
    sm = difflib.SequenceMatcher(None, r, h, autojunk=False)
    return round(sum(b.size for b in sm.get_matching_blocks()) / max(len(r), 1), 4)


def identity(meta: Any) -> str | None:
    """What identifies the record: its canonical ID, or for notes/reports its e-File number."""
    return meta.canonical_id or (f"file:{meta.file_no}" if meta.file_no else None)


def wer(ref: str, hyp: str) -> float:
    """Word error rate: word-level edit distance / reference words."""
    r, h = _norm(ref).split(), _norm(hyp).split()
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hw in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw))
        prev = cur
    return round(prev[-1] / max(len(r), 1), 4)


def char_similarity(ref: str, hyp: str) -> float:
    """difflib ratio on normalised text (1.0 = identical). An approximation, labelled as such."""
    return round(difflib.SequenceMatcher(None, _norm(ref), _norm(hyp), autojunk=False).ratio(), 4)


def _rows() -> list[dict[str, str]]:
    import csv

    with (CORPUS / "documents_index.csv").open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run(engine: OcrEngine) -> dict[str, Any]:
    depts = load_departments(REPO_ROOT / "data" / "ontology" / "departments.yaml")
    out: list[dict[str, Any]] = []
    for row in _rows():
        path = CORPUS / row["file"]
        data = path.read_bytes()
        native = extract_native(data, detect_file(path))
        need = [p.page for p in native.pages if p.source is PageSource.NEEDS_OCR]
        if not need:
            continue
        rec: dict[str, Any] = {"doc": row["id"], "file": row["file"], "pages": need}
        try:
            res = engine.read(data, media_type(data, path.name), need)
        except OcrError as exc:
            out.append({**rec, "error": str(exc)})
            continue
        merged = "\n".join(
            (p.text or "")
            if p.source is PageSource.NATIVE
            else (res.page(p.page) or res.pages[0]).text
            for p in native.pages
        )
        truth = (CORPUS / "ground_truth" / "text" / f"{row['id']}.txt").read_text("utf-8")
        cid_ocr = identity(extract_metadata(merged, depts, source_department=row["department"]))
        cid_truth = identity(extract_metadata(truth, depts, source_department=row["department"]))
        confs = [p.confidence for p in res.pages if p.confidence is not None]
        out.append(
            {
                **rec,
                "engine": res.engine,
                "page_confidence": {str(p.page): p.confidence for p in res.pages},
                "min_confidence": min(confs) if confs else None,
                "languages": sorted({lang for p in res.pages for lang in p.languages}),
                "wer": wer(truth, merged),
                "recall": recall(truth, merged),
                "char_similarity": char_similarity(truth, merged),
                "canonical_id_ocr": cid_ocr,
                "canonical_id_truth": cid_truth,
                "canonical_id_match": cid_ocr == cid_truth and cid_truth is not None,
            }
        )
    done = [r for r in out if "error" not in r]
    return {
        "suite": "ocr-accuracy",
        "corpus": "mock_v1 (SYNTHETIC)",
        "run_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "documents": out,
        "summary": {
            "files_needing_ocr": len(out),
            "ocr_run": len(done),
            "not_run": [r["doc"] for r in out if "error" in r],
            "mean_wer": round(sum(r["wer"] for r in done) / len(done), 4) if done else None,
            "mean_recall": round(sum(r["recall"] for r in done) / len(done), 4) if done else None,
            "mean_char_similarity": round(sum(r["char_similarity"] for r in done) / len(done), 4)
            if done
            else None,
            "canonical_id_match": f"{sum(r['canonical_id_match'] for r in done)}/{len(done)}",
        },
    }


def markdown(rep: dict[str, Any]) -> str:
    s = rep["summary"]
    lines = [
        f"# OCR accuracy — {rep['corpus']} — {rep['run_at'][:10]}",
        "",
        "EVALUATION ONLY. Hand transcriptions are the reference. Word recall = share of reference",
        "words OCR recovered in order (text the transcription omits is not an error). WER is exact",
        "but also counts that omitted text; dash variants and spacing are normalised first.",
        "Character similarity is difflib's ratio (an approximation). Confidence is Document AI's,",
        "weighted by token length. The gate threshold stays **uncalibrated (null)** until the",
        "owner approves a value from this evidence.",
        "",
        f"- Files with image-only pages: **{s['files_needing_ocr']}**, OCR run: **{s['ocr_run']}**"
        + (f", not run: {', '.join(s['not_run'])}" if s["not_run"] else ""),
        f"- Mean word recall: **{s['mean_recall']}** · mean WER: **{s['mean_wer']}** · "
        f"mean character similarity: **{s['mean_char_similarity']}**",
        "- Record identity (canonical ID, or e-File no. for notes) read correctly from OCR "
        f"text: **{s['canonical_id_match']}**",
        "",
        "| Doc | OCR pages | Min conf. | Recall | WER | Char sim. | Languages | ID from OCR "
        "| ID matches |",
        "|---|---|---:|---:|---:|---:|---|---|:---:|",
    ]
    for r in rep["documents"]:
        if "error" in r:
            lines.append(
                f"| {r['doc']} | {r['pages']} | — | — | — | — | not run: {r['error']} | — |"
            )
            continue
        lines.append(
            f"| {r['doc']} | {r['pages']} | {r['min_confidence']} | {r['recall']} | {r['wer']} | "
            f"{r['char_similarity']} | {', '.join(r['languages'])} | `{r['canonical_id_ocr']}` | "
            f"{'✓' if r['canonical_id_match'] else '✗'} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true", help="call Document AI for files not cached")
    ap.add_argument("--project", default=os.environ.get("C2_GCP_PROJECT_ID"))
    ap.add_argument("--location", default=os.environ.get("C2_GCP_REGION"))
    ap.add_argument("--processor", default=os.environ.get("C2_DOCAI_OCR_PROCESSOR_ID"))
    ap.add_argument(
        "--version",
        default=os.environ.get("C2_DOCAI_OCR_PROCESSOR_VERSION"),
        help="OCR model version to pin (e.g. pretrained-ocr-v2.1.1-2025-01-31)",
    )
    ap.add_argument("--name", default=None, help="report name (default: <date>-ocr-documentai)")
    args = ap.parse_args()
    if args.live:
        engine: OcrEngine = CachingOcr(
            DocumentAiOcr(
                args.project or "",
                args.location or "",
                args.processor or "",
                processor_version=args.version,
            ),
            CACHE_ROOT,
        )
    else:
        engine = RecordedOcr(
            load_recorded(version_dir(CACHE_ROOT, args.version)),
            f"documentai:recorded:{args.version or 'default'}",
        )
    rep = run(engine)
    REPORTS.mkdir(exist_ok=True)
    tag = f"-{args.version}" if args.version else ""
    name = free_name(REPORTS, args.name or f"{dt.date.today().isoformat()}-ocr-documentai{tag}")
    (REPORTS / f"{name}.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), "utf-8")
    (REPORTS / f"{name}.md").write_text(markdown(rep), "utf-8")
    print(markdown(rep))
    print(f"Report: evaluation/reports/{name}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
