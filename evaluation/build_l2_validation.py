"""Build the L2 calibration set, and its family-disjoint holdout, from the public G.O. corpus
(ADR-0061 addendum, 24 Nov 2026). One script for both sets (merged 24 Nov with the former
`build_l2_holdout.py`), so both use the same query cleaning and the same corpus reading.

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
    # only orders loaded in the cloud index (needs gcloud and the gcp extra):
    … --filter-bq
    # the holdout: no order from the calibration set, nor any order in its amendment /
    # supersession / republication family; one query per family; balanced by department
    … --holdout-of evaluation/data/l2_validation_known_item.json --n 100 --seed 42 \\
        --out evaluation/data/l2_holdout_dataset.json

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


def _relations(corpus: Path | None, zpath: Path | None) -> Iterator[dict[str, Any]]:
    """The corpus relation manifest (AMENDS / SUPERSEDES / REPEALS …)."""
    if corpus is not None:
        lines = (corpus / "manifests" / "relations.jsonl").read_text("utf-8").splitlines()
    else:
        assert zpath is not None
        with zipfile.ZipFile(zpath) as z:
            name = next(
                n
                for n in z.namelist()
                if n.endswith("manifests/relations.jsonl") and "__MACOSX" not in n
            )
            lines = z.read(name).decode("utf-8").splitlines()
    for line in lines:
        if line.strip():
            yield json.loads(line)


def bigquery_ids() -> set[str]:
    """Canonical IDs loaded in the cloud index. Fails loudly: a fallback would change the set."""
    import subprocess  # noqa: PLC0415 — only for --filter-bq / --holdout-of

    import google.oauth2.credentials  # noqa: PLC0415
    from google.cloud import bigquery  # noqa: PLC0415

    cmd = ["gcloud", "auth", "print-access-token"]
    token = subprocess.check_output(cmd).decode().strip()  # noqa: S603
    client = bigquery.Client(
        project="use-case-24-project",
        location="asia-south1",
        credentials=google.oauth2.credentials.Credentials(token=token),  # type: ignore[no-untyped-call,unused-ignore]
    )
    rows = client.query(
        "SELECT canonical_id FROM `use-case-24-project.c2_metadata.documents`"
    ).result()
    return {r.canonical_id for r in rows}


def in_index(metas: list[dict[str, Any]], ids: set[str]) -> list[dict[str, Any]]:
    """Keep orders present in the index; a republication of a missing order is no longer a copy."""
    kept = [dict(m) for m in metas if m.get("canonical_id") in ids]
    for m in kept:
        if m.get("republishes_id") not in ids:
            m["republishes_id"] = None
    return kept


def query_of(subject: str) -> str:
    q = subject
    for _ in range(3):
        q = _NOISE.sub(" ", q)
    q = re.sub(r"\s+", " ", q)
    while (t := _TAIL.sub("", q)) != q:  # trailing "– Orders – Issued", separators
        q = t
    return q.strip(" .,:;–-")


def _balanced(pool: dict[str, list[tuple[str, str]]], n: int, seed: int) -> list[tuple[str, str]]:
    """A reproducible sample, taken from each department in turn so none dominates."""
    rng = random.Random(seed)  # noqa: S311 — a reproducible sample, not security
    depts = sorted(pool)
    for d in depts:
        rng.shuffle(pool[d])
    chosen: list[tuple[str, str]] = []
    while len(chosen) < n and any(pool[d] for d in depts):
        for d in depts:
            if pool[d] and len(chosen) < n:
                chosen.append(pool[d].pop())
    return chosen


def build(
    metas: list[dict[str, Any]],
    *,
    n: int,
    user: str,
    seed: int,
    exclude: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Known-item set; `exclude` = orders that may not be an item (e.g. another set's families)."""
    by_id = {m["canonical_id"]: m for m in metas if m.get("canonical_id")}
    copies: dict[str, set[str]] = defaultdict(set)  # an order and its Gazette republications
    for m in metas:
        rid = m.get("republishes_id")
        if rid and rid != "None" and rid in by_id:
            copies[rid].add(m["canonical_id"])
            copies[m["canonical_id"]].add(rid)
    pool: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for cid, m in by_id.items():
        if (
            m.get("classification") != "UNCLASSIFIED"
            or m.get("department_code") == "GAZ"
            or cid in exclude
        ):
            continue  # public orders only; a Gazette copy is never the item itself
        q = query_of(str(m.get("subject") or ""))
        if len(q.split()) >= MIN_WORDS:
            pool[str(m.get("department_code"))].append((cid, q))
    chosen = _balanced(pool, n, seed)
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


def _component(start: str, adj: dict[str, set[str]], within: set[str] | None = None) -> set[str]:
    seen, todo = {start}, [start]
    while todo:
        for v in adj.get(todo.pop(), set()):
            if v not in seen and (within is None or v in within):
                seen.add(v)
                todo.append(v)
    return seen


def build_holdout(
    metas: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    calibration: dict[str, Any],
    *,
    n: int,
    user: str,
    seed: int,
) -> dict[str, Any]:
    """Family-disjoint holdout: no calibration order, nor any order in the same amendment /
    supersession / repeal / republication family as one; one query per family; balanced by
    department; the disjointness is asserted on the result."""
    by_id = {m["canonical_id"]: m for m in metas if m.get("canonical_id")}
    adj: dict[str, set[str]] = defaultdict(set)
    copies: dict[str, set[str]] = defaultdict(set)
    for cid, m in by_id.items():
        rid = m.get("republishes_id")
        if rid and rid != "None" and rid in by_id:
            for a, b in ((cid, rid), (rid, cid)):
                adj[a].add(b)
                copies[a].add(b)
    for r in relations:
        u, v = str(r.get("from") or ""), str(r.get("to") or "")
        if r.get("type") in ("AMENDS", "SUPERSEDES", "REPEALS") and u in by_id and v in by_id:
            adj[u].add(v)
            adj[v].add(u)
    excluded: set[str] = set()
    for q in calibration["queries"]:
        for cid in q["relevant_canonical_ids"]:
            if cid not in excluded:
                excluded |= _component(cid, adj)
    eligible = {
        cid
        for cid, m in by_id.items()
        if cid not in excluded
        and m.get("classification") == "UNCLASSIFIED"
        and m.get("department_code") != "GAZ"
    }
    pool: dict[str, list[tuple[str, str]]] = defaultdict(list)
    done: set[str] = set()
    for cid in by_id:  # corpus order, so a seed reproduces the same set
        if cid not in eligible or cid in done:
            continue
        family = _component(cid, adj, within=set(by_id))
        done |= family
        for member in sorted(family):  # the family's first order with a usable subject
            m = by_id[member]
            q = query_of(str(m.get("subject") or ""))
            if m.get("department_code") != "GAZ" and len(q.split()) >= MIN_WORDS:
                pool[str(m.get("department_code"))].append((member, q))
                break
    chosen = _balanced(pool, n, seed)
    queries = [
        {
            "id": f"HO-{i + 1:03d}",
            "query": q,
            "user_id": user,
            "relevant_canonical_ids": sorted({cid, *copies.get(cid, set())}),
            "distractor_canonical_ids": [],
            "expected_l2_termination": True,
            "category": by_id[cid].get("department_code", "?"),
            "family_root_id": cid,
        }
        for i, (cid, q) in enumerate(chosen)
    ]
    overlap = {c for q in queries for c in q["relevant_canonical_ids"]} & excluded
    assert not overlap, f"holdout overlaps calibration families: {sorted(overlap)}"
    return {
        "version": f"holdout-family-disjoint-s{seed}-n{len(queries)}",
        "description": (
            f"Family-disjoint holdout ({len(queries)} queries): no calibration order, nor any "
            "order in its amendment / supersession / repeal / republication family."
        ),
        "queries": queries,
    }


def family_graph(
    metas: list[dict[str, Any]], relations: list[dict[str, Any]]
) -> dict[str, set[str]]:
    """Orders linked by AMENDS / SUPERSEDES / REPEALS or republication, both ways."""
    ids = {m["canonical_id"] for m in metas if m.get("canonical_id")}
    adj: dict[str, set[str]] = defaultdict(set)
    for m in metas:
        rid = m.get("republishes_id")
        if m.get("canonical_id") and rid and rid != "None" and rid in ids:
            adj[m["canonical_id"]].add(rid)
            adj[rid].add(m["canonical_id"])
    for r in relations:
        u, v = str(r.get("from") or ""), str(r.get("to") or "")
        if r.get("type") in ("AMENDS", "SUPERSEDES", "REPEALS") and u in ids and v in ids:
            adj[u].add(v)
            adj[v].add(u)
    return adj


def families_of(datasets: list[dict[str, Any]], adj: dict[str, set[str]]) -> frozenset[str]:
    """Every order in the family of an order these datasets name."""
    out: set[str] = set()
    for d in datasets:
        for q in d["queries"]:
            for cid in q["relevant_canonical_ids"]:
                if cid not in out:
                    out |= _component(cid, adj)
    return frozenset(out)


def no_answer(
    all_metas: list[dict[str, Any]],
    adj: dict[str, set[str]],
    index: set[str],
    *,
    n: int,
    user: str,
    seed: int,
) -> list[dict[str, Any]]:
    """Questions whose answer is not in the index: subjects of public orders that are not loaded,
    with no order of their family loaded either. Any early exit on them is a wrong exit, so they
    measure what known-item questions cannot (a near-duplicate order taken for the answer)."""
    dept = {
        m["canonical_id"]: str(m.get("department_code")) for m in all_metas if m.get("canonical_id")
    }
    pool: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for m in all_metas:
        cid = m.get("canonical_id")
        if (
            not cid
            or cid in index
            or m.get("classification") != "UNCLASSIFIED"
            or m.get("department_code") == "GAZ"
            or _component(cid, adj) & index
        ):
            continue
        q = query_of(str(m.get("subject") or ""))
        if len(q.split()) >= MIN_WORDS:
            pool[dept[cid]].append((cid, q))
    return [
        {
            "id": f"NA-{i + 1:03d}",
            "query": q,
            "user_id": user,
            "relevant_canonical_ids": [],
            "distractor_canonical_ids": [],
            "expected_l2_termination": False,
            "category": dept[cid],
            "source_not_loaded": cid,
        }
        for i, (cid, q) in enumerate(_balanced(pool, n, seed))
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--corpus", type=Path, help="the corpus staging/ folder")
    src.add_argument("--zip", type=Path, help="the zip of the corpus folder")
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--user", default="U01", help="a sandbox officer (public orders: any)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument(
        "--filter-bq",
        action="store_true",
        help="only orders loaded in BigQuery c2_metadata.documents (always on with --holdout-of)",
    )
    ap.add_argument(
        "--holdout-of",
        type=Path,
        metavar="CALIBRATION_JSON",
        help="build the family-disjoint holdout of this calibration set instead",
    )
    ap.add_argument(
        "--exclude-families-of",
        type=Path,
        action="append",
        default=[],
        metavar="DATASET_JSON",
        help="keep this set clear of the families of the orders that dataset names",
    )
    ap.add_argument(
        "--no-answer",
        type=int,
        default=0,
        metavar="K",
        help="add K questions whose answer is not in the cloud index (needs BigQuery)",
    )
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    all_metas = list(_metas(a.corpus, a.zip))
    metas, index = all_metas, set[str]()
    if a.filter_bq or a.holdout_of or a.no_answer:
        index = bigquery_ids()
        metas = in_index(all_metas, index)
        print(f"{len(metas)} orders are in the cloud index")
    needs_relations = a.holdout_of or a.exclude_families_of or a.no_answer
    relations = list(_relations(a.corpus, a.zip)) if needs_relations else []
    if a.holdout_of:
        data = build_holdout(
            metas,
            relations,
            json.loads(a.holdout_of.read_text("utf-8")),
            n=a.n,
            user=a.user,
            seed=a.seed,
        )
    else:
        others = [json.loads(p.read_text("utf-8")) for p in a.exclude_families_of]
        exclude = families_of(others, family_graph(metas, relations))
        data = build(metas, n=a.n, user=a.user, seed=a.seed, exclude=exclude)
        if exclude:
            names = ", ".join(p.name for p in a.exclude_families_of)
            data["description"] += f" Clear of the order families in {names}."
        if a.no_answer:
            adj = family_graph(all_metas, relations)
            na = no_answer(all_metas, adj, index, n=a.no_answer, user=a.user, seed=a.seed)
            data["queries"] += na
            data["version"] += f"-na{len(na)}"
            data["description"] = data["description"].replace(
                "No no-answer questions: false exits count wrong top hits only.",
                f"Plus {len(na)} questions whose answer is not in the index (any exit is wrong).",
            )
    a.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", "utf-8")
    print(f"{len(data['queries'])} queries → {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
