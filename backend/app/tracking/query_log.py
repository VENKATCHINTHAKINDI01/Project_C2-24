"""Query tracking: one structured record per assistant question (plan §10.4; ADR-0029).

Fields mirror `AgentState`. Privacy (plan §10.4; CLAUDE.md §4.11): IDs and metadata only. The
question itself is NOT stored — only a hash of its normalised form (to count repeats) and its
intent; record texts and answer texts never are. Who asked is stored as the officer's ID,
department, section and post, so views by department / role are possible without content.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from collections.abc import Sequence
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger(__name__)


class QueryRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    query_id: str
    ts: dt.datetime
    session_id: str
    turn: int = Field(ge=1)
    user_id: str
    department: str
    section: str | None
    role: str
    query_hash: str  # sha256 of the normalised question (never the text)
    intent: str | None
    entities: tuple[str, ...] = ()  # canonical IDs / file numbers the question named or recalled
    ladder_level: str | None
    retrieved_ids: tuple[str, ...] = ()  # authorised candidates (after scope + re-check)
    evidence_ids: tuple[str, ...] = ()
    cited_ids: tuple[str, ...] = ()  # canonical IDs cited by shown statements
    conflicts_found: int = 0
    conflict_types: tuple[str, ...] = ()
    scope_signature: str | None
    latency_ms: int = Field(ge=0)
    cache_hit: bool = False
    answer_status: str  # answered | review_needed | no_answer | not_run | denied
    human_action: str | None = None  # filled later from the review endpoints
    # plan §10.4 raw_query, for the monitoring officer's pad (ADR-0035): the officer's own words,
    # never document text; shown only to a monitoring officer cleared at least as high as the
    # asker (`clearance_rank`). Off with C2_QUERY_LOG_TEXT=false.
    question: str | None = Field(default=None, max_length=500)
    clearance_rank: int | None = None
    # unusual-activity signals on this question, fixed codes only (ADR-0036; app.tracking.signals)
    flags: tuple[str, ...] = ()


def query_hash(question: str) -> str:
    return hashlib.sha256(" ".join(question.lower().split()).encode()).hexdigest()


class QueryLog(Protocol):
    def write(self, record: QueryRecord) -> None: ...


class InMemoryQueryLog:
    """Reference log (sandbox default, tests)."""

    def __init__(self) -> None:
        self.records: list[QueryRecord] = []

    def write(self, record: QueryRecord) -> None:
        self.records.append(record)


def bq_row(r: QueryRecord) -> dict[str, Any]:
    row = r.model_dump(mode="json")
    for k, v in row.items():
        if isinstance(v, tuple):
            row[k] = list(v)
    return row


class BigQueryQueryLog:
    """Streaming insert into `<project>.<prefix>_audit.query_log` (schema:
    data/schemas/bigquery/query_log.json). Needs table write on the dataset only (no job).
    Tracking must never break an answer: a failed insert is logged (type only) and dropped."""

    def __init__(self, project: str, table: str, client: Any | None = None) -> None:
        if client is None:
            from google.cloud import bigquery

            client = bigquery.Client(project=project)
        self._client, self._table = client, table

    def write(self, record: QueryRecord) -> None:
        try:
            errors = self._client.insert_rows_json(self._table, [bq_row(record)])
        except Exception as exc:  # noqa: BLE001 — tracking is best-effort, never the answer path
            log.error("query log insert failed: %s", type(exc).__name__)
            return
        if errors:
            log.error("query log insert rejected %d row(s)", len(errors))


def query_log_columns() -> Sequence[str]:
    return tuple(QueryRecord.model_fields)
