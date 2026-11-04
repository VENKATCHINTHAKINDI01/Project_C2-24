"""The sandbox's document store: the SYNTHETIC mock corpus files, with the access tags the mock
e-Office records for each upload (plan §11.6). Only the source-system columns of
`documents_index.csv` are read — file, department, section, classification and the e-File number.
Expected IDs, statuses and dates in that file are evaluation facts and are never read here
(CLAUDE.md §9.2)."""

from __future__ import annotations

import csv
from pathlib import Path

from app.connectors.eoffice import SourceArtefact

SOURCE_COLUMNS = ("file", "department", "section", "classification", "raw_reference")


def artefacts_from_corpus(corpus_dir: Path) -> list[SourceArtefact]:
    with (corpus_dir / "documents_index.csv").open(encoding="utf-8", newline="") as fh:
        rows = [{k: r[k] for k in SOURCE_COLUMNS} for r in csv.DictReader(fh)]
    out = []
    for r in rows:
        path = corpus_dir / r["file"]
        ref = r["raw_reference"]
        out.append(
            SourceArtefact(
                source_uri=f"mock://{r['file']}",
                filename=path.name,
                department=r["department"],
                section=r["section"],
                classification=r["classification"],
                file_no=ref.removeprefix("File No.") if ref.startswith("File No.") else None,
                data=path.read_bytes(),
            )
        )
    return out
