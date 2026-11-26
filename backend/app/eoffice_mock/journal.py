"""Sandbox journal (ADR-0071): the officers' actions in the mock e-Office survive a restart or a
new deploy. Each successful action (create a file, write / save / confirm / discard a note or
draft, send, put up, return, issue, attach, close) is appended as one record; at start-up the
records are replayed, in order, through the same adapter methods at their recorded times, so the
files, notes, movements and issued orders — and the documents they hand to ingestion — come back
exactly as they were. Nothing here touches access rules: replay runs the same checks as the
officer's original click.

Stores: `FileJournal` (a local JSON-lines file) and `PostgresJournal` (Cloud SQL table
`sandbox_journal`, migration 0007). SYNTHETIC sandbox data only."""

from __future__ import annotations

import base64
import datetime as dt
import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from app.connectors.eoffice import DraftRequest
from app.pg import Pg

log = logging.getLogger(__name__)

# the adapter's officer actions (not reads); nested calls (send_file signing notes) are not
# recorded twice — only the outermost action is
ACTIONS = (
    "create_file", "write_note", "create_draft", "save_draft", "confirm_yellow_note",
    "discard_draft", "submit_draft", "return_draft", "approve_and_issue", "send_file",
    "add_attachment", "close_file", "letter_arrives", "order_arrives",
)  # fmt: skip


class Journal(Protocol):
    def load(self) -> list[dict[str, Any]]: ...

    def append(self, record: dict[str, Any]) -> None: ...


class FileJournal:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def load(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        out = []
        for line in self.path.read_text("utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def append(self, record: dict[str, Any]) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")


class PostgresJournal:
    def __init__(self, pg: Pg) -> None:
        self.pg = pg

    def load(self) -> list[dict[str, Any]]:
        with self.pg.tx() as cur:
            cur.execute("SELECT body FROM sandbox_journal ORDER BY seq")
            return [json.loads(r[0]) for r in cur.fetchall()]

    def append(self, record: dict[str, Any]) -> None:
        with self.pg.tx() as cur:
            cur.execute(
                "INSERT INTO sandbox_journal (at, action, body) VALUES (%s, %s, %s)",
                (record["at"], record["action"], json.dumps(record, ensure_ascii=False)),
            )


def _enc(v: Any) -> Any:
    if isinstance(v, bytes):
        return {"__b64__": base64.b64encode(v).decode("ascii")}
    if isinstance(v, dt.date) and not isinstance(v, dt.datetime):
        return {"__date__": v.isoformat()}
    if isinstance(v, DraftRequest):
        return {"__draft_request__": v.model_dump(mode="json")}
    if isinstance(v, (list, tuple)):
        return [_enc(x) for x in v]
    return v


def _dec(v: Any) -> Any:
    if isinstance(v, dict):
        if "__b64__" in v:
            return base64.b64decode(v["__b64__"])
        if "__date__" in v:
            return dt.date.fromisoformat(v["__date__"])
        if "__draft_request__" in v:
            return DraftRequest.model_validate(v["__draft_request__"])
    if isinstance(v, list):
        return [_dec(x) for x in v]
    return v


def attach_journal(adapter: Any, journal: Journal) -> int:
    """Replay the journal into a freshly seeded `adapter`, then record its officer actions from
    now on. Returns the number of records replayed. A record that no longer applies (the seed
    changed) is skipped with a warning; the rest still replay."""
    originals: dict[str, Callable[..., Any]] = {n: getattr(adapter, n) for n in ACTIONS}
    replayed = 0
    try:
        records = journal.load()
    except Exception:  # noqa: BLE001 — e.g. migration 0007 not applied: start, but say so
        log.error(
            "sandbox journal could not be read; the sandbox starts from its seed", exc_info=True
        )
        records = []
    for rec in records:
        fn = originals.get(str(rec.get("action")))
        if fn is None:
            continue
        adapter._now = dt.datetime.fromisoformat(rec["at"])  # noqa: SLF001 — replay at its time
        try:
            fn(*_dec(rec.get("args", [])), **{k: _dec(v) for k, v in rec.get("kwargs", {}).items()})
            replayed += 1
        except Exception as exc:  # noqa: BLE001 — one stale record must not stop the rest
            log.warning("sandbox journal: %s skipped on replay (%s)", rec.get("action"), exc)
        finally:
            adapter._now = None  # noqa: SLF001
    depth = threading.local()

    def wrap(name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
        def recorded(*args: Any, **kwargs: Any) -> Any:
            outer = getattr(depth, "n", 0) == 0
            # one instant for the whole action (frozen under the sandbox lock), so a replay at
            # the recorded time gives the same dates, to the microsecond
            with adapter._state_lock:  # noqa: SLF001
                at = adapter._clock()  # noqa: SLF001 — the time the action ran
                frozen = outer and adapter._now is None  # noqa: SLF001
                if frozen:
                    adapter._now = at  # noqa: SLF001
                depth.n = getattr(depth, "n", 0) + 1
                try:
                    result = fn(*args, **kwargs)
                finally:
                    depth.n -= 1
                    if frozen:
                        adapter._now = None  # noqa: SLF001
            if outer:
                try:
                    journal.append(
                        {
                            "at": at.isoformat(),
                            "action": name,
                            "args": _enc(list(args)),
                            "kwargs": {k: _enc(v) for k, v in kwargs.items()},
                        }
                    )
                except Exception:  # noqa: BLE001 — the action happened; say the save failed
                    log.error("sandbox journal: could not record %s", name, exc_info=True)
            return result

        return recorded

    for name, fn in originals.items():
        setattr(adapter, name, wrap(name, fn))
    if replayed:
        log.info("sandbox journal: %d action(s) replayed", replayed)
    return replayed
