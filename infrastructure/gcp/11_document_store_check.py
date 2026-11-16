"""Live check of the GCS document store (ADR-0014 rule 7), run from backend/ with the gcp extra:

    env -u VIRTUAL_ENV uv run python ../infrastructure/gcp/11_document_store_check.py

Starts the sandbox app with C2_DOCUMENT_STORE=gcs, so ingestion writes the SYNTHETIC corpus's
indexed files to gs://<project>-c2-raw/synthetic/mock_v1/sources/ (written once per version, never
overwritten). Then, through the normal access-checked API, it previews one order as an allowed
officer and compares the bytes with the corpus file. It also confirms that a hidden document still
gives 404. Read-only apart from those uploads.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("C2_DOCUMENT_STORE", "gcs")
os.environ.setdefault("C2_GCS_RAW_BUCKET", "use-case-24-project-c2-raw")

from fastapi.testclient import TestClient  # noqa: E402
from google.cloud import storage  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

settings = Settings(sandbox=True)
app = create_app(settings)
cid, corpus_file = "AP-FIN01-GOMS-88-2022", ROOT / "data/synthetic/mock_v1/documents/01_Finance_HR"
with TestClient(app) as c:
    r = c.get(f"/assist/documents/{cid}/preview", headers={"X-Sandbox-User": "U01"})
    local = next(corpus_file.glob("D03_*"))
    print(f"preview {cid} as U01: HTTP {r.status_code}, {len(r.content)} bytes, "
          f"identical to corpus file: {r.content == local.read_bytes()}")
    h = c.get("/assist/documents/AP-USD01-RPT-USD0131-9-2025/preview", headers={"X-Sandbox-User": "U05"})
    print(f"hidden document for U05: HTTP {h.status_code} (expected 404)")

blobs = list(storage.Client().list_blobs(settings.gcs_raw_bucket, prefix=settings.gcs_documents_prefix + "/"))
print(f"objects under gs://{settings.gcs_raw_bucket}/{settings.gcs_documents_prefix}/: {len(blobs)}")
for b in blobs[:3]:
    print("  ", b.name, b.content_type, b.size)
