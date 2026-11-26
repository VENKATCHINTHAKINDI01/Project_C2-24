"""ADR-0071: the officers' sandbox actions survive a restart (journal replayed at start-up)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


def _app(path: Path) -> TestClient:
    s = get_settings().model_copy(
        update={"sandbox": True, "sandbox_journal": "file", "sandbox_journal_path": path}
    )
    return TestClient(create_app(s))


def test_files_notes_moves_and_issued_orders_come_back_after_a_restart(tmp_path: Path) -> None:
    j = tmp_path / "journal.jsonl"
    with _app(j) as c:
        f = c.post("/sandbox/files", json={"subject": "Journal check — transfer on spouse grounds",
                   "previous_references": []}, headers=_h("U01")).json()["file"]  # fmt: skip
        cno = f["computer_no"]
        c.post(f"/sandbox/files/{cno}/notes", json={"text": "1. Request received."},
               headers=_h("U01"))  # fmt: skip
        c.post(f"/sandbox/files/{cno}/move", json={"to_user": "U02", "remarks": "For orders."},
               headers=_h("U01"))  # fmt: skip
        before = c.get(f"/sandbox/files/{cno}", headers=_h("U02")).json()
    assert j.is_file() and len(j.read_text("utf-8").splitlines()) == 3  # create, note, send

    with _app(j) as c:  # a new instance: same seed, journal replayed
        after = c.get(f"/sandbox/files/{cno}", headers=_h("U02")).json()
        assert after["file"]["with_me"] is True
        assert [n["text"] for n in after["notes"]] == [n["text"] for n in before["notes"]]
        assert [(m["to_user"], m["remarks"]) for m in after["movements"]] == [
            ("U02", "For orders.")
        ]
        assert after["movements"][0]["sent_at"] == before["movements"][0]["sent_at"]
        # new actions are recorded after the replayed ones
        c.post(f"/sandbox/files/{cno}/move", json={"to_user": "U01", "remarks": "Seen."},
               headers=_h("U02"))  # fmt: skip
    assert len(j.read_text("utf-8").splitlines()) == 4


def test_a_record_that_no_longer_applies_is_skipped(tmp_path: Path) -> None:
    j = tmp_path / "journal.jsonl"
    rec = {"at": "2026-10-02T05:00:00+00:00", "action": "write_note",
           "args": ["999999", "U01", "x"], "kwargs": {}}  # fmt: skip
    j.write_text(json.dumps(rec) + "\n", "utf-8")
    with _app(j) as c:
        assert c.get("/sandbox/profiles").status_code == 200  # started anyway
