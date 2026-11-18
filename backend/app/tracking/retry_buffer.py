"""Buffer and retry for the tracking sinks (plan §14.4: "Audit / query log sink — requests not
recorded → buffer and retry; alert if the buffer fills").

The BigQuery query log and the officers' feedback actions are streamed one row at a time. When an
insert fails (BigQuery unreachable, a quota answer), the row is kept here, bounded, and sent again
with the next write, oldest first. The answer or the officer's action never waits for tracking and
never fails because of it.

If the buffer fills, the oldest rows are dropped and a fixed CRITICAL line is logged:
``C2_TRACKING_BUFFER_FULL sink=<name> dropped=<n>``. A log-based alert on that text is the alert
(infrastructure/gcp/28_tracking_alert.sh). Rows hold IDs and metadata only, never document text.

The buffer lives in the instance's memory: an instance that stops loses what it held, and says so
in the log as it stops. The audit trail itself (Cloud SQL) does not use this buffer: an action that
cannot be audited does not happen (ADR-0049).
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any

log = logging.getLogger(__name__)

FULL = "C2_TRACKING_BUFFER_FULL"
Insert = Callable[[list[dict[str, Any]]], Sequence[Any]]  # BigQuery insert_rows_json shape


class RetryBuffer:
    """Rows for one sink. `insert(rows)` returns the per-row errors (BigQuery's shape: a list of
    {"index": i, "errors": [...]}) and may raise; rows that did not go are kept and retried."""

    def __init__(
        self, name: str, insert: Insert, *, max_rows: int = 5_000, batch: int = 500
    ) -> None:
        self.name = name
        self._insert = insert
        self._max = max_rows
        self._batch = batch
        self._rows: deque[tuple[dict[str, Any], int]] = deque()  # (row, times rejected)
        self._lock = threading.Lock()
        self.dropped = 0  # rows lost because the buffer was full (since start)

    @property
    def waiting(self) -> int:
        return len(self._rows)

    def write(self, row: dict[str, Any]) -> None:
        with self._lock:
            self._rows.append((row, 0))
            over = len(self._rows) - self._max
            if over > 0:
                for _ in range(over):
                    self._rows.popleft()
                self.dropped += over
                log.critical("%s sink=%s dropped=%d", FULL, self.name, self.dropped)
            self._flush()

    def flush(self) -> None:
        with self._lock:
            self._flush()

    def _flush(self) -> None:
        while self._rows:
            batch = [self._rows[i] for i in range(min(self._batch, len(self._rows)))]
            try:
                errors = list(self._insert([row for row, _ in batch]) or ())
            except Exception as exc:  # noqa: BLE001 — tracking never breaks the answer path
                log.error(
                    "%s insert failed (%s); %d row(s) kept for retry",
                    self.name,
                    type(exc).__name__,
                    len(self._rows),
                )
                return
            failed = sorted(
                {int(e["index"]) for e in errors if isinstance(e, dict) and "index" in e}
            )
            for _ in range(len(batch)):
                self._rows.popleft()
            if failed:
                # a row BigQuery rejects is tried once more (a transient refusal), then dropped
                # and counted: one it refuses for its content would be refused forever
                again = [(batch[i][0], batch[i][1] + 1) for i in failed if 0 <= i < len(batch)]
                gone = [r for r in again if r[1] > 1]
                self.dropped += len(gone)
                log.error("%s rejected %d row(s), %d dropped", self.name, len(again), len(gone))
                for r in reversed([r for r in again if r[1] <= 1]):
                    self._rows.appendleft(r)
                return

    def close(self) -> None:
        """At shutdown: one last try, then say what is lost."""
        self.flush()
        if self._rows:
            log.error("%s: %d tracking row(s) not written at shutdown", self.name, len(self._rows))
