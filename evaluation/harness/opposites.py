"""Opposite scenarios (`ground_truth/opposite_scenarios.json`): for each touchpoint, the case where
the correct output is the reverse — no access, nothing to find, nothing wrong, an order in force.

Run through the sandbox HTTP API (as the officer sees it), not the evaluation stack: access must be
judged on the real responses, including that a hidden record answers exactly like a missing one.
The sandbox has no OCR; the scenarios were written not to depend on a scan's text.
EVALUATION ONLY (CLAUDE.md §9.2).
"""

from __future__ import annotations

import csv
import json
from functools import cache
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app

CORPUS = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "mock_v1"
SCENARIOS = CORPUS / "ground_truth" / "opposite_scenarios.json"


@cache
def _cid() -> dict[str, str]:
    with (CORPUS / "documents_index.csv").open(encoding="utf-8") as fh:
        return {r["id"]: r["canonical_id"] for r in csv.DictReader(fh)}


def _client(replay: str | None) -> TestClient:
    upd: dict[str, Any] = {"sandbox": True, "sandbox_replay": replay}
    return TestClient(create_app(get_settings().model_copy(update=upd)))


def _call(c: TestClient, user: str, call: list[Any]) -> tuple[int, Any]:
    method, path, body = call
    h = {"X-Sandbox-User": user}
    r = c.get(path, headers=h) if method == "GET" else c.post(path, json=body, headers=h)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def _strip(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _strip(v) for k, v in x.items() if k != "request_id"}
    if isinstance(x, list):
        return [_strip(v) for v in x]
    return x


def _path(x: Any, dotted: str) -> list[Any]:
    """'flags.*.type' → every flag's type; 'cited_clause.clause_id' → [value] (missing → [None])."""
    vals = [x]
    for part in dotted.split("."):
        nxt: list[Any] = []
        for v in vals:
            if part == "*" and isinstance(v, list):
                nxt += v
            elif isinstance(v, dict):
                nxt.append(v.get(part))
            else:
                nxt.append(None)
        vals = nxt
    return vals


def _check(c: TestClient, sc: dict[str, Any], code: int, body: Any) -> list[str]:
    exp, problems = sc["expect"], []
    text = json.dumps(body, ensure_ascii=False)
    if same := exp.get("same_as_unknown"):
        method, path, req = sc["call"]
        if "path" in same:  # GET by ID (ADR-0014 documents): the unknown record's path
            code2, body2 = _call(c, sc["user"], [method, same["path"], req])
        else:
            code2, body2 = _call(c, sc["user"], [method, path, {**req, **same}])
        if (code, _strip(body)) != (code2, _strip(body2)):
            problems.append(f"differs from an unknown record: {code} {body!r} vs {code2} {body2!r}")
        return problems
    if code != 200:
        return [f"HTTP {code}: {body!r}"]
    problems += [f"names {d}" for d in exp.get("never_docs", []) if _cid()[d] in text]
    problems += [f"does not name {d}" for d in exp.get("must_docs", []) if _cid()[d] not in text]
    if "flag_types" in exp:
        got = sorted({f["type"] for f in body.get("flags", [])})
        if got != sorted(exp["flag_types"]):
            problems.append(f"flags {got}, expected {exp['flag_types']}")
    if "certain_flags" in exp:
        got = sorted({f["type"] for f in body.get("flags", []) if f.get("certain")})
        if got != sorted(exp["certain_flags"]):
            problems.append(f"certain flags {got}, expected {exp['certain_flags']}")
    for field in exp.get("empty", []):
        if body.get(field):
            problems.append(f"{field} not empty: {len(body[field])}")
    for k, v in exp.get("equals", {}).items():
        if any(x != v for x in _path(body, k)):
            problems.append(f"{k} = {_path(body, k)}, expected {v!r}")
    for k, v in exp.get("not_equals", {}).items():
        if v in _path(body, k):
            problems.append(f"{k} has {v!r}")
    if exp.get("no_in_place_of"):
        listed = body.get("read_list") or body.get("orders") or []
        if any(i.get("in_place_of") for i in listed):
            problems.append("an order is marked 'in place of' a cited order")
    return problems


def run_opposites(path: Path = SCENARIOS) -> dict[str, Any]:
    spec = json.loads(path.read_text("utf-8"))
    rows: list[dict[str, Any]] = []
    plain = _client(None)
    with plain:
        for sc in spec["scenarios"]:
            if sc.get("replay"):
                with _client(sc["replay"]) as rc:
                    if sc.get("arrive"):
                        rc.post(
                            f"/sandbox/receipts/{sc['arrive']}/arrive",
                            headers={"X-Sandbox-User": "U02"},
                        )
                    code, body = _call(rc, sc["user"], sc["call"])
                    problems = _check(rc, sc, code, body)
            else:
                code, body = _call(plain, sc["user"], sc["call"])
                problems = _check(plain, sc, code, body)
            rows.append(
                {
                    "id": sc["id"],
                    "mirrors": sc["mirrors"],
                    "user": sc["user"],
                    "call": f"{sc['call'][0]} {sc['call'][1]}",
                    "pass": not problems,
                    "problems": problems,
                    "basis": sc["basis"],
                }
            )
    return {
        "summary": {
            "scenarios": len(rows),
            "passed": sum(r["pass"] for r in rows),
            "status": spec["status"],
            "where": "sandbox HTTP API (no OCR)",
        },
        "scenarios": rows,
    }
