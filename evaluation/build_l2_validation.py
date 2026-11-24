"""Build the L2 calibration set from the public G.O. corpus (ADR-0061 addendum, 24 Nov 2026).

Known-item questions: each query is an order's own subject with its number, date, department and
bracketed references removed, and the relevant record is that order. Labels therefore come from
the corpus itself (no invented IDs). Gazette republications of the same order are listed as
relevant too, so finding either copy counts. A deterministic sample (`--seed`) is drawn per
department so no department dominates.

Usage (from the repo root; reads the corpus folder, or the zip of it):
    python3 evaluation/build_l2_validation.py --corpus ~/Documents/c2-24-corpus/staging \\
        --n 150 --user V14 --out evaluation/data/l2_validation_known_item.json
    python3 evaluation/build_l2_validation.py \\
        --zip ~/Documents/c2-24-corpus-archive/c2-24-corpus.zip …

Limits (stated in the dataset): known-item queries measure "is the top hit the order the words
come from", the question L2 early exit has to answer; they do not include questions with no
answer in the corpus, so the false-exit rate counts wrong top hits only.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any

_NOISE = re.compile(
    r"\[[^\]]*\]|\([^)]*\)|\bG\.?\s*O\.?\s*(?:\(?(?:Ms|Rt|P)\)?\.?)?\s*No\.?\s*[\w./-]+"
    r"|\b(?:dated?|dt)\s*[:.]?\s*[\d./-]+|\b\d{1,2}[-./]\d{1,2}[-./]\d{2,4}\b|\bNo\.\s*[\w/-]+",
    re.I,
)
_TAIL = re.compile(r"(?:[\s,.:;–-]+|\b(?:orders?|issued|reg|regarding|sanctioned)\b)+$", re.I)
MIN_WORDS = 5


def _metas(corpus: Path | None, zpath: Path | None) -> Iterator[dict[str, Any]]:
    if corpus is not None:
        for p in sorted((corpus / "rule-library").rglob("meta.json")):
            yield json.loads(p.read_text("utf-8"))
        return
    assert zpath is not None
    with zipfile.ZipFile(zpath) as z:
        for n in sorted(z.namelist()):
            if "/rule-library/" in n and n.endswith("/meta.json") and "__MACOSX" not in n:
                yield json.loads(z.read(n))


def query_of(subject: str) -> str:
    q = subject
    for _ in range(3):
        q = _NOISE.sub(" ", q)
    q = re.sub(r"\s+", " ", q)
    while (t := _TAIL.sub("", q)) != q:  # trailing "– Orders – Issued", separators
        q = t
    return q.strip(" .,:;–-")


def build(metas: list[dict[str, Any]], *, n: int, user: str, seed: int) -> dict[str, Any]:
    by_id = {m["canonical_id"]: m for m in metas if m.get("canonical_id")}
    copies: dict[str, set[str]] = defaultdict(set)  # an order and its Gazette republications
    for m in metas:
        rid = m.get("republishes_id")
        if rid and rid != "None" and rid in by_id:
            copies[rid].add(m["canonical_id"])
            copies[m["canonical_id"]].add(rid)
    pool: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for cid, m in by_id.items():
        if m.get("classification") != "UNCLASSIFIED" or m.get("department_code") == "GAZ":
            continue  # public orders only; a Gazette copy is never the item itself
        q = query_of(str(m.get("subject") or ""))
        if len(q.split()) >= MIN_WORDS:
            pool[str(m.get("department_code"))].append((cid, q))
    rng = random.Random(seed)  # noqa: S311 — a reproducible sample, not security
    depts = sorted(pool)
    for d in depts:
        rng.shuffle(pool[d])
    chosen: list[tuple[str, str]] = []
    while len(chosen) < n and any(pool[d] for d in depts):
        for d in depts:
            if pool[d] and len(chosen) < n:
                chosen.append(pool[d].pop())
    return {
        "version": f"known-item-s{seed}-n{len(chosen)}",
        "description": (
            "Known-item queries from public order subjects (number, date and references removed); "
            "relevant = that order and its Gazette copies. No no-answer questions: false exits "
            "count wrong top hits only."
        ),
        "queries": [
            {
                "id": f"KI-{i + 1:03d}",
                "query": q,
                "user_id": user,
                "relevant_canonical_ids": sorted({cid, *copies.get(cid, set())}),
                "distractor_canonical_ids": [],
                "expected_l2_termination": True,
                "category": by_id[cid].get("department_code", "?"),
            }
            for i, (cid, q) in enumerate(chosen)
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--corpus", type=Path, help="the corpus staging/ folder")
    src.add_argument("--zip", type=Path, help="the zip of the corpus folder")
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--user", default="V14", help="a sandbox v2 officer (public orders: any)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    data = build(list(_metas(a.corpus, a.zip)), n=a.n, user=a.user, seed=a.seed)
    a.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"{len(data['queries'])} queries → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
