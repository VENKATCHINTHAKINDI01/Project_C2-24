"""Join the corpus OCR cache into whole-file recorded responses the backend can replay (ADR-0017, ADR-0020).

ocr_corpus.py keeps one Document AI response per 15-page chunk:
    staging/ocr_cache/documentai/<version>/<sha256>-p<first>.json
The backend's RecordedOcr replays one response per file:
    staging/ocr_recorded/documentai/<version>/<sha256>.json        (written here)

Joining = the chunk texts end to end, every text anchor shifted by the length of the text before it; page numbers
are already absolute in the chunks. Nothing is re-read or paid for again, and the text is exactly what Document AI
returned. A file whose chunks do not start at page 1 or leave a gap is skipped and reported (never patched).

  python tools/join_ocr_cache.py                 # only the files in efiles_v2/eoffice/public_index.csv
  python tools/join_ocr_cache.py --all           # every cached file
  python tools/join_ocr_cache.py --version pretrained-ocr-v2.1.1-2025-01-31
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import ROOT  # noqa: E402

CACHE = ROOT / "staging" / "ocr_cache" / "documentai"
OUT = ROOT / "staging" / "ocr_recorded" / "documentai"
INDEX = HERE.parents[1] / "data" / "synthetic" / "mock_v1" / "efiles_v2" / "eoffice" / "public_index.csv"
CHUNK = re.compile(r"^(?P<sha>[0-9a-f]{64})-p(?P<first>\d+)\.json$")


def shift(node: Any, by: int) -> None:
    """Move every text anchor in a Document AI dict by `by` characters (indices are strings in to_dict)."""
    if isinstance(node, dict):
        for seg in node.get("text_segments") or ():
            seg["start_index"] = str(int(seg.get("start_index") or 0) + by)
            seg["end_index"] = str(int(seg.get("end_index") or 0) + by)
        for k, v in node.items():
            if k != "text_segments":
                shift(v, by)
    elif isinstance(node, list):
        for v in node:
            shift(v, by)


def join(parts: list[dict[str, Any]]) -> dict[str, Any]:
    doc = {k: v for k, v in parts[0].items() if k not in ("text", "pages")}
    text, pages = "", []
    for p in parts:
        for pg in p.get("pages") or ():
            shift(pg, len(text))
            pages.append(pg)
        text += str(p.get("text") or "")
    doc["text"], doc["pages"] = text, pages
    return doc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="pretrained-ocr-v2.1.1-2025-01-31")
    ap.add_argument("--all", action="store_true", help="join every cached file, not only the v2 public index")
    a = ap.parse_args()
    src, dst = CACHE / a.version, OUT / a.version
    chunks: dict[str, list[tuple[int, Path]]] = {}
    for f in src.glob("*.json"):
        if m := CHUNK.match(f.name):
            chunks.setdefault(m["sha"], []).append((int(m["first"]), f))
    want = set(chunks)
    if not a.all:
        with open(INDEX, encoding="utf-8", newline="") as fh:
            want &= {r["sha256"] for r in csv.DictReader(fh)}
    dst.mkdir(parents=True, exist_ok=True)
    done, skipped = 0, []
    for sha in sorted(want):
        parts = [json.loads(f.read_text("utf-8")) for _, f in sorted(chunks[sha])]
        nums = [int(pg.get("page_number") or 0) for p in parts for pg in p.get("pages") or ()]
        if not nums or nums != list(range(1, len(nums) + 1)):
            skipped.append(sha[:12])
            continue
        (dst / f"{sha}.json").write_text(json.dumps(join(parts), ensure_ascii=False), "utf-8")
        done += 1
    print(f"{done} files joined into {dst.relative_to(ROOT)} ({len(want)} wanted with OCR in the cache); "
          f"skipped {len(skipped)} with page gaps: {skipped}")


if __name__ == "__main__":
    main()
