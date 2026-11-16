"""Review queue and confirmed text in PostgreSQL (plan §4.2, §9.1; CLAUDE.md §8).

The same behaviour as the in-memory `ReviewQueue`:
- `submit` is idempotent per (kind, subject, version);
- an item is decided once;
- a reviewer and a reason are required;
- `blocks` holds a version while any item for it is pending or rejected.

Decisions survive restarts, so a file confirmed yesterday is indexed again at startup without asking
anyone. Schema: `data/schemas/postgres/0001_review_audit.sql`.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, MutableMapping
from typing import Any

from app.hitl.queue import ReviewError, ReviewItem, ReviewKind, ReviewQueue, ReviewState
from app.pg import Pg

# Fixed statements only (no SQL built from input; every value is a bound parameter).
_ROW = "SELECT item_id, kind, subject, version, reason, created_at, state, reviewer, decided_at, \
decision_reason FROM review_items"
_SUBMIT = "INSERT INTO review_items (item_id, kind, subject, version, reason, created_at) \
VALUES ('RV-' || lpad(nextval('review_item_seq')::text, 6, '0'), %s, %s, %s, %s, %s) \
ON CONFLICT (kind, subject, version) DO NOTHING"
_BY_KEY = _ROW + " WHERE kind = %s AND subject = %s AND version = %s"
_LOCK = "SELECT state FROM review_items WHERE item_id = %s FOR UPDATE"
_DECIDE = (
    "UPDATE review_items SET state = %s, reviewer = %s, decided_at = %s, decision_reason = %s \
WHERE item_id = %s"
)
_BY_ID = _ROW + " WHERE item_id = %s"
_PENDING = _ROW + " WHERE state = 'pending' ORDER BY item_id"
_PENDING_KIND = _ROW + " WHERE state = 'pending' AND kind = %s ORDER BY item_id"
_BLOCKS = "SELECT 1 FROM review_items WHERE subject = %s AND version = %s \
AND state <> 'confirmed' LIMIT 1"
_HISTORY = _ROW + " ORDER BY item_id"


def _item(row: Any) -> ReviewItem:
    return ReviewItem(
        item_id=row[0],
        kind=ReviewKind(row[1]),
        subject=row[2],
        version=row[3],
        reason=row[4],
        created_at=row[5],
        state=ReviewState(row[6]),
        reviewer=row[7],
        decided_at=row[8],
        decision_reason=row[9],
    )


class PostgresReviewQueue(ReviewQueue):
    def __init__(self, pg: Pg) -> None:  # no in-memory state at all
        self.pg = pg

    def submit(
        self, kind: ReviewKind, subject: str, version: str, reason: str, at: dt.datetime
    ) -> ReviewItem:
        with self.pg.tx() as cur:
            cur.execute(_SUBMIT, (kind.value, subject, version, reason[:500], at))
            cur.execute(_BY_KEY, (kind.value, subject, version))
            return _item(cur.fetchone())

    def decide(
        self, item_id: str, *, reviewer: str, confirm: bool, reason: str, at: dt.datetime
    ) -> ReviewItem:
        state = ReviewState.CONFIRMED if confirm else ReviewState.REJECTED
        with self.pg.tx() as cur:  # same checks, same order as the in-memory queue
            cur.execute(_LOCK, (item_id,))
            row = cur.fetchone()
            if row is None:
                raise ReviewError("unknown review item")
            if row[0] != ReviewState.PENDING.value:
                raise ReviewError("already decided; submit a new item to revisit")
            if not reviewer.strip() or not reason.strip():
                raise ReviewError("reviewer identity and reason are required")
            cur.execute(_DECIDE, (state.value, reviewer, at, reason[:500], item_id))
            cur.execute(_BY_ID, (item_id,))
            return _item(cur.fetchone())

    def pending(self, kind: ReviewKind | None = None) -> tuple[ReviewItem, ...]:
        with self.pg.tx() as cur:
            if kind is None:
                cur.execute(_PENDING)
            else:
                cur.execute(_PENDING_KIND, (kind.value,))
            return tuple(_item(r) for r in cur.fetchall())

    def blocks(self, subject: str, version: str) -> bool:
        with self.pg.tx() as cur:
            cur.execute(_BLOCKS, (subject, version))
            return cur.fetchone() is not None

    def history(self) -> tuple[ReviewItem, ...]:
        with self.pg.tx() as cur:
            cur.execute(_HISTORY)
            return tuple(_item(r) for r in cur.fetchall())


class PostgresConfirmedText(MutableMapping[str, str]):
    """version → text a reviewer confirmed or corrected (what gets indexed for that scan)."""

    def __init__(self, pg: Pg) -> None:
        self.pg = pg

    def __getitem__(self, version: str) -> str:
        with self.pg.tx() as cur:
            cur.execute("SELECT text FROM confirmed_texts WHERE version = %s", (version,))
            row = cur.fetchone()
        if row is None:
            raise KeyError(version)
        return str(row[0])

    def __setitem__(self, version: str, text: str) -> None:
        with self.pg.tx() as cur:
            cur.execute(
                "INSERT INTO confirmed_texts (version, text) VALUES (%s, %s) "
                "ON CONFLICT (version) DO UPDATE SET text = EXCLUDED.text, recorded_at = now()",
                (version, text),
            )

    def __delitem__(self, version: str) -> None:
        raise ReviewError("confirmed text is kept; a new decision supersedes it")

    def __iter__(self) -> Iterator[str]:
        with self.pg.tx() as cur:
            cur.execute("SELECT version FROM confirmed_texts ORDER BY version")
            versions = [str(r[0]) for r in cur.fetchall()]
        return iter(versions)

    def __len__(self) -> int:
        with self.pg.tx() as cur:
            cur.execute("SELECT count(*) FROM confirmed_texts")
            return int(cur.fetchone()[0])
