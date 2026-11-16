"""OCR review screen API (plan §4.2, §9.1; CLAUDE.md §4.7, §8; ADR-0014 rule 4, ADR-0016).

The sandbox replays recorded Document AI v2.1.1 output for the synthetic scans. Every scan waits
for a reviewer. These tests check:
- the queue shows only the scans the officer may see;
- a hidden item answers exactly like an unknown one;
- confirming indexes the scan through the pipeline, under the scan's own version;
- a correction is what gets indexed;
- a reject keeps the file held;
- every decision is audited with IDs only.

Each test gets a fresh app, because reviews change state.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.messages import REVIEW_ITEM_NOT_AVAILABLE
from app.config import get_settings
from app.main import create_app
from tests.unit.mock_access import CORPUS, MATRIX, rows

SEED = json.loads((CORPUS / "eoffice" / "seed.json").read_text("utf-8"))
USERS = [p["user_id"] for p in SEED["profiles"] if p["login"]]
DOC_OF = {Path(r["file"]).name: r["id"] for r in rows("documents_index.csv")}
SCANS = {"D01", "D02", "D09", "D11", "D13", "D15", "D16", "D22"}
UNKNOWN = "RV-999999"


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(get_settings().model_copy(update={"sandbox": True}))
    with TestClient(app) as c:
        yield c


def _queue(c: TestClient, uid: str) -> dict[str, str]:
    """doc id → review item id, as this officer's queue shows it."""
    items = c.get("/assist/review/ocr", headers=_h(uid)).json()["items"]
    return {DOC_OF[i["filename"]]: i["item_id"] for i in items}


def test_queue_shows_exactly_the_scans_each_officer_may_see(client: TestClient) -> None:
    for uid in USERS:
        shown = set(_queue(client, uid))
        assert shown == {d for d in SCANS if MATRIX[(d, uid)]}, uid


def test_a_hidden_item_answers_exactly_like_an_unknown_one(client: TestClient) -> None:
    hidden = _queue(client, "U04")["D22"]  # Vigilance note: U04 may see it, U01 may not
    body = {"reason": "checked against the scan"}
    for method, suffix in (
        ("get", ""),
        ("get", "/scan"),
        ("post", "/confirm"),
        ("post", "/reject"),
    ):
        kw = {"json": body} if method == "post" else {}
        a = getattr(client, method)(f"/assist/review/ocr/{hidden}{suffix}", headers=_h("U01"), **kw)
        b = getattr(client, method)(
            f"/assist/review/ocr/{UNKNOWN}{suffix}", headers=_h("U01"), **kw
        )
        assert a.status_code == b.status_code == 404 and a.content == b.content, suffix
        assert a.json() == {"detail": REVIEW_ITEM_NOT_AVAILABLE}
    assert hidden in _queue(client, "U04").values()  # nothing was decided by the refused calls


def test_detail_has_the_ocr_text_and_the_scan_itself(client: TestClient) -> None:
    item = _queue(client, "U03")["D16"]
    d = client.get(f"/assist/review/ocr/{item}", headers=_h("U03")).json()
    assert d["has_draft"] and "ఆంధ్రప్రదేశ్ ప్రభుత్వము" in d["draft_text"]
    assert d["engine"].endswith("pretrained-ocr-v2.1.1-2025-01-31")
    assert d["pages"][0]["confidence"] > 0.9 and "te" in d["pages"][0]["languages"]
    scan = client.get(f"/assist/review/ocr/{item}/scan", headers=_h("U03"))
    on_disk = next(CORPUS / r["file"] for r in rows("documents_index.csv") if r["id"] == "D16")
    assert scan.status_code == 200 and scan.content == on_disk.read_bytes()
    assert scan.headers["cache-control"] == "private, no-store"


def test_confirming_indexes_the_scan_and_it_becomes_citable(client: TestClient) -> None:
    item = _queue(client, "U01")["D09"]
    r = client.post(
        f"/assist/review/ocr/{item}/confirm",
        json={"reason": "OCR matches the scan"},
        headers=_h("U01"),
    ).json()
    assert r["status"] == "indexed" and r["canonical_id"] == "AP-GAD01-GOMS-19-2018"
    assert r["corrected"] is False
    assert "D09" not in _queue(client, "U01")  # decided: gone from every queue
    doc = client.get("/assist/documents/AP-GAD01-GOMS-19-2018/preview", headers=_h("U07"))
    assert doc.status_code == 200 and doc.content.startswith(b"%PDF")  # the scan is served
    events = [
        e
        for e in cast(FastAPI, client.app).state.audit.events()
        if e.action == "assist.review.confirm"
    ]
    assert (events[-1].user_id, events[-1].outcome) == ("U01", "indexed")
    assert set(events[-1].ids) == {item, "AP-GAD01-GOMS-19-2018"}  # IDs only, no text


def test_misread_marker_unchanged_stays_held_for_the_unresolved_reference(
    client: TestClient,
) -> None:
    item = _queue(client, "U03")["D16"]
    r = client.post(
        f"/assist/review/ocr/{item}/confirm", json={"reason": "text looks fine"}, headers=_h("U03")
    ).json()
    assert r["status"] == "held" and r["canonical_id"] is None
    assert [h["kind"] for h in r["still_held_for"]] == ["unresolved_reference"]


def test_reviewer_correction_is_what_gets_indexed(client: TestClient) -> None:
    """D16: OCR read the Telugu marker ఆర్.సి.నెం. as "5.2.3." and తేది as "3໖". The reviewer fixes
    both against the scan; the corrected text resolves the Rc. number."""
    item = _queue(client, "U03")["D16"]
    draft = client.get(f"/assist/review/ocr/{item}", headers=_h("U03")).json()["draft_text"]
    line = next(x for x in draft.splitlines() if "USD01-WRKS0/22/2025" in x)
    fixed = draft.replace(line, "ఆర్.సి.నెం. USD01-WRKS0/22/2025, తేది: 02.06.2025")
    r = client.post(
        f"/assist/review/ocr/{item}/confirm",
        json={"reason": "corrected the Rc. No. marker against the scan", "corrected_text": fixed},
        headers=_h("U03"),
    ).json()
    assert r["status"] == "indexed" and r["corrected"] is True
    assert r["canonical_id"] == "AP-USD01-RC-USD01WRKS0-22-2025-D20250602"


def test_reject_keeps_the_file_held_and_records_why(client: TestClient) -> None:
    item = _queue(client, "U01")["D09"]
    r = client.post(
        f"/assist/review/ocr/{item}/reject",
        json={"reason": "page cut off; needs a re-scan"},
        headers=_h("U01"),
    )
    assert r.json()["status"] == "rejected"
    assert "D09" not in _queue(client, "U01")
    doc = client.get("/assist/documents/AP-GAD01-GOMS-19-2018", headers=_h("U01"))
    assert doc.status_code == 404  # never indexed


def test_a_reason_is_required(client: TestClient) -> None:
    item = _queue(client, "U01")["D09"]
    r = client.post(f"/assist/review/ocr/{item}/confirm", json={"reason": ""}, headers=_h("U01"))
    assert r.status_code == 422
