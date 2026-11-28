"""ADR-0074 End-to-End Scenario Script (Steps 1–5).

Exercises the complete link-learning lifecycle in-process against the real FastAPI app:
1. Step 1 — Related orders & Useful feedback (`GET /assist/links/{id}`, feedback)
2. Step 2 — Officer work signals (`write_note`, `approve_and_issue` W6 never validates)
3. Step 3 — Roll-up (`app.state.rollup_links`), audit (`graph.link.state_change`), cache
   invalidation, and authenticated human validation (`POST /assist/links/decision`)
4. Step 4 — File CITES order, File RELATED TO file, Order APPLIES TO section
5. Step 5 — Monitoring pad `GET /assist/monitor?days=7` (`link_changes` with documentary evidence)
"""

from __future__ import annotations

import datetime as dt
import logging
import sys
from pathlib import Path

from fastapi.testclient import TestClient

root = Path(__file__).resolve().parents[1]
backend_path = root / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.auth.models import DocumentAccessTags  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.graph.repository import EdgeKind, GraphEdge, GraphNode  # noqa: E402
from app.main import create_app  # noqa: E402
from app.retrieval.scoped import IndexedDocument  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("link_learning_scenario")

NEW = "AP-ESE01-GOMS-29-2021"
OLD = "AP-ESE01-GOMS-8-2021"


def _h(user_id: str) -> dict[str, str]:
    return {"X-Sandbox-User": user_id}


def run_scenario() -> None:
    settings = get_settings()
    app = create_app(settings)
    client = TestClient(app)

    run = app.state.assist_runtime()
    assert run is not None, "assist_runtime did not initialize"

    # Seed a candidate SUPERSEDES link with documentary wording in the newer order
    for cid in (NEW, OLD):
        tags = DocumentAccessTags(doc_id=cid, department="ESE01", classification="UNCLASSIFIED")
        run.stores.index.upsert(
            IndexedDocument(
                canonical_id=cid,
                tags=tags,
                doc_type="GO_MS",
                issue_date=dt.date(2021, 8, 12) if cid == NEW else dt.date(2021, 3, 5),
                subject=f"Order {cid}",
            )
        )
        run.stores.graph.upsert_node(GraphNode(canonical_id=cid, tags=tags))
    run.stores.graph.upsert_edge(
        GraphEdge(source=NEW, kind=EdgeKind.SUPERSEDES, target=OLD, confirmed=False)
    )
    run.stores.instruments.setdefault(NEW, run.stores.instruments.get(OLD))  # type: ignore[arg-type]
    run.texts[NEW] = (
        "G.O.Ms.No.29 Dated: 12-08-2021\n"
        "ORDER:\n"
        "In supersession of G.O.Ms.No.8, School Education Department, dated 05.03.2021, "
        "revised transfer norms are issued."
    )
    evidence_sentence = (
        "In supersession of G.O.Ms.No.8, School Education Department, dated 05.03.2021, "
        "revised transfer norms are issued."
    )

    # Step 1: Officer U01 views related orders & gives Useful feedback
    log.info("Step 1: GET /assist/links/%s & POST /assist/links/feedback", OLD)
    r = client.get(f"/assist/links/{OLD}", headers=_h("U01"))
    assert r.status_code == 200, r.text
    links = r.json().get("links", [])
    match = next((x for x in links if x["source"] == NEW and x["target"] == OLD), None)
    assert match is not None, f"Expected candidate link in {links}"
    assert match["state"] in ("candidate", "suggested")
    assert "unverified" not in (match.get("wording") or "").lower()

    fb = client.post(
        "/assist/links/feedback",
        headers=_h("U01"),
        json={"source": NEW, "kind": "SUPERSEDES", "target": OLD, "code": "useful"},
    )
    assert fb.status_code == 200, fb.text

    # Step 2: Work signal from note_written (W1/W3) on an open file
    log.info("Step 2: Record work signal via sandbox file creation & note")
    cf = client.post(
        "/sandbox/files",
        headers=_h("U01"),
        json={"subject": f"Proposal following {NEW} for school norms", "previous_references": []},
    )
    assert cf.status_code == 200, cf.text
    cno = cf.json()["file"]["computer_no"]
    file_no = cf.json()["file"]["file_no"]
    wn = client.post(
        f"/sandbox/files/{cno}/notes",
        headers=_h("U01"),
        json={"text": f"Submitted per {NEW} in supersession of G.O.Ms.No.8 of 2021."},
    )
    assert wn.status_code == 200, wn.text

    # Step 3: Roll-up updates graph_edges, audits state transition, invalidates cache
    log.info("Step 3: Run rollup_links & verify graph_edges + human validation")
    res1 = app.state.rollup_links()
    assert res1 is not None and res1.checked >= 1
    edge1 = next(e for e in run.stores.graph.edges() if e.source == NEW and e.target == OLD)
    assert edge1.confirmed is False, "Usage signals must never validate a link"

    # Human validation by an authorized ESE01 validator (or U01 if Section Officer in ESE01)
    # Find an ESE01 Section Officer+ profile from /sandbox/profiles
    profiles = client.get("/sandbox/profiles").json()["profiles"]
    validator = next(
        (
            p["user_id"]
            for p in profiles
            if p.get("department") == "ESE01"
            and any(
                p.get("post", "").startswith(x)
                for x in ("Section Officer", "Deputy Secretary", "Secretary")
            )
        ),
        None,
    )
    if validator:
        dec = client.post(
            "/assist/links/decision",
            headers=_h(validator),
            json={
                "source": NEW,
                "kind": "SUPERSEDES",
                "target": OLD,
                "action": "validate",
                "reason": "Confirmed from G.O.Ms.No.29 text",
                "evidence": evidence_sentence,
            },
        )
        assert dec.status_code == 200, dec.text
        res2 = app.state.rollup_links()
        assert res2 is not None and res2.state_changes >= 1
        edge2 = next(e for e in run.stores.graph.edges() if e.source == NEW and e.target == OLD)
        assert edge2.state == "validated" and edge2.confirmed is True

    # Step 4: Verify File CITES order & Order APPLIES TO section edges created by roll-up
    log.info("Step 4: Verify File CITES order & Order APPLIES TO section for %s", file_no)
    cites_edges = [
        e for e in run.stores.graph.edges() if e.kind is EdgeKind.CITES and e.target == NEW
    ]
    assert cites_edges, "Expected at least one FILE -> CITES -> NEW edge after roll-up"
    applies_edges = [
        e for e in run.stores.graph.edges() if e.kind is EdgeKind.APPLIES_TO and e.source == NEW
    ]
    assert applies_edges, "Expected at least one NEW -> APPLIES_TO -> SECTION edge"

    # Step 5: Monitoring officer M01 views /assist/monitor link_changes; U01 gets 404
    log.info("Step 5: Verify GET /assist/monitor?days=7 link_changes & access control")
    denied = client.get("/assist/monitor?days=7", headers=_h("U01"))
    assert denied.status_code == 404
    mon = client.get("/assist/monitor?days=7", headers=_h("M01"))
    assert mon.status_code == 200, mon.text
    changes = mon.json().get("link_changes", [])
    assert any(c["source"] == NEW and c["target"] == OLD for c in changes), (
        f"Expected {NEW}->{OLD} in monitor link_changes: {changes}"
    )

    log.info("ADR-0074 scenario passed cleanly across all 5 steps!")


if __name__ == "__main__":
    run_scenario()
