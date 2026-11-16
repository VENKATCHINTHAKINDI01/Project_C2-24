"""OCR the public corpus with Document AI: scans with no text layer and PDFs whose text is unreadable.

Owner OK 13 Nov 2026. Uses the backend's Document AI reader (app/ingestion/ocr.py): Enterprise Document OCR, the pinned
model version (ADR-0017: pretrained-ocr-v2.1.1-2025-01-31, reads Telugu), region-pinned endpoint, te/en hints.
Online requests take at most 15 pages, so longer PDFs are read in 15-page chunks.

Run from backend/ with the gcp extra (dry run by default: lists files, pages and cost; nothing is sent):

  env -u VIRTUAL_ENV uv run python ../data_collection/tools/ocr_corpus.py
  env -u VIRTUAL_ENV uv run python ../data_collection/tools/ocr_corpus.py --apply --limit 3     # test: 3 files
  env -u VIRTUAL_ENV uv run python ../data_collection/tools/ocr_corpus.py --apply               # all
  … --id <canonical ID> [--id …] --force    # named files even if their text layer looks readable
  … --ids-file <file> --cache-only [--apply]  # text PDFs whose pages also carry an image: response to the cache only

For each file:
- every Document AI response is kept in staging/ocr_cache/documentai/<version>/<sha256>-p<first>.json, so a re-run
  never pays twice;
- the text goes to ocr.txt (pages separated by form feeds); an older ocr.txt is kept as ocr.archive.txt, never deleted;
- meta.json records ocr_source, ocr_version, ocr_pages, ocr_confidence (mean of page confidences), and pages the
  engine gave no confidence for (ocr_pages_unconfirmed). Low or missing confidence is recorded, not hidden: the OCR
  review gate applies at ingestion (ADR-0018).

Skipped: withheld (confidential) and document_missing records, and files already read with this model version.
Stops after 3 errors in a row. Cost: list price US$1.50 per 1,000 pages after the first 1,000 each month
(cloud.google.com/document-ai/pricing, checked 13 Nov 2026).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from io import BytesIO
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "backend"))
from common import ROOT, now, write_json  # noqa: E402  (data root, ADR-0006)

ST = ROOT / "staging"
CHUNK = 15
PRICE_PER_1000 = 1.50
FREE_PAGES = 1000
VERSION = "pretrained-ocr-v2.1.1-2025-01-31"


logging.getLogger("pypdf").setLevel(logging.ERROR)   # font / duplicate-key warnings on old gazette PDFs are harmless


def pages_and_text(pdf: Path) -> tuple[int, str]:
    from pypdf import PdfReader
    r = PdfReader(str(pdf))
    head = "".join((p.extract_text() or "") for p in r.pages[:2])
    return len(r.pages), head


def readable(text: str) -> bool:
    """Same idea as audit_corpus: enough characters and enough common English words."""
    import re
    common = set("the and of to in for government order orders department dated read following issued with from by "
                 "is are be this that as on at under rules employees pension finance andhra pradesh hereby date no".split())
    words = re.findall(r"[A-Za-z]{3,}", text[:6000])
    hits = sum(w.lower() in common for w in words)
    # short documents (1-3 page gazettes) have few words in all: judge them by the share of common words
    return len(text.strip()) >= 300 and (hits >= 25 or (len(words) >= 50 and hits / len(words) >= 0.12))


def targets(only: set[str] | None, scans_too: bool = False, force: bool = False) -> list[dict]:
    out = []
    for mp in sorted((ST / "rule-library").rglob("meta.json")):
        m = json.loads(mp.read_text())
        cid = m.get("canonical_id")
        if only and cid not in only:
            continue
        if m.get("withheld") or m.get("document_missing"):
            continue
        if m.get("ocr_version") == VERSION:
            continue
        pdf = mp.parent / ((m.get("files") or {}).get("original") or "order.pdf")
        if not pdf.exists():
            continue
        try:
            n, head = pages_and_text(pdf)
        except Exception:
            n, head = 0, ""
        ocr = mp.parent / ((m.get("files") or {}).get("ocr") or "ocr.txt")
        old = ocr.read_text(errors="ignore") if ocr.exists() else ""
        reason = None
        if m.get("ocr_status") == "needs_documentai" or m.get("needs_ocr"):
            reason = "marked for Document AI"
        elif not readable(head) and not readable(old[:6000]):
            reason = "no readable text (scan, or unreadable text layer)"
        elif scans_too and len(head.strip()) < 200:
            reason = "scan read only by the archive's OCR (no page/paragraph locations)"
        elif force and only:
            reason = "named with --id --force (the sandbox could not read it: pages without text or no own reference)"
        if reason and n:
            out.append({"cid": cid, "meta": mp, "pdf": pdf, "pages": n, "reason": reason})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="send to Document AI (default: dry run)")
    ap.add_argument("--limit", type=int, default=0, help="at most N files (0 = all)")
    ap.add_argument("--id", action="append", help="only this canonical ID (repeatable)")
    ap.add_argument("--scans-too", action="store_true",
                    help="also scans that only have the Internet Archive's OCR text (better text + page locations)")
    ap.add_argument("--ids-file", type=Path, help="a file with one canonical ID per line (same as repeating --id)")
    ap.add_argument("--cache-only", action="store_true",
                    help="keep the Document AI response in ocr_cache/ only; ocr.txt and meta.json are NOT changed. "
                         "For PDFs with a readable text layer whose pages also carry an image: the backend sends "
                         "such pages to OCR, the corpus's own text stays as collected (14 Nov 2026)")
    ap.add_argument("--force", action="store_true",
                    help="with --id: read the named files even if their text layer looks readable")
    ap.add_argument("--project", default="use-case-24-project")
    ap.add_argument("--location", default="asia-south1")
    ap.add_argument("--processor", default="93ce7a373c394aed")
    ap.add_argument("--version", default=VERSION)
    a = ap.parse_args()
    if a.version != VERSION:
        sys.exit(f"--version must be {VERSION} (ADR-0017 pin); change the pin by decision first")

    ids = set(a.id or [])
    if a.ids_file:
        ids |= {x.strip() for x in a.ids_file.expanduser().read_text().splitlines() if x.strip()}
    if (a.force or a.cache_only) and not ids:
        sys.exit("--force / --cache-only need --id or --ids-file (they never widen a full run)")
    todo = targets(ids or None, a.scans_too, a.force or a.cache_only)
    if a.cache_only:   # a file already read in full has its response cached: nothing to send
        cached = ST / "ocr_cache" / "documentai" / a.version
        todo = [t for t in todo
                if not (cached / f"{hashlib.sha256(t['pdf'].read_bytes()).hexdigest()}-p1.json").exists()]
    if a.limit:
        todo = todo[: a.limit]
    pages = sum(t["pages"] for t in todo)
    cost = max(0, pages - FREE_PAGES) / 1000 * PRICE_PER_1000
    by = {}
    for t in todo:
        k = "gazette" if t["cid"].startswith("AP-GAZ") else "G.O."
        by[k] = by.get(k, 0) + 1
    print(f"{len(todo)} files, {pages} pages ({by}); at most ~US${pages / 1000 * PRICE_PER_1000:.2f} at list price "
          f"(~US${cost:.2f} if this month's first {FREE_PAGES} free pages are unused)")
    for t in todo[:15]:
        print(f"   {t['cid']:<34} {t['pages']:>3} p  {t['reason']}")
    if len(todo) > 15:
        print(f"   … {len(todo) - 15} more")
    if not a.apply:
        print("dry run — nothing sent. Add --apply (with --limit 3 to test).")
        return

    from app.ingestion.ocr import DocumentAiOcr, OcrError, parse_document  # backend, gcp extra

    # Fail fast on expired sign-in: otherwise the SDK keeps retrying "Reauthentication is needed" (looks like a hang)
    try:
        import google.auth
        import google.auth.transport.requests
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds.refresh(google.auth.transport.requests.Request())
    except Exception as e:
        sys.exit(f"Google sign-in not usable ({type(e).__name__}). Run: gcloud auth application-default login")

    eng = DocumentAiOcr(a.project, a.location, a.processor, processor_version=a.version)
    cache = ST / "ocr_cache" / "documentai" / a.version
    cache.mkdir(parents=True, exist_ok=True)
    errors = done = 0
    for t in todo:
        data = t["pdf"].read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        texts, confs, unconfirmed = [], [], []
        try:
            for first in range(1, t["pages"] + 1, CHUNK):
                pg = list(range(first, min(first + CHUNK, t["pages"] + 1)))
                cf = cache / f"{sha}-p{first}.json"
                if cf.exists():
                    raw = json.loads(cf.read_text())
                else:
                    print(f"   … {t['cid']} pages {pg[0]}-{pg[-1]}: sending", flush=True)
                    raw = eng.raw(data, "application/pdf", pg)
                    for page in raw.get("pages") or []:
                        page.pop("image", None)   # page images: ~1 MB each, the PDF itself is kept (as CachingOcr does)
                    cf.write_text(json.dumps(raw))
                res = parse_document(raw, eng.name, pg)
                for n in pg:
                    p = res.page(n)
                    texts.append(p.text if p else "")
                    if p and p.confidence is not None:
                        confs.append(p.confidence)
                    else:
                        unconfirmed.append(n)
            errors = 0
        except OcrError as e:
            errors += 1
            print(f"!! {t['cid']}: {e}")
            if errors >= 3:
                sys.exit("3 errors in a row — stopping (re-run later: finished files and cached chunks are kept)")
            continue
        if a.cache_only:
            done += 1
            print(f"   ok {t['cid']:<34} {t['pages']:>3} p  cached only"
                  f"{'  unconfirmed pages ' + str(unconfirmed) if unconfirmed else ''}")
            continue
        folder = t["meta"].parent
        m = json.loads(t["meta"].read_text())
        ocr = folder / "ocr.txt"
        if ocr.exists() and not (folder / "ocr.archive.txt").exists():
            ocr.rename(folder / "ocr.archive.txt")
        ocr.write_text("\f".join(texts))
        m.setdefault("files", {})["ocr"] = "ocr.txt"
        m.update({"ocr_source": f"Document AI Enterprise OCR ({a.location})", "ocr_version": a.version,
                  "ocr_pages": t["pages"], "ocr_confidence": round(sum(confs) / len(confs), 3) if confs else None,
                  "ocr_pages_unconfirmed": unconfirmed, "ocr_at": now(), "ocr_status": "done", "needs_ocr": False})
        write_json(t["meta"], m)
        done += 1
        print(f"   ok {t['cid']:<34} {t['pages']:>3} p  confidence {m['ocr_confidence']}"
              f"{'  unconfirmed pages ' + str(unconfirmed) if unconfirmed else ''}")
    print(f"done {done} of {len(todo)}. Next: extract_relations.py staging, audit_corpus.py, reconcile_dates.py")


if __name__ == "__main__":
    main()
