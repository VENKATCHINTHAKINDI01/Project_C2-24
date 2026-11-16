"""The sandbox's document store: the SYNTHETIC mock corpus files, with the access tags the mock
e-Office records for each upload (plan §11.6). Only the source-system columns of an index are
read — file, department, section, classification and the e-File number. Expected IDs, statuses
and dates in `documents_index.csv` are evaluation facts and are never read here (CLAUDE.md §9.2).

Synthetic set v2 (ADR-0020) adds two indexes: the files' correspondence pages (in the repo) and
the real public G.O.s the notes can cite (in the data root, outside the repo; checked by SHA-256
so a changed or missing file stops the load instead of serving something else)."""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

from app.connectors.eoffice import ConnectorError, SourceArtefact

SOURCE_COLUMNS = ("file", "department", "section", "classification", "raw_reference")


def artefacts_from_corpus(corpus_dir: Path) -> list[SourceArtefact]:
    return artefacts_from_index(corpus_dir / "documents_index.csv", corpus_dir, "mock://")


def artefacts_from_v2(v2_dir: Path, public_root: Path) -> list[SourceArtefact]:
    """v2 correspondence pages (repo) + the public orders listed in public_index.csv (data root)."""
    return artefacts_from_index(
        v2_dir / "documents_index.csv", v2_dir.parent, "mock://efiles_v2/"
    ) + artefacts_from_index(v2_dir / "public_index.csv", public_root, "public://")


def arrivals_from_v2(v2_dir: Path, public_root: Path) -> list[SourceArtefact]:
    """Public orders held back for the demo (public_holdback.csv): NOT part of the initial load;
    the sandbox lets one "arrive" (data collection plan step 11; plan §11.5 touchpoint 4)."""
    index = v2_dir / "public_holdback.csv"
    return artefacts_from_index(index, public_root, "public://") if index.is_file() else []


def artefacts_from_index(index: Path, root: Path, uri_prefix: str) -> list[SourceArtefact]:
    with index.open(encoding="utf-8", newline="") as fh:
        rows = [
            {k: r[k] for k in (*SOURCE_COLUMNS, "sha256") if k in r} for r in csv.DictReader(fh)
        ]
    out = []
    for r in rows:
        path = root / r["file"]
        if not path.resolve().is_relative_to(root.resolve()):
            raise ConnectorError("index entry outside its root")
        data = path.read_bytes()
        if "sha256" in r and hashlib.sha256(data).hexdigest() != r["sha256"]:
            raise ConnectorError(f"document changed since it was indexed: {r['file']}")
        ref = r["raw_reference"]
        out.append(
            SourceArtefact(
                source_uri=f"{uri_prefix}{r['file']}",
                filename=path.name,
                department=r["department"],
                section=r["section"],
                classification=r["classification"],
                file_no=ref.removeprefix("File No.") if ref.startswith("File No.") else None,
                data=data,
            )
        )
    return out
