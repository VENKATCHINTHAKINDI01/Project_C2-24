"""Extended touchpoints 1, 5, 12, 16, 17, 18, 19 — end to end through the mock e-Office sandbox
(plan §11.5, §13.2; CLAUDE.md §9.3 "each touchpoint end to end in the sandbox"; ADR-0038).

Each scenario runs against a fresh sandbox app (some of them close files or confirm OCR text) over
HTTP, exactly as the screens call it, signed in as the scenario's officer. Expectations come from
the answer key (`touchpoint_scenarios.json`) and the seed; the application never reads either.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import get_settings
from app.identifiers.canonical import efile_document_id
from app.main import create_app

CORPUS = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "mock_v1"
EXTENDED = (1, 5, 12, 16, 17, 18, 19)


def _seed() -> Any:
    return json.loads((CORPUS / "eoffice" / "seed.json").read_text("utf-8"))


def _d_of() -> dict[str, str]:
    """canonical ID → D-number (documents_index.csv); suffixed IDs map to their base's D."""
    with (CORPUS / "documents_index.csv").open(encoding="utf-8") as fh:
        return {r["canonical_id"]: r["id"] for r in csv.DictReader(fh)}


def _words(v: str | None) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", (v or "").lower()).split()


def _h(uid: str) -> dict[str, str]:
    return {"X-Sandbox-User": uid}


def _app() -> TestClient:
    return TestClient(create_app(get_settings().model_copy(update={"sandbox": True})))


def _tp01(sc: dict[str, Any], c: TestClient) -> dict[str, Any]:
    exp = sc["expected"]
    fields = exp["fields"]
    right, total, wrong, ocr = 0, 0, [], 0
    for r in _seed()["receipts"]:
        j = c.post(
            "/assist/diarise", json={"computer_no": r["computer_no"]}, headers=_h(sc["user"])
        )
        p = j.json().get("prefill") or {}
        ocr += bool(p.get("from_ocr"))
        for f in fields:
            total += 1
            got = (p.get(f) or {}).get("value")
            if _words(got) == _words(r[f]):
                right += 1
            else:
                wrong.append({"receipt": r["computer_no"], "field": f, "got": got, "want": r[f]})
    o = exp["outsider"]
    hidden = c.post("/assist/diarise", json={"computer_no": o["receipt"]}, headers=_h(o["user"]))
    unknown = c.post("/assist/diarise", json={"computer_no": "9199999"}, headers=_h(o["user"]))
    same_404 = hidden.status_code == unknown.status_code == 404 and hidden.json() == unknown.json()
    return {
        "run": True,
        "pass": right == total and same_404,
        "field_accuracy": round(right / total, 3) if total else None,
        "fields_checked": total,
        "read_by_ocr": ocr,
        "wrong": wrong[:10],
        "outsider_same_404": same_404,
        "note": f"{right}/{total} diary fields equal the diary entry; {ocr} letters read by OCR",
    }


def _tp05(sc: dict[str, Any], c: TestClient) -> dict[str, Any]:
    exp = sc["expected"]
    j = c.post(
        "/assist/previous-references",
        json={"subject": sc["context"]["subject"]},
        headers=_h(sc["user"]),
    ).json()
    got = [s["computer_no"] for s in j["suggestions"]]
    want, forbid = set(exp["files"]), set(exp["forbidden_files"])
    d_of = _d_of()
    docs = {
        d_of.get(d["canonical_id"], d["canonical_id"])
        for s in j["suggestions"]
        for d in s["documents"]
    }
    return {
        "run": True,
        "pass": want <= set(got)
        and not forbid & set(got)
        and not set(exp["forbidden_docs"]) & docs,
        "expected_files": sorted(want),
        "suggested": got,
        "precision": round(len(want & set(got)) / len(got), 3) if got else None,
        "note": f"{len(want & set(got))}/{len(want)} expected files offered among {len(got)}",
    }


def _tp12(sc: dict[str, Any], c: TestClient) -> dict[str, Any]:
    exp = sc["expected"]
    j = c.post(
        "/assist/movements",
        json={"computer_no": sc["context"]["computer_no"]},
        headers=_h(sc["user"]),
    ).json()
    steps = j.get("steps", [])
    remarks = [s["remarks"] for s in steps]
    notes = [[n["note_no"] for n in s["notes"]] for s in steps]
    last = (j.get("last_direction") or {}).get("note_no")
    ok = (
        len(steps) == exp["movements"]
        and remarks == exp["remarks"]
        and notes == exp["notes_put_up"]
        and last == exp["last_direction"]
        and j.get("state") == exp["state"]
        and (j.get("pending_with") is None) == (exp["state"] == "closed")
    )
    return {
        "run": True,
        "pass": ok,
        "remarks": remarks,
        "notes_put_up": notes,
        "last_direction": last,
        "headline": j.get("headline"),
    }


def _tp16(sc: dict[str, Any], c: TestClient) -> dict[str, Any]:
    exp, ctx = sc["expected"], sc["context"]
    cr = c.post(
        "/assist/closing-remarks", json={"computer_no": ctx["computer_no"]}, headers=_h(sc["user"])
    ).json()
    nh = exp["not_holder"]
    other = c.post(
        "/assist/closing-remarks", json={"computer_no": nh["computer_no"]}, headers=_h(nh["user"])
    ).json()
    q = {"query": ctx["search"]}

    def found(uid: str) -> set[str]:
        return {
            d["canonical_id"]
            for d in c.post("/assist/search", json=q, headers=_h(uid)).json()["documents"]
        }

    before = {u: found(u) for u in (*exp["joins_index"]["finds"], *exp["joins_index"]["never"])}
    closed = c.post(
        f"/sandbox/files/{ctx['computer_no']}/close",
        json={"remarks": ctx["remarks"]},
        headers=_h(sc["user"]),
    )
    base = efile_document_id(exp["joins_index"]["file_no"], "NOTE")
    new_for = {u: {x for x in found(u) - before[u] if x.startswith(base)} for u in before}
    blocked = c.post(
        f"/sandbox/files/{nh['computer_no']}/close",
        json={"remarks": "closing"},
        headers=_h(nh["user"]),
    ).status_code
    ok = (
        bool(cr.get("can_close")) == exp["can_close"][sc["user"]]
        and bool(cr.get("text"))
        and bool(cr.get("cited"))
        and not other.get("can_close")
        and blocked == 404
        and closed.status_code == 200
        and all(new_for[u] for u in exp["joins_index"]["finds"])
        and not any(new_for[u] for u in exp["joins_index"]["never"])
    )
    return {
        "run": True,
        "pass": ok,
        "remarks": cr.get("text"),
        "blockers_other": other.get("blockers"),
        "newly_found": {u: sorted(v) for u, v in new_for.items()},
    }


def _tp17(sc: dict[str, Any], c: TestClient) -> dict[str, Any]:
    exp = sc["expected"]
    j = c.post(
        "/assist/since-decision",
        json={"computer_no": sc["context"]["computer_no"]},
        headers=_h(sc["user"]),
    ).json()
    d_of = _d_of()
    got = [
        {
            "cited": d_of.get(x["cited"], x["cited"]),
            "change": x["change"],
            "by": d_of.get(x["by"] or "", x["by"]),
        }
        for x in j.get("changes", [])
        if x["after_decision"]
    ]
    ok = (
        (j.get("decided") or {}).get("note_no") == exp["decided_note"]
        and j.get("decided_on") == exp["decided_on"]
        and sorted(got, key=lambda g: (g["cited"], g["by"] or ""))
        == sorted(exp["changed_since"], key=lambda g: (g["cited"], g["by"] or ""))
    )
    return {"run": True, "pass": ok, "changed_since": got, "headline": j.get("headline")}


def _tp18(sc: dict[str, Any], c: TestClient) -> dict[str, Any]:
    exp, ctx = sc["expected"], sc["context"]
    q = {"query": ctx["search"]}

    def found(uid: str) -> set[str]:
        return {
            d["canonical_id"]
            for d in c.post("/assist/search", json=q, headers=_h(uid)).json()["documents"]
        }

    before = found(sc["user"])
    items = c.get("/assist/review/ocr", headers=_h(sc["user"])).json()["items"]
    item = next((i for i in items if i["filename"].startswith(ctx["scan"] + "_")), None)
    if item is None:
        return {"run": True, "pass": False, "why": "scan not in the reviewer's queue"}
    hidden_queue = any(
        i["filename"].startswith(ctx["scan"] + "_")
        for u in exp["after_review"]["never"]
        for i in c.get("/assist/review/ocr", headers=_h(u)).json()["items"]
    )
    text = c.get(f"/assist/review/ocr/{item['item_id']}", headers=_h(sc["user"])).json()[
        "draft_text"
    ]
    res = c.post(
        f"/assist/review/ocr/{item['item_id']}/confirm",
        json={"reason": "checked against the scan", "corrected_text": text},
        headers=_h(sc["user"]),
    ).json()
    cid = res.get("canonical_id")
    chain = c.post(
        "/assist/file-so-far", json={"computer_no": ctx["computer_no"]}, headers=_h(sc["user"])
    ).json()
    nos = [n["note_no"] for n in chain.get("notes", [])]
    ok = (
        cid is not None
        and cid not in before
        and all(cid in found(u) for u in exp["after_review"]["finds"])
        and not any(cid in found(u) for u in exp["after_review"]["never"])
        and not hidden_queue
        and all(n in nos for n in exp["notes_join_chain"])
    )
    return {
        "run": True,
        "pass": ok,
        "indexed_as": cid,
        "status": res.get("status"),
        "note_chain": nos,
        "queue_hidden_from_others": not hidden_queue,
    }


def _tp19(sc: dict[str, Any], c: TestClient) -> dict[str, Any]:
    exp = sc["expected"]
    j = c.get("/assist/handover", headers=_h(sc["user"])).json()
    d_of = _d_of()
    in_hand = {f["computer_no"] for f in j.get("in_hand", [])}
    decided = {d["computer_no"] for d in j.get("decisions", [])}
    gone = [
        {
            "cited": d_of.get(o["canonical_id"], o["canonical_id"]),
            "change": o["status"],
            "by": d_of.get(o["by"] or "", o["by"]),
        }
        for o in j.get("no_longer_in_force", [])
    ]
    text = json.dumps(j)
    ok = (
        set(exp["files"]) == in_hand
        and set(exp["decisions"]) == decided
        and not any(f in text for f in exp["forbidden_files"])
        # exactly the cited orders that changed: none missing, none extra (owner review 15 Nov)
        and sorted(gone, key=lambda g: g["cited"])
        == sorted(exp["no_longer_in_force"], key=lambda g: g["cited"])
    )
    return {
        "run": True,
        "pass": ok,
        "in_hand": sorted(in_hand),
        "decisions": sorted(decided),
        "no_longer_in_force": gone,
        "headline": j.get("headline"),
    }


RUNNERS: dict[int, Callable[[dict[str, Any], TestClient], dict[str, Any]]] = {
    1: _tp01,
    5: _tp05,
    12: _tp12,
    16: _tp16,
    17: _tp17,
    18: _tp18,
    19: _tp19,
}


def run_extended(sc: dict[str, Any]) -> dict[str, Any]:
    """One extended scenario on a fresh sandbox (closing a file / confirming OCR change state)."""
    with _app() as c:
        return RUNNERS[sc["touchpoint"]](sc, c)
