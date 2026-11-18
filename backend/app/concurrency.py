"""One writer, many readers, for the sandbox's in-memory indexes (ADR-0039).

The assistant's in-memory stores (indexes, graph, texts) are read by every request and changed
only when e-Office hands over new material (an order arrives, a receipt is diarised, a file is
closed, an OCR text is confirmed). Readers share the lock; a change waits for the readers in
flight, runs alone, and new readers wait for it (writer preference, so a change is never starved).
Cloud stores (BigQuery, Cloud SQL) have their own isolation and do not need it.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager


class RWLock:
    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    def acquire_read(self) -> None:
        with self._cond:
            while self._writer or self._waiting_writers:
                self._cond.wait()
            self._readers += 1

    def release_read(self) -> None:
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()

    @contextmanager
    def read(self) -> Iterator[None]:
        self.acquire_read()
        try:
            yield
        finally:
            self.release_read()

    @contextmanager
    def write(self) -> Iterator[None]:
        with self._cond:
            self._waiting_writers += 1
            try:
                while self._writer or self._readers:
                    self._cond.wait()
            finally:
                self._waiting_writers -= 1
            self._writer = True
        try:
            yield
        finally:
            with self._cond:
                self._writer = False
                self._cond.notify_all()
