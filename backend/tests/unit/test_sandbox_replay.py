"""Touchpoint 4 through the running app (plan §11.5, §7.2, §7.3): with the "tp04" replay,
G.O.Ms.31/2025 is held back at startup; when the letter arrives, ingestion reconciles it and
officers see a notice for their OPEN files that cite the superseded order."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

APP = create_app(get_settings().model_copy(update={"sandbox": True, "sandbox_replay": "tp04"}))


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        yield c


def _notices(c: TestClient, uid: str) -> list[dict]:  # type: ignore[type-arg]
    return list(c.get("/assist/notices", headers=_h(uid)).json()["notices"])


def test_order_arrives_and_open_files_are_notified(client: TestClient) -> None:
    assert _notices(client, "U02") == []  # nothing before the letter arrives
    ref = client.post("/assist/reference", json={"text": "G.O.Ms.No.88/2022"}, headers=_h("U06"))
    assert ref.json()["status"] != "superseded"  # 31/2025 not in the records yet
    pending = [
        r["computer_no"]
        for r in client.get("/sandbox/receipts", headers=_h("U02")).json()["receipts"]
        if r["letter_pending"]
    ]
    assert pending == ["9100009"]
    assert client.post("/sandbox/receipts/9100009/arrive", headers=_h("U03")).status_code == 404
    ev = client.post("/sandbox/receipts/9100009/arrive", headers=_h("U02")).json()
    assert ev["kind"] == "order_received"

    (n,) = _notices(client, "U02")
    assert n["change"] == "SUPERSEDES"
    assert (n["new"]["canonical_id"], n["changed"]["canonical_id"]) == (
        "AP-FIN01-GOMS-31-2025",
        "AP-FIN01-GOMS-88-2022",
    )
    assert [f["file_no"] for f in n["files"]] == ["USD01-12/19/2026-ESTT.I"]  # open file only
    assert [f["file_no"] for x in _notices(client, "U01") for f in x["files"]] == [
        "USD01-12/19/2026-ESTT.I"
    ]
    assert _notices(client, "U03") == [] and _notices(client, "U07") == []  # Works / Finance

    # explicit supersession is applied directly (plan §7.3): the status flips
    after = client.post("/assist/reference", json={"text": "G.O.Ms.No.88/2022"}, headers=_h("U01"))
    assert after.json()["status"] == "superseded" and after.json()["by"] == "AP-FIN01-GOMS-31-2025"
    again = client.post("/sandbox/receipts/9100009/arrive", headers=_h("U02"))
    assert again.status_code == 404  # arrives once
