"""The file of a public order that is only in the cloud index (ADR-0028 addendum, ADR-0014).

The sandbox keeps the files of its own ~120 orders in memory; the other public orders are known
to the service only through BigQuery. To show one, the service reads the order's file from the
mounted corpus bucket at the path the graph build recorded, and serves it only if the bytes hash
to the SHA-256 recorded with it. The lookup carries the officer's scope in its WHERE clause like
every other read (CLAUDE.md §4.2), and callers ask only after the access re-check has passed.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from app.auth.models import Scope
from app.ingestion.document_store import StoredDocument, media_type
from app.retrieval.bigquery_index import SCOPE_SQL, QueryRunner, scope_params

log = logging.getLogger(__name__)

SOURCE_SQL = (
    "SELECT source_path, source_sha256 FROM `{table}` "  # noqa: S608 — table validated
    "WHERE canonical_id = @cid AND " + SCOPE_SQL + " LIMIT 1"
)


class CloudSourceFiles:
    def __init__(self, runner: QueryRunner, table: str, root: Path) -> None:
        if not all(p.replace("-", "").replace("_", "").isalnum() for p in table.split(".")):
            raise ValueError("table must be project.dataset.table")
        self._runner, self._table, self._root = runner, table, root.resolve()

    def get(self, canonical_id: str, scope: Scope) -> StoredDocument | None:
        """The order's file, or None: not in scope, no recorded file, a path outside the corpus,
        a missing file or bytes that differ from the recorded hash (all logged by kind only)."""
        rows = self._runner.run(
            SOURCE_SQL.format(table=self._table),
            [*scope_params(scope), ("cid", "STRING", canonical_id)],
        )
        if not rows or not rows[0].get("source_path") or not rows[0].get("source_sha256"):
            return None
        path = (self._root / str(rows[0]["source_path"])).resolve()
        if not path.is_relative_to(self._root):
            log.error("cloud source refused: path outside the corpus")
            return None
        try:
            data = path.read_bytes()
        except OSError as exc:
            log.error("cloud source unreadable: %s", type(exc).__name__)
            return None
        sha = hashlib.sha256(data).hexdigest()
        if sha != rows[0]["source_sha256"]:
            log.error("cloud source refused: bytes differ from the recorded hash")
            return None
        return StoredDocument(
            version=f"src-{sha[:16]}", media_type=media_type(data, path.name), data=data
        )
