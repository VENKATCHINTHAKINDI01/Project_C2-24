"""Which text-embedding models answer in the project's region? (rung L2, ADR-0026)

Run from backend/ (a handful of tiny requests; a few paise at most):

    env -u VIRTUAL_ENV uv run python ../infrastructure/gcp/17_embedding_check.py
    env -u VIRTUAL_ENV uv run python ../infrastructure/gcp/17_embedding_check.py --model <name> ...

For each candidate it asks, in the region from config.env and never the global endpoint, for the
embedding of one English and one Telugu sentence, and prints whether the model answered, the
vector size, and how close the two sentences (same meaning) are. Pick a model that answers and
pass it to the build job: EMBEDDING_MODEL=<name> APPLY=1 RUN=1 ./14_graph_job.sh
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))
_spec = importlib.util.spec_from_file_location("schema12", HERE / "12_cloudsql_schema.py")
assert _spec and _spec.loader
kit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kit)

CANDIDATES = ["gemini-embedding-001", "text-multilingual-embedding-002", "text-embedding-005"]
ENGLISH = "Earned leave may be accumulated up to three hundred days."
TELUGU = "ఆర్జిత సెలవును మూడు వందల రోజుల వరకు నిల్వ చేసుకోవచ్చు."
OTHER = "The district collector shall conduct the tender for the drain works."


def cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1.0
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append")
    ap.add_argument("--dimensions", type=int, default=768)
    a = ap.parse_args()
    cfg = kit.config()
    from app.retrieval.bigquery_l2 import EmbeddingError, VertexEmbedder

    print(f"project {cfg['PROJECT_ID']}, region {cfg['REGION']}, {a.dimensions} dimensions")
    for model in a.model or CANDIDATES:
        try:
            e = VertexEmbedder(cfg["PROJECT_ID"], cfg["REGION"], model, a.dimensions)
            en, te, other = e.embed_documents([ENGLISH, TELUGU, OTHER])
            q = e.embed_query("how many days of earned leave can be accumulated")
            print(
                f"  OK   {model}: question~English {cos(q, en):.2f}, question~Telugu "
                f"{cos(q, te):.2f}, question~unrelated {cos(q, other):.2f}"
            )
        except EmbeddingError as exc:
            cause = exc.__cause__
            print(f"  no   {model}: {exc} {str(cause)[:160] if cause else ''}")


if __name__ == "__main__":
    main()
