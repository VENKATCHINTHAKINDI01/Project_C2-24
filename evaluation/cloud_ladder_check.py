"""Do the cloud rungs give the same answers as the reference? (plan §3.2, §5.2; milestone M3)

Reads the graph build's files from the artifacts bucket, builds the in-memory reference from
them, then asks the SAME questions of BigQuery (L0 exact, L1 filter, L2 search when
C2_EMBEDDING_MODEL is set) and of the graph in Cloud SQL (L3 walk), under several officer
scopes, and compares answer by answer.

    cd backend
    C2_GCP_PROJECT_ID=<project> C2_GCP_REGION=asia-south1 \\
      env -u VIRTUAL_ENV uv run python ../evaluation/cloud_ladder_check.py \\
      --sql-user <your gcloud account e-mail> [--sample 150]

Needs your gcloud login + Application Default Credentials. Read-only: a few hundred small
BigQuery queries (well inside the free tier) and Cloud SQL reads with your IAM login.
The corpus in the cloud is public orders only, so every scope sees the same records here; what
this proves is that the fixed templates run on the real services and agree with the reference.
Scope differences are proved on set v2 (`leakage_v2.py`) and by the contract tests.
Writes evaluation/reports/<date>-cloud-ladder-check.md. Exit 1 on any difference.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.auth.models import DocumentAccessTags, Scope  # noqa: E402
from app.config import get_settings, load_classification  # noqa: E402
from app.graph.postgres import PostgresGraphRepository  # noqa: E402
from app.graph.repository import (  # noqa: E402
    Direction,
    EdgeKind,
    GraphEdge,
    GraphNode,
    InMemoryGraphRepository,
)
from app.pg import pg_from_settings  # noqa: E402
from app.retrieval.bigquery_index import (  # noqa: E402
    BigQueryRunner,
    BigQueryScopedIndex,
    _doc,
    table_rows,
)
from app.retrieval.scoped import InMemoryScopedIndex, L1Criteria  # noqa: E402

REPORTS = ROOT / "evaluation" / "reports"
# Questions no public order answers (off-domain): their best score shows what "nothing relevant"
# looks like. Written for this check; not a golden set.
OFF_DOMAIN = (
    "recipe for mango pickle with mustard seeds",
    "final score of the cricket world cup",
    "how to repair a car gearbox",
    "intraday stock trading strategy",
    "timeline of the moon landing mission",
    "python programming tutorial for beginners",
    "football transfer news this week",
    "guitar chord progressions for pop songs",
    "best wedding photography packages",
    "how to train a puppy to sit",
)


def l2_calibration(
    l2: Any, passages: list[dict[str, Any]], sc: Scope, rng: random.Random
) -> list[str]:
    """Evidence for the L2 threshold (`C2_L2_CLOUD_MIN_SCORE`) — a PROPOSAL in the report, never
    written to config (CLAUDE.md §9.4). Known-item questions: twelve words copied from the
    middle of an order's second passage, so the order is the right answer; being copied text they
    are easier than an officer's own words, so read the recall as an upper bound. Off-domain
    questions: no order is the right answer."""
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for r in passages:
        by_doc.setdefault(r["canonical_id"], []).append(r)
    pool = sorted(c for c, ps in by_doc.items() if len(ps) >= 2)
    known: list[tuple[str, str]] = []
    for cid in rng.sample(pool, min(40, len(pool))):
        words = [
            w
            for w in re.split(
                r"[^\w]+", sorted(by_doc[cid], key=lambda r: r["passage_no"])[1]["text"]
            )
            if w
        ]
        if len(words) >= 20:
            mid = len(words) // 2 - 6
            known.append((cid, " ".join(words[mid : mid + 12]).lower()))
    ranks, pos, neg = [], [], []
    for cid, q in known:
        hits = l2.search(q, sc, 10)
        ids = [h.doc.canonical_id for h in hits]
        ranks.append(ids.index(cid) + 1 if cid in ids else None)
        pos.append(hits[0].score if hits else 0.0)
    for q in OFF_DOMAIN:
        hits = l2.search(q, sc, 10)
        neg.append(hits[0].score if hits else 0.0)
    if not known:
        return [
            "",
            "## L2 threshold evidence",
            "",
            "No order with two passages: nothing to measure.",
        ]
    at1 = sum(r == 1 for r in ranks) / len(ranks)
    at10 = sum(r is not None for r in ranks) / len(ranks)
    pos_s = sorted(pos)
    p10 = pos_s[max(0, int(0.1 * len(pos_s)) - 1)]
    worst_neg = max(neg)
    out = [
        "",
        "## L2 threshold evidence (proposal only — not applied)",
        "",
        f"Known-item questions: {len(known)} (twelve words copied from an order; an upper bound). "
        f"Recall@1 {at1:.2f}, recall@10 {at10:.2f}.",
        f"Best score — known-item: min {pos_s[0]:.3f}, 10th percentile {p10:.3f}, "
        f"median {pos_s[len(pos_s) // 2]:.3f}; off-domain ({len(neg)}): max {worst_neg:.3f}, "
        f"median {sorted(neg)[len(neg) // 2]:.3f}.",
    ]
    if p10 > worst_neg:
        prop = round((p10 + worst_neg) / 2, 3)
        out.append(
            f"Separation found: a threshold of **{prop}** sits between the worst off-domain score "
            f"and the 10th-percentile known-item score. Proposed for `C2_L2_CLOUD_MIN_SCORE`; "
            "needs the owner's approval and a check on officers' own wording before use."
        )
    else:
        out.append(
            "No clean separation: keep `C2_L2_CLOUD_MIN_SCORE` unset (cloud L2 then never ends "
            "the ladder on its own)."
        )
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sample", type=int, default=150, help="records to look up by ID")
    ap.add_argument("--prefix", default="c2")
    ap.add_argument("--skip-graph", action="store_true")
    ap.add_argument("--sql-user", help="your IAM database login (your gcloud account e-mail)")
    a = ap.parse_args()
    s = get_settings()
    if not (s.gcp_project_id and s.gcp_region):
        sys.exit("set C2_GCP_PROJECT_ID and C2_GCP_REGION")
    if not (a.skip_graph or a.sql_user or s.cloudsql_user):
        sys.exit("give --sql-user <your gcloud account e-mail> (or --skip-graph)")
    project, region = s.gcp_project_id, s.gcp_region

    from google.cloud import storage

    bucket = storage.Client(project=project).bucket(f"{project}-{a.prefix}-artifacts")

    def rows(name: str) -> list[dict[str, Any]]:
        text = bucket.blob(f"graph/{name}").download_as_text()
        return [json.loads(x) for x in text.splitlines() if x.strip()]

    nodes, edges = rows("nodes.jsonl"), rows("edges.jsonl")
    docs = [_doc(r) for r in table_rows(nodes)]
    ref = InMemoryScopedIndex(docs)
    bq = BigQueryScopedIndex(
        BigQueryRunner(project, region), f"{project}.{a.prefix}_metadata.documents"
    )
    ranks = {
        lv.name: lv.rank
        for lv in load_classification(s.ontology_dir / "classification.yaml").levels
    }

    def scope(dept: str, wide: bool, rank: int) -> Scope:
        return Scope(
            user_id="check",
            policy_version="check",
            classification_ranks=ranks,
            public_rank=0,
            department=dept,
            max_rank=rank,
            department_wide=wide,
            sections=frozenset(),
            file_nos=frozenset(),
        )

    scopes = {
        "outsider (public only)": scope("NONE", False, 0),
        "FIN01 department-wide": scope("FIN01", True, 2),
        "GAD01 section officer": scope("GAD01", False, 1),
    }
    rng = random.Random(24)  # noqa: S311 — a fixed sample
    ids = [d.canonical_id for d in rng.sample(docs, min(a.sample, len(docs)))]
    ids += [i.split("-D")[0] for i in ids if "-D" in i][:30] + ["AP-FIN01-GOMS-99999-2020"]
    depts = sorted({d.tags.department for d in docs})
    criteria = [L1Criteria()] + [L1Criteria(department=d) for d in depts]
    criteria += [
        L1Criteria(
            department=depts[0], issued_from=dt.date(2020, 1, 1), issued_to=dt.date(2022, 12, 31)
        ),
        L1Criteria(subject_terms=("pension",)),
        L1Criteria(subject_terms=("transfer", "teachers")),
        L1Criteria(doc_types=frozenset({docs[0].doc_type}), issued_from=dt.date(2024, 1, 1)),
    ]
    out: dict[str, dict[str, int]] = {}
    diffs: list[str] = []

    def tally(path: str, same: bool, what: str) -> None:
        t = out.setdefault(path, {"asked": 0, "different": 0})
        t["asked"] += 1
        if not same:
            t["different"] += 1
            diffs.append(f"{path}: {what}")

    for name, sc in scopes.items():
        for cid in ids:
            got = sorted(d.canonical_id for d in bq.exact(cid, sc))
            tally(
                "L0 exact (BigQuery)",
                got == sorted(d.canonical_id for d in ref.exact(cid, sc)),
                f"{name} · {cid}",
            )
        for i, c in enumerate(criteria):
            tally("L1 filter (BigQuery)", bq.filter(c, sc) == ref.filter(c, sc), f"{name} · #{i}")

    if not a.skip_graph:
        mem = InMemoryGraphRepository()
        for n in nodes:
            if n.get("department") and n.get("classification"):
                mem.upsert_node(
                    GraphNode(
                        canonical_id=n["id"],
                        tags=DocumentAccessTags(
                            doc_id=n["id"],
                            department=n["department"],
                            section=n.get("section") or None,
                            classification=n["classification"],
                            file_no=n.get("file_no") or None,
                        ),
                    )
                )
        for e in edges:
            mem.upsert_edge(
                GraphEdge(
                    source=e["from"],
                    kind=EdgeKind(e["relation"]),
                    target=e["to"],
                    confirmed=bool(e["confirmed"]),
                )
            )
        pg = pg_from_settings(
            s.model_copy(
                update={
                    "state_store": "postgres",
                    "cloudsql_user": a.sql_user or s.cloudsql_user,
                    "cloudsql_instance": s.cloudsql_instance
                    or f"{project}:{region}:{a.prefix}-sql",
                }
            )
        )
        assert pg is not None  # noqa: S101
        try:
            cloud = PostgresGraphRepository(pg)
            tally(
                "L3 graph size (Cloud SQL)",
                cloud.counts() == (len(mem.node_ids()), len(mem.edges())),
                f"cloud {cloud.counts()} vs files {(len(mem.node_ids()), len(mem.edges()))}",
            )
            linked = sorted({e["from"] for e in edges})
            for name, sc in scopes.items():
                for cid in rng.sample(linked, min(40, len(linked))):
                    kw: dict[str, Any] = {
                        "kinds": frozenset(EdgeKind),
                        "direction": Direction.BOTH,
                        "max_hops": 2,
                        "include_unconfirmed": True,
                    }
                    tally(
                        "L3 walk, 2 hops (Cloud SQL)",
                        cloud.walk([cid], sc, **kw) == mem.walk([cid], sc, **kw),
                        f"{name} · {cid}",
                    )
        finally:
            pg.close()

    loaded = bucket.blob("graph/passages/loaded.json")
    if s.embedding_model and loaded.exists():
        from app.retrieval.bigquery_l2 import BigQueryHybridRetriever, VertexEmbedder
        from app.retrieval.ladder import _terms

        emb = VertexEmbedder(project, region, s.embedding_model, s.embedding_dimensions)
        l2 = BigQueryHybridRetriever(
            BigQueryRunner(project, region), f"{project}.{a.prefix}_metadata.passages", emb
        )
        parts = json.loads(loaded.download_as_text())["parts"]
        passages = [r for p in parts for r in rows(f"passages/{p}")]
        tags = {d.canonical_id: d.tags for d in docs}
        questions = [
            "revision of pension and dearness relief",
            "transfer of teachers and rationalisation of posts",
            "earned leave encashment on retirement",
            "delegation of financial powers to heads of departments",
            "appointment on compassionate grounds",
            "ఉపాధ్యాయుల బదిలీలు",
        ]
        for name, sc in scopes.items():
            for q in questions:
                qv, terms = emb.embed_query(q), sorted(set(_terms(q)))
                best: dict[str, float] = {}
                for r in passages:
                    if r["canonical_id"] not in tags or not sc.admits(tags[r["canonical_id"]]):
                        continue
                    v = r["embedding"]
                    cos = sum(x * y for x, y in zip(qv, v, strict=True)) / (
                        (sum(x * x for x in qv) ** 0.5) * (sum(y * y for y in v) ** 0.5) or 1.0
                    )
                    hits = sum(t in r["text"].lower() for t in terms)
                    score = 0.7 * cos + 0.3 * hits / max(1, len(terms))
                    best[r["canonical_id"]] = max(best.get(r["canonical_id"], -1.0), score)
                want = sorted(best.items(), key=lambda x: (-round(x[1], 4), x[0]))[:10]
                got = [(h.doc.canonical_id, h.score) for h in l2.search(q, sc, 10)]
                got.sort(key=lambda x: (-round(x[1], 4), x[0]))
                tally(
                    "L2 meaning + keywords, top 10 (BigQuery)",
                    [c for c, _ in got] == [c for c, _ in want],
                    f"{name} · {q[:40]}",
                )
        calib = l2_calibration(l2, passages, scopes["outsider (public only)"], rng)
    else:
        print("L2 not checked: set C2_EMBEDDING_MODEL and build the passages table first")
        calib = []

    total = sum(t["different"] for t in out.values())
    day = dt.date.today().isoformat()
    md = [
        f"# Cloud rungs against the reference — {day}",
        "",
        f"Project `{project}`, region `{region}`. {len(docs)} documents, {len(edges)} relations "
        "(public orders). Scopes: " + "; ".join(scopes) + ".",
        "",
        "| Path | Asked | Different |",
        "|---|---:|---:|",
    ]
    md += [f"| {k} | {v['asked']} | {v['different']} |" for k, v in out.items()]
    md += ["", f"**{'SAME on every question' if total == 0 else f'{total} DIFFERENCES'}**"]
    md += [f"- {d}" for d in diffs[:40]]
    md += calib
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / f"{day}-cloud-ladder-check.md").write_text("\n".join(md) + "\n", "utf-8")
    print("\n".join(md[4:]))
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
