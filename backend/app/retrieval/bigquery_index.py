"""Ladder rungs L0 and L1 on BigQuery (plan §3.2, §3.6; CLAUDE.md §2.2, §3, §4.2).

Two fixed, parameterised templates over one table of document metadata. The officer's scope is
part of the WHERE clause of both (pushed down: an out-of-scope row is never read back), and every
returned row is checked again with `scope.admits` before it leaves this module, so the SQL
predicate and the in-memory rule cannot silently disagree: a row the rule refuses is dropped and
counted as an error in the log. No SQL is ever built from a question or by a model; the only
variable parts are bound parameters.

Same answers as `InMemoryScopedIndex` (contract test). Any BigQuery error propagates: the caller
(`retrieve`) fails closed.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

from app.auth.models import DocumentAccessTags, Scope
from app.identifiers.canonical import InvalidCanonicalIdError, lookup_keys, parse_canonical_id
from app.retrieval.scoped import IndexedDocument, L1Criteria

log = logging.getLogger(__name__)

COLUMNS = (
    "canonical_id, base_id, department, section, classification, file_no, doc_type, "
    "issue_date, subject"
)
# The scope as SQL. A published instrument (no file number) at the public marking is open to
# everyone; anything else needs the officer's department, a marking within clearance, and one of:
# department-wide reach, the section, or the file. An unknown marking matches neither list.
SCOPE_SQL = (
    "((classification IN UNNEST(@public_marks) AND file_no IS NULL) "
    "OR (department = @scope_department AND classification IN UNNEST(@cleared_marks) "
    "AND (@department_wide OR section IN UNNEST(@scope_sections) "
    "OR file_no IN UNNEST(@scope_files))))"
)
# {columns} is the constant above and {table} is validated in the constructor; every value that
# varies per request is a bound parameter.
EXACT_SQL = (
    "SELECT {columns} FROM `{table}` WHERE " + SCOPE_SQL + " "  # noqa: S608
    "AND (canonical_id IN UNNEST(@keys) OR (@by_base AND base_id IN UNNEST(@keys)))"
)
FILTER_SQL = (
    "SELECT {columns} FROM `{table}` WHERE " + SCOPE_SQL + " "  # noqa: S608
    "AND (@department IS NULL OR department = @department) "
    "AND (@any_type OR doc_type IN UNNEST(@doc_types)) "
    "AND (@issued_from IS NULL OR issue_date >= @issued_from) "
    "AND (@issued_to IS NULL OR issue_date <= @issued_to) "
    "AND NOT EXISTS (SELECT 1 FROM UNNEST(@subject_terms) AS t "
    "WHERE STRPOS(LOWER(subject), t) = 0)"
)

Param = tuple[str, str, Any]  # (name, BigQuery type or "ARRAY<type>", value)


class QueryRunner(Protocol):
    """Runs one fixed template with bound parameters and returns rows as mappings."""

    def run(self, sql: str, params: Sequence[Param]) -> list[Mapping[str, Any]]: ...


class BigQueryRunner:
    """The real runner (google-cloud-bigquery, Application Default Credentials)."""

    def __init__(self, project: str, location: str) -> None:
        from google.cloud import bigquery

        self._bq = bigquery
        self._client = bigquery.Client(project=project, location=location)

    def run(self, sql: str, params: Sequence[Param]) -> list[Mapping[str, Any]]:
        bq = self._bq
        bound = [
            bq.ArrayQueryParameter(n, t[6:-1], v)
            if t.startswith("ARRAY<")
            else bq.ScalarQueryParameter(n, t, v)
            for n, t, v in params
        ]
        job = self._client.query(sql, job_config=bq.QueryJobConfig(query_parameters=bound))
        return [dict(r.items()) for r in job.result()]


def scope_params(scope: Scope) -> list[Param]:
    ranks = scope.classification_ranks
    return [
        (
            "public_marks",
            "ARRAY<STRING>",
            sorted(m for m, r in ranks.items() if r == scope.public_rank),
        ),
        (
            "cleared_marks",
            "ARRAY<STRING>",
            sorted(m for m, r in ranks.items() if r <= scope.max_rank),
        ),
        ("scope_department", "STRING", scope.department),
        ("department_wide", "BOOL", scope.department_wide),
        ("scope_sections", "ARRAY<STRING>", sorted(scope.sections)),
        ("scope_files", "ARRAY<STRING>", sorted(scope.file_nos)),
    ]


def _doc(row: Mapping[str, Any]) -> IndexedDocument:
    day = row.get("issue_date")
    return IndexedDocument(
        canonical_id=row["canonical_id"],
        tags=DocumentAccessTags(
            doc_id=row["canonical_id"],
            department=row["department"],
            section=row.get("section") or None,
            classification=row["classification"],
            file_no=row.get("file_no") or None,
        ),
        doc_type=row.get("doc_type") or "",
        issue_date=dt.date.fromisoformat(day) if isinstance(day, str) else day,
        subject=row.get("subject") or "",
    )


class BigQueryScopedIndex:
    """`ScopedRetriever` over `<project>.<dataset>.documents`."""

    def __init__(self, runner: QueryRunner, table: str) -> None:
        if not all(p.replace("-", "").replace("_", "").isalnum() for p in table.split(".")):
            raise ValueError("table must be project.dataset.table")  # never from user input
        self._runner, self._table = runner, table

    def _rows(self, sql: str, params: list[Param], scope: Scope) -> list[IndexedDocument]:
        rows = self._runner.run(
            sql.format(columns=COLUMNS, table=self._table), [*scope_params(scope), *params]
        )
        docs = [_doc(r) for r in rows]
        kept = [d for d in docs if scope.admits(d.tags)]
        if len(kept) != len(docs):  # the SQL predicate and the rule disagree: a defect
            log.error(
                "bigquery scope predicate returned %d rows the scope refuses", len(docs) - len(kept)
            )
        return kept

    def exact(self, canonical_id: str, scope: Scope) -> list[IndexedDocument]:
        try:
            keys = lookup_keys(canonical_id)
        except InvalidCanonicalIdError:
            return []
        pool = self._rows(
            EXACT_SQL,
            [("keys", "ARRAY<STRING>", list(keys)), ("by_base", "BOOL", len(keys) == 1)],
            scope,
        )
        for key in keys:  # exact ID first, then the pre-ADR-0007 form
            hits = [d for d in pool if d.canonical_id == key]
            if hits:
                return hits
        return sorted(pool, key=lambda d: d.canonical_id) if len(keys) == 1 else []

    def filter(self, criteria: L1Criteria, scope: Scope) -> list[IndexedDocument]:
        out = self._rows(
            FILTER_SQL,
            [
                ("department", "STRING", criteria.department),
                ("any_type", "BOOL", not criteria.doc_types),
                ("doc_types", "ARRAY<STRING>", sorted(criteria.doc_types)),
                ("issued_from", "DATE", criteria.issued_from),
                ("issued_to", "DATE", criteria.issued_to),
                ("subject_terms", "ARRAY<STRING>", [t.lower() for t in criteria.subject_terms]),
            ],
            scope,
        )
        return sorted(
            out, key=lambda d: (d.issue_date or dt.date.min, d.canonical_id), reverse=True
        )


def table_rows(nodes: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Rows for the documents table from the graph build's node rows. A row without access tags
    or a document type is left out (it is not a readable document)."""
    out = []
    for n in nodes:
        if not (n.get("department") and n.get("classification") and n.get("doc_type")):
            continue
        try:
            base = parse_canonical_id(n["id"]).base_id
        except InvalidCanonicalIdError:
            base = None
        out.append(
            {
                "canonical_id": n["id"],
                "base_id": base,
                "department": n["department"],
                "section": n.get("section"),
                "classification": n["classification"],
                "file_no": n.get("file_no"),
                "doc_type": n["doc_type"],
                "hierarchy_level": n.get("hierarchy_level"),
                "issue_date": n.get("issue_date"),
                "effective_from": n.get("effective_from"),
                "valid_until": n.get("valid_until"),
                "subject": n.get("subject") or "",
                "source_path": n.get("source_path"),
                "source_sha256": n.get("source_sha256"),
            }
        )
    return out


SCHEMA = (  # name, type, mode
    ("canonical_id", "STRING", "REQUIRED"),
    ("base_id", "STRING", "NULLABLE"),
    ("department", "STRING", "REQUIRED"),
    ("section", "STRING", "NULLABLE"),
    ("classification", "STRING", "REQUIRED"),
    ("file_no", "STRING", "NULLABLE"),
    ("doc_type", "STRING", "REQUIRED"),
    ("hierarchy_level", "INT64", "NULLABLE"),
    ("issue_date", "DATE", "NULLABLE"),
    ("effective_from", "DATE", "NULLABLE"),
    ("valid_until", "DATE", "NULLABLE"),
    ("subject", "STRING", "REQUIRED"),
    # where the order's file is in the corpus bucket (relative to the staging root) and its
    # SHA-256, so the service can show a cloud-only order's file and prove it is the same bytes
    ("source_path", "STRING", "NULLABLE"),
    ("source_sha256", "STRING", "NULLABLE"),
)


def load_table(project: str, location: str, table: str, rows: list[dict[str, Any]]) -> int:
    """Replace the documents table with `rows` in one load job (atomic: readers see the old
    table or the new one). The table is derived data, rebuilt from the corpus each run."""
    from google.cloud import bigquery

    client = bigquery.Client(project=project, location=location)
    cfg = bigquery.LoadJobConfig(
        schema=[bigquery.SchemaField(n, t, mode=m) for n, t, m in SCHEMA],
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )
    client.load_table_from_json(rows, table, job_config=cfg).result()
    return int(client.get_table(table).num_rows)
