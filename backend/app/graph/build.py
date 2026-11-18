"""Build the knowledge graph of the public corpus by running every order through the NORMAL
ingestion pipeline (plan §4, §3.6; milestone M2 at corpus scale).

    cd backend
    env -u VIRTUAL_ENV uv run python -m app.graph.build --public-dir ~/Documents/c2-24-corpus
        [--limit N] [--out DIR] [--load-postgres] [--load-bigquery P.D.T]
    … --staging-dir /mnt/raw/public-go --out /mnt/artifacts/graph --load-postgres   (Cloud Run Job)

`<staging>` is `<public-dir>/staging`, or the folder given with --staging-dir.

Reads `<staging>/rule-library/**/meta.json` only for the source-system tags (department,
section, classification) and the file path; IDs, dates, types and links all come from the pipeline's
own reading of the file. Scans replay the Document AI readings already paid for
(`<staging>/ocr_recorded/…`, joined by data_collection/tools/join_ocr_cache.py --all); nothing is
sent to GCP and nothing is billed. Orders are ingested oldest first, so supersession is reconciled
in the order it happened.

Writes to `<staging>/graph/` unless --out is given (outside the repository):
  nodes.jsonl    one indexed order: id, type, hierarchy level, department, section, dates, subject
  edges.jsonl    one relation: from, relation, to, confirmed (store-agnostic schema, plan §3.6)
  held.jsonl     files the pipeline did not index, with the reason (IDs and reasons only)
  report.md      counts, and how the pipeline's reading compares with the collection metadata
  passages/      with --load-passages: part-NNNNN.jsonl (passages + embeddings), a .done.json
                 manifest per complete part (resume), loaded.json (the parts in the table)

Public orders only (UNCLASSIFIED); anything else is skipped. SANDBOX values: the OCR auto-pass
threshold is the uncalibrated one from config/sandbox.yaml (labelled in the report).
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import gc
import hashlib
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml

from app.agents.runtime import AssistRuntime
from app.config import get_settings, load_classification, load_hierarchy
from app.connectors.eoffice import SourceArtefact
from app.graph.postgres import PostgresGraphRepository
from app.ingestion.detect import scan_record
from app.ingestion.document_store import StoredDocument
from app.ingestion.ocr import RecordedOcrFiles, version_dir
from app.pg import pg_from_settings
from app.retrieval.bigquery_index import load_table, table_rows
from app.retrieval.bigquery_l2 import VertexEmbedder, load_passages_from_uri, write_passage_parts
from app.retrieval.ladder import LadderConfig

CHANGES = ("SUPERSEDES", "AMENDS", "REPEALS", "CLARIFIES")


class NoDocumentStore:
    """The job keeps no copies of the files (they stay in the data root)."""

    def put(self, doc: StoredDocument) -> None:
        return None

    def get(self, version: str) -> StoredDocument | None:
        return None


def corpus(root: Path) -> list[dict[str, Any]]:
    """Public orders under the staging folder, oldest first (collection date: ordering only)."""
    rows = []
    for mp in (root / "rule-library").rglob("meta.json"):
        m = json.loads(mp.read_text("utf-8"))
        f = mp.parent / ((m.get("files") or {}).get("original") or "order.pdf")
        if m.get("classification") == "UNCLASSIFIED" and f.is_file():
            rows.append({"meta": m, "file": f})
    return sorted(rows, key=lambda r: (str(r["meta"].get("date") or ""), r["meta"]["canonical_id"]))


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--public-dir", type=Path, help="data root; the corpus is in its staging/")
    where.add_argument(
        "--staging-dir",
        type=Path,
        help="the folder that holds rule-library/ itself (the bucket's public-go/ on GCP)",
    )
    ap.add_argument("--limit", type=int, default=0, help="first N orders only (test run)")
    ap.add_argument(
        "--pdf-scans",
        type=Path,
        default=None,
        help="also save each PDF's page reads as <sha256>.json here, so the sandbox service "
        "reads them instead of parsing the same orders at every start (ADR-0028 addendum 2)",
    )
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument(
        "--load-postgres",
        action="store_true",
        help="after the files are written, copy the graph into Postgres / Cloud SQL "
        "(C2_PG_DSN, or C2_CLOUDSQL_INSTANCE + C2_CLOUDSQL_USER)",
    )
    ap.add_argument(
        "--load-spanner",
        action="store_true",
        help="after the files are written, copy the graph into Spanner Graph (ADR-0048): "
        "C2_GCP_PROJECT_ID, C2_SPANNER_INSTANCE, C2_SPANNER_DATABASE. Use instead of "
        "--load-postgres once the API reads Spanner: one graph store is written, not two",
    )
    ap.add_argument(
        "--load-dry-run",
        action="store_true",
        help="with --load-postgres / --load-spanner: report what the load would add, update and "
        "DELETE (links the build no longer produces), and change nothing (ADR-0055)",
    )
    ap.add_argument(
        "--max-delete-share",
        type=float,
        default=0.2,
        help="refuse a load that would delete more than this share of the links or nodes held "
        "(default 0.2); nothing is changed when refused",
    )
    ap.add_argument(
        "--allow-large-delete",
        action="store_true",
        help="load even past --max-delete-share (after checking a dry run)",
    )
    ap.add_argument(
        "--load-bigquery",
        metavar="PROJECT.DATASET.TABLE",
        help="after the files are written, replace this BigQuery table with the documents' "
        "metadata (ladder rungs L0/L1). Needs C2_GCP_PROJECT_ID and C2_GCP_REGION",
    )
    ap.add_argument(
        "--load-passages",
        nargs=2,
        metavar=("PROJECT.DATASET.TABLE", "GS_DIR"),
        help="embed the indexed orders' text as passages (C2_EMBEDDING_MODEL, in region), write "
        "them as resumable part files to <out>/passages/ and replace the BigQuery table from "
        "them; GS_DIR is the gs:// address of <out> (ladder rung L2, ADR-0026)",
    )
    a = ap.parse_args(argv)
    root = (a.staging_dir or a.public_dir / "staging").expanduser()
    out = a.out or root / "graph"
    if a.pdf_scans is not None:
        a.pdf_scans.mkdir(parents=True, exist_ok=True)
    settings = get_settings()
    sandbox_cfg = yaml.safe_load(settings.sandbox_config_path.read_text("utf-8"))
    threshold = (sandbox_cfg.get("ocr") or {}).get("public_auto_pass_min_confidence")
    r = sandbox_cfg["retrieval"]
    as_of = dt.date.today()
    run = AssistRuntime.build(
        [],
        ontology_dir=settings.ontology_dir,
        hierarchy=load_hierarchy(settings.ontology_dir / "hierarchy.yaml"),
        classification=load_classification(settings.ontology_dir / "classification.yaml"),
        cfg=LadderConfig(
            l2_top_k=r["l2_top_k"],
            l2_min_score=r["l2_rerank_min_score"],
            l3_max_hops=r["l3_max_hops"],
        ),
        calibrated=False,
        as_of=as_of,
        received_at=dt.datetime.combine(as_of, dt.time(9), tzinfo=dt.UTC),
        ocr=RecordedOcrFiles(
            [
                version_dir(
                    root / "ocr_recorded" / "documentai", settings.docai_ocr_processor_version
                )
            ],
            "documentai:recorded",
        ),
        documents=NoDocumentStore(),
        public_ocr_auto_pass=threshold,
    )
    rows = corpus(root)[: a.limit or None]
    print(f"{len(rows)} public orders → pipeline (OCR auto-pass {threshold}, uncalibrated)")
    read_as: dict[str, str | None] = {}  # collection ID → the ID the pipeline read
    source_of: dict[str, tuple[str, str]] = {}  # canonical ID read → (path under root, sha256)
    held: list[dict[str, str]] = []
    errors: dict[str, str] = {}
    t0 = time.time()
    for n, row in enumerate(rows, 1):
        m, f = row["meta"], row["file"]
        data = f.read_bytes()
        art = SourceArtefact(
            source_uri="public://" + f.relative_to(root).as_posix(),
            filename=f.name,
            department=m["department_code"],
            section=m.get("section") or "",
            classification="UNCLASSIFIED",
            data=data,
        )
        try:
            res = run._ingest(art, run_received(run, m))  # noqa: SLF001 — the pipeline entry
        except Exception as exc:  # noqa: BLE001 — one unreadable order must not stop the run
            # not indexed (fail closed); the kind of error only, never text from the file
            run.artefacts.pop(art.source_uri, None)
            read_as[m["canonical_id"]] = None
            errors[m["canonical_id"]] = f"pipeline error: {type(exc).__name__}"
            held.append({"collection_id": m["canonical_id"], "status": "error"})
            print(f"  ! {m['canonical_id']}: {type(exc).__name__}", flush=True)
            continue
        if a.pdf_scans is not None and data.startswith(b"%PDF-"):
            try:
                name, rec = scan_record(data)  # already read by detection: no second parse
            except Exception as exc:  # noqa: BLE001 — a missing saved read only costs time
                print(f"  ! no saved read for {m['canonical_id']}: {type(exc).__name__}")
            else:
                target = a.pdf_scans / name
                if not target.exists():
                    target.write_text(json.dumps(rec, ensure_ascii=False), "utf-8")
        run.artefacts.pop(art.source_uri, None)  # do not keep the bytes
        run.stores.ocr_drafts.pop(res.version, None)  # release fine-grained OCR geometry
        read_as[m["canonical_id"]] = res.canonical_id if res.status.value == "indexed" else None
        if res.status.value == "indexed" and res.canonical_id:
            source_of[res.canonical_id] = (
                f.relative_to(root).as_posix(),
                hashlib.sha256(data).hexdigest(),
            )
        if res.status.value != "indexed":
            held.append({"collection_id": m["canonical_id"], "status": res.status.value})
        if n % 50 == 0 or n == len(rows):
            print(f"  {n}/{len(rows)}  indexed {run.indexed}  {time.time() - t0:.0f}s", flush=True)
            gc.collect()

    reasons = {i.subject: i.reason for i in run.stores.queue.pending()}
    for h in held:
        h["reason"] = errors.get(h["collection_id"]) or next(
            (v for k, v in reasons.items() if h["collection_id"] in k), ""
        )
    docs = {d.canonical_id: d for d in run.stores.index._docs}  # noqa: SLF001
    insts = run.stores.instruments
    # every graph node gets a row (an edge must never point at a missing node), with its tags
    nodes = []
    for cid in sorted(set(run.stores.graph.node_ids()) | set(insts)):
        d, inst, g = docs.get(cid), insts.get(cid), run.stores.graph.node(cid)
        tags = d.tags if d else (g.tags if g else None)
        nodes.append(
            {
                "id": cid,
                "doc_type": d.doc_type if d else None,
                "hierarchy_level": inst.hierarchy_level if inst else None,
                "department": tags.department if tags else None,
                "section": tags.section if tags else None,
                "classification": tags.classification if tags else None,
                "file_no": tags.file_no if tags else None,
                "issue_date": str(d.issue_date) if d and d.issue_date else None,
                "effective_from": str(inst.effective_from)
                if inst and inst.effective_from
                else None,
                "valid_until": str(inst.valid_until) if inst and inst.valid_until else None,
                "subject": d.subject if d else None,
                "source_path": source_of[cid][0] if cid in source_of else None,
                "source_sha256": source_of[cid][1] if cid in source_of else None,
            }
        )
    edges = [(e.source, e.kind.value, e.target, e.confirmed) for e in run.stores.graph.edges()]
    out.mkdir(parents=True, exist_ok=True)
    _jsonl(out / "nodes.jsonl", nodes)
    _jsonl(out / "edges.jsonl", _edge_rows(edges))
    _jsonl(out / "held.jsonl", held)
    (out / "report.md").write_text(_report(root, rows, read_as, nodes, edges, held, threshold))
    print(
        f"wrote {out}/nodes.jsonl ({len(nodes)}), edges.jsonl ({len(edges)}), held.jsonl "
        f"({len(held)}), report.md"
    )
    # The files above are the record of the run. Each store is loaded on its own: one failing
    # does not stop the other, and any failure makes the run exit non-zero.
    failed = []
    # each store is made equal to this build (ADR-0055): links it no longer produces are deleted
    sync_opts: dict[str, Any] = {
        "max_delete_share": a.max_delete_share,
        "allow_large_delete": a.allow_large_delete,
        "dry_run": a.load_dry_run,
    }
    if a.load_postgres:
        try:
            pg = pg_from_settings(settings.model_copy(update={"state_store": "postgres"}))
            assert pg is not None  # noqa: S101 — postgres was just selected
            try:
                repo = PostgresGraphRepository(pg)
                p = repo.sync_rows(nodes, _edge_rows(edges), **sync_opts)
                verb = "DRY RUN, nothing changed —" if a.load_dry_run else "synced —"
                print(
                    f"postgres: {verb} {p.summary()}; tables now hold {repo.counts()}", flush=True
                )
            finally:
                pg.close()
        except Exception as exc:  # noqa: BLE001 — reported, then the next store is tried
            failed.append("postgres")
            print(f"postgres: FAILED ({type(exc).__name__}: {exc})", flush=True)
    if a.load_spanner:
        try:
            if not (settings.gcp_project_id and settings.spanner_instance):
                raise ValueError("C2_GCP_PROJECT_ID and C2_SPANNER_INSTANCE are required")
            from app.graph.spanner import CloudSpannerPort, SpannerGraphRepository

            sp = SpannerGraphRepository(
                CloudSpannerPort(
                    settings.gcp_project_id, settings.spanner_instance, settings.spanner_database
                )
            )
            p = sp.sync_rows(nodes, _edge_rows(edges), **sync_opts)
            verb = "DRY RUN, nothing changed —" if a.load_dry_run else "synced —"
            print(f"spanner: {verb} {p.summary()}; it now holds {sp.counts()}", flush=True)
        except Exception as exc:  # noqa: BLE001 — reported, then the next store is tried
            failed.append("spanner")
            print(f"spanner: FAILED ({type(exc).__name__}: {exc})", flush=True)
    if a.load_bigquery:
        try:
            if not (settings.gcp_project_id and settings.gcp_region):
                raise ValueError("C2_GCP_PROJECT_ID and C2_GCP_REGION are required")
            count = load_table(
                settings.gcp_project_id, settings.gcp_region, a.load_bigquery, table_rows(nodes)
            )
            print(f"bigquery: {a.load_bigquery} now holds {count} documents", flush=True)
        except Exception as exc:  # noqa: BLE001
            failed.append("bigquery")
            print(f"bigquery: FAILED ({type(exc).__name__}: {exc})", flush=True)
    if a.load_passages:
        table, uri = a.load_passages
        try:
            if not (settings.gcp_project_id and settings.gcp_region and settings.embedding_model):
                raise ValueError("C2_GCP_PROJECT_ID, C2_GCP_REGION and C2_EMBEDDING_MODEL needed")
            embedder = VertexEmbedder(
                settings.gcp_project_id,
                settings.gcp_region,
                settings.embedding_model,
                settings.embedding_dimensions,
            )
            parts = write_passage_parts(
                table_rows(nodes),
                run.texts,
                embedder,
                out / "passages",
                progress=lambda m: print(m, flush=True),
            )
            print(
                f"  passages: {parts.passages} in {len(parts.parts)} parts; "
                f"{parts.embedded_documents} documents embedded now, {parts.reused_documents} "
                f"kept; {embedder.calls} embedding requests",
                flush=True,
            )
            uris = [f"{uri.rstrip('/')}/passages/{p}" for p in parts.parts]
            count = load_passages_from_uri(
                settings.gcp_project_id, settings.gcp_region, table, uris
            )
            (out / "passages" / "loaded.json").write_text(
                json.dumps(
                    {"model": embedder.name, "table": table, "rows": count, "parts": parts.parts}
                ),
                "utf-8",
            )
            print(f"bigquery: {table} now holds {count} passages ({embedder.name})", flush=True)
        except Exception as exc:  # noqa: BLE001
            failed.append("passages")
            print(f"passages: FAILED ({type(exc).__name__}: {exc})", flush=True)
    if failed:
        print(f"stores not loaded: {', '.join(failed)}", flush=True)
        return 1
    return 0


def run_received(run: AssistRuntime, meta: dict[str, Any]) -> dt.datetime:
    """Received on its collection date (ordering only; the issue date is read from the file)."""
    try:
        day = dt.date.fromisoformat(str(meta.get("date")))
    except ValueError:
        day = run.as_of
    return dt.datetime.combine(day, dt.time(9), tzinfo=dt.UTC)


def _edge_rows(edges: list[tuple[str, str, str, bool]]) -> list[dict[str, Any]]:
    return [{"from": s, "relation": k, "to": t, "confirmed": c} for s, k, t, c in edges]


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")


def _report(
    root: Path,
    rows: list[dict[str, Any]],
    read_as: dict[str, str | None],
    nodes: list[dict[str, Any]],
    edges: list[tuple[str, str, str, bool]],
    held: list[dict[str, str]],
    threshold: float | None,
) -> str:
    ids = {n["id"] for n in nodes}
    same = sum(1 for k, v in read_as.items() if v == k)
    other = {k: v for k, v in read_as.items() if v and v != k}
    kinds = collections.Counter((k, c) for _, k, _, c in edges)
    inside = sum(1 for s, _, t, _ in edges if s in ids and t in ids)
    why = collections.Counter((h.get("reason") or h["status"])[:70] for h in held)
    # the collection tools' own links (candidates), as a second opinion — not ground truth
    theirs: set[tuple[str, str, str]] = set()
    rel = root / "manifests" / "relations.jsonl"
    for line in rel.read_text("utf-8").splitlines() if rel.is_file() else []:
        e = json.loads(line)
        if e["type"] in CHANGES and e.get("to"):
            theirs.add((e["from"], e["type"], e["to"]))
    ours = {(s, k, t) for s, k, t, _ in edges if k in CHANGES}
    both_held = {e for e in theirs if e[0] in ids and e[2] in ids}
    changed = collections.Counter(t for _, k, t, _ in edges if k in CHANGES)
    lines = [
        f"# Knowledge graph of the public corpus — {dt.date.today().isoformat()}",
        "",
        "Built by the normal ingestion pipeline (`python -m app.graph.build`). SANDBOX: OCR pages "
        f"pass at confidence ≥ {threshold} (uncalibrated test value). Public orders only.",
        "",
        f"- Orders given to the pipeline: **{len(rows)}**",
        f"- Indexed (graph nodes): **{len(nodes)}**; held for review: **{len(held)}**",
        f"- Pipeline read the same ID as the collection metadata: **{same}**; a different ID: "
        f"**{len(other)}**",
        f"- Relations (edges): **{len(edges)}**, of which both ends are indexed orders: {inside}",
        "",
        "| Relation | Confirmed (stated in the text) | Unconfirmed (candidate) |",
        "|---|---:|---:|",
    ]
    for k in sorted({k for k, _ in kinds}):
        lines.append(f"| {k} | {kinds[(k, True)]} | {kinds[(k, False)]} |")
    lines += [
        "",
        "## Second opinion: the collection tools' links (candidates, not ground truth)",
        f"- Change links (supersedes / amends / repeals / clarifies) with both orders indexed, in "
        f"the collection manifest: {len(both_held)}",
        f"- of those, also read by the pipeline: {len(both_held & ours)}; only in the manifest: "
        f"{len(both_held - ours)}; only read by the pipeline: "
        f"{len({e for e in ours if e[0] in ids and e[2] in ids} - theirs)}",
        "",
        "## Orders changed most often",
    ]
    lines += [f"- {cid}: {n} later orders" for cid, n in changed.most_common(10)]
    lines += ["", "## Held for review, by reason"]
    lines += [f"- {n} × {w}" for w, n in why.most_common(12)]
    if other:
        lines += ["", "## Different ID read (first 15)"]
        lines += [f"- {k} → {v}" for k, v in list(sorted(other.items()))[:15]]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    sys.exit(main())
