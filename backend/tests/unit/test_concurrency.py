"""Concurrent requests on the in-memory sandbox (ADR-0039). Regression: under load, a file
created while another officer's handover listed the section's files raised "dictionary changed
size during iteration" (a 503 for that officer)."""

from __future__ import annotations

import threading
import time

from app.concurrency import RWLock
from app.config import get_settings
from app.main import create_app


def test_sandbox_state_survives_writes_during_reads() -> None:
    app = create_app(get_settings().model_copy(update={"sandbox": True}))
    adapter = app.state.adapter
    errors: list[BaseException] = []
    stop = threading.Event()

    def read() -> None:
        try:
            while not stop.is_set():
                adapter.section_files("U01")
                adapter.reachable_files("U02")
                adapter.officer_files("U01")
        except BaseException as exc:  # noqa: BLE001 — the test records any failure
            errors.append(exc)

    readers = [threading.Thread(target=read) for _ in range(4)]
    for t in readers:
        t.start()
    for i in range(300):
        adapter.create_file("U01", f"Establishment – Sri X{i} – transfer on spouse grounds", [])
    stop.set()
    for t in readers:
        t.join()
    assert errors == []


def test_writer_waits_for_readers_and_new_readers_wait_for_a_writer() -> None:
    lock = RWLock()
    order: list[str] = []
    lock.acquire_read()

    def write() -> None:
        with lock.write():
            order.append("write")

    def late_read() -> None:
        with lock.read():
            order.append("late read")

    w = threading.Thread(target=write)
    w.start()
    time.sleep(0.05)
    r = threading.Thread(target=late_read)
    r.start()
    time.sleep(0.05)
    assert order == []  # the writer waits for the reader in flight; the new reader waits too
    lock.release_read()
    w.join()
    r.join()
    assert order == ["write", "late read"]
