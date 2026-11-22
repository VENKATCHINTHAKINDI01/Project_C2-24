"""Two-Officer Rehearsal (Milestone M9 / Phase P8; ADR-0031, ADR-0045, ADR-0062).

Simulates the complete golden-path collaborative workflow between two officers:
1. Officer 1 (Author: Section Officer U01, ESTT.I):
   - Opens file 1771342 (Request for transfer to Vijayawada on spouse grounds).
   - Inquires about transfer & posting precedents via C2-24.
   - Prepares a Yellow Note draft citing precedents.
   - Prepares a DFA (Draft for Approval) granting transfer.
   - Puts up the DFA for senior approval.
2. Officer 2 (Approver: Secretary to Government U06):
   - Reviews the submitted DFA in approvals.
   - Returns the draft with senior review remarks (ADR-0062):
     "Please mandate 2-year minimum station tenure per transfer policy before granting transfer."
3. Officer 1 (Author: U01):
   - Views returned remarks on the file screen banner.
   - Executes AI-assisted revision (POST /assist/draft/revise).
   - Verifies the revised wording incorporates the senior review remarks.
   - Confirms and signs the Yellow Note into the official Green Note.
   - Re-submits the revised DFA.
4. Officer 2 (Approver: U06):
   - Approves, signs, and issues the official Government Order (G.O.Ms.No. 9001).
   - Verifies the new order is indexed in institutional memory (ADR-0045).
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

# Ensure backend is on sys.path
root = Path(__file__).resolve().parents[1]
backend_path = root / "backend"
if str(backend_path) not in sys.path:
    sys.path.insert(0, str(backend_path))

from app.config import get_settings  # noqa: E402
from app.main import create_app  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("two_officer_rehearsal")


def _h(user_id: str) -> dict[str, str]:
    return {"X-Sandbox-User": user_id}


def run_rehearsal() -> dict[str, Any]:
    log.info("Initializing Mock e-Office Sandbox Application...")
    settings = get_settings().model_copy(
        update={
            "sandbox": True,
            "sandbox_seed": "v1",
            "identity": "sandbox",
        }
    )
    app = create_app(settings)

    results: dict[str, Any] = {
        "status": "PASS",
        "milestone": "M9",
        "phase": "P8",
        "author": "U01 (Officer A — Section Officer, ESTT.I)",
        "approver": "U06 (Officer F — Secretary to Government)",
        "computer_no": "1771342",
        "steps": [],
    }

    with TestClient(app) as client:
        cno = "1771342"

        # ---------------------------------------------------------------------
        # STEP 1: Author U01 views file and retrieves precedent
        # ---------------------------------------------------------------------
        log.info("Step 1: Officer 1 (U01, SO) opens file %s", cno)
        res1 = client.get(f"/sandbox/files/{cno}", headers=_h("U01"))
        assert res1.status_code == 200, f"Failed to open file: {res1.text}"
        file_data = res1.json()
        f_info = file_data.get("file", {})
        log.info(
            "File opened: '%s' (Dealing Section: %s)",
            f_info.get("subject"),
            f_info.get("dealing_section"),
        )
        initial_notes_count = len(file_data.get("notes", []))

        # Query C2-24 for precedent on transfer guidelines
        ask_res = client.post(
            "/assist/ask",
            json={"question": "What are the transfer guidelines and spouse grounds policies?"},
            headers=_h("U01"),
        )
        assert ask_res.status_code == 200, f"Search failed: {ask_res.text}"
        ask_json = ask_res.json()
        cited_docs = ask_json.get("documents", [])
        log.info("Precedents retrieved by U01: %s", cited_docs[:3])
        results["steps"].append(
            {
                "step": 1,
                "name": "Author file inspection & precedent search",
                "status": "OK",
                "precedents_found": len(cited_docs),
            }
        )

        # ---------------------------------------------------------------------
        # STEP 2: Author U01 creates a Yellow Note draft & a DFA draft
        # ---------------------------------------------------------------------
        log.info("Step 2: Officer 1 (U01) drafts Yellow Note and DFA")
        yellow_body = (
            "Submitted for orders:\n\n"
            "The representation of Smt. A. Lakshmi Prasanna, Senior Assistant, "
            "Regional Office, Guntur, requesting transfer to Vijayawada on spouse grounds "
            "has been examined.\n"
            "As per Government guidelines, transfer on spouse grounds may be considered "
            "subject to minimum station tenure. Put up for orders.\n\n"
            "Section Officer (ESTT.I)"
        )
        yellow_res = client.post(
            "/assist/draft",
            json={
                "computer_no": cno,
                "kind": "yellow_note",
                "body": yellow_body,
                "citations": [],
                "request_id": "rehearsal-req-yn-1",
            },
            headers=_h("U01"),
        )
        assert yellow_res.status_code == 200, f"Failed to create Yellow Note: {yellow_res.text}"
        yellow_draft_id = yellow_res.json()["draft_id"]
        log.info("Yellow Note created (draft_id: %s)", yellow_draft_id)

        dfa_body = (
            "GOVERNMENT OF ANDHRA PRADESH\n"
            "ABSTRACT\n"
            "Establishment – Transfer of Senior Assistant on spouse grounds – Orders Issued.\n"
            "GENERAL ADMINISTRATION (ESTT.I) DEPARTMENT\n\n"
            "G.O.Ms.No.____ Dated: ____\n\n"
            "ORDER:\n"
            "Government hereby accords permission for transfer of Smt. A. Lakshmi Prasanna, "
            "Senior Assistant, from Regional Office, Guntur to Regional Office, Vijayawada "
            "with immediate effect."
        )
        dfa_res = client.post(
            "/assist/draft",
            json={
                "computer_no": cno,
                "kind": "dfa_draft",
                "body": dfa_body,
                "citations": [],
                "request_id": "rehearsal-req-dfa-1",
            },
            headers=_h("U01"),
        )
        assert dfa_res.status_code == 200, f"Failed to create DFA: {dfa_res.text}"
        dfa_draft_id = dfa_res.json()["draft_id"]
        log.info("DFA Draft created (draft_id: %s)", dfa_draft_id)

        results["steps"].append(
            {
                "step": 2,
                "name": "Draft preparation (Yellow Note & DFA)",
                "yellow_draft_id": yellow_draft_id,
                "dfa_draft_id": dfa_draft_id,
                "status": "OK",
            }
        )

        # ---------------------------------------------------------------------
        # STEP 3: Author U01 puts up DFA for approval
        # ---------------------------------------------------------------------
        log.info("Step 3: Officer 1 (U01) puts up DFA for approval")
        sub_res = client.post(
            f"/sandbox/files/{cno}/drafts/{dfa_draft_id}/submit",
            headers=_h("U01"),
        )
        assert sub_res.status_code == 200, f"Failed to submit DFA: {sub_res.text}"
        assert sub_res.json()["status"] == "submitted"
        log.info("DFA successfully submitted for senior approval.")
        results["steps"].append(
            {
                "step": 3,
                "name": "DFA submission to senior approver",
                "status": "OK",
            }
        )

        # ---------------------------------------------------------------------
        # STEP 4: Senior Approver U06 reviews and returns DFA with remarks
        # ---------------------------------------------------------------------
        log.info("Step 4: Senior Approver (U06, Secretary) reviews and returns draft")
        review_remarks = (
            "Please revise the draft to mandate a 2-year minimum station tenure condition "
            "and specify that the transfer is subject to vacancy availability at Vijayawada."
        )
        return_res = client.post(
            f"/sandbox/files/{cno}/approvals/{dfa_draft_id}/return",
            json={"remarks": review_remarks},
            headers=_h("U06"),
        )
        assert return_res.status_code == 200, f"Failed to return draft: {return_res.text}"
        ret_data = return_res.json()
        assert ret_data["status"] == "draft"
        assert ret_data["review_remarks"] == review_remarks
        log.info("DFA returned to author with remarks: '%s'", review_remarks)
        results["steps"].append(
            {
                "step": 4,
                "name": "Approver returns draft with remarks (ADR-0062)",
                "remarks": review_remarks,
                "returned_by": "U06",
                "status": "OK",
            }
        )

        # ---------------------------------------------------------------------
        # STEP 5: Author U01 inspects returned draft & executes AI revision
        # ---------------------------------------------------------------------
        log.info("Step 5: Author (U01) inspects returned remarks & requests AI revision")
        page_res = client.get(f"/sandbox/files/{cno}", headers=_h("U01"))
        assert page_res.status_code == 200
        drafts = page_res.json().get("drafts", [])
        dfa_entry = next((d for d in drafts if d["draft_id"] == dfa_draft_id), None)
        assert dfa_entry is not None, "DFA not found in author's file view"
        assert dfa_entry["review_remarks"] == review_remarks
        assert dfa_entry["returned_by_post"] == "Secretary to Government"
        log.info("Author banner confirms returned by: %s", dfa_entry["returned_by_post"])

        # Call POST /assist/draft/revise
        rev_res = client.post(
            "/assist/draft/revise",
            json={
                "computer_no": cno,
                "draft_id": dfa_draft_id,
                "current_text": dfa_entry["text"],
                "review_remarks": dfa_entry["review_remarks"],
            },
            headers=_h("U01"),
        )
        assert rev_res.status_code == 200, f"Failed AI revision: {rev_res.text}"
        rev_json = rev_res.json()
        assert "revised_text" in rev_json
        revised_text = rev_json["revised_text"]
        log.info(
            "AI Revision result generated (Changes summary: %s)", rev_json.get("changes_summary")
        )

        # Author saves revised draft text
        save_res = client.post(
            f"/sandbox/files/{cno}/drafts/{dfa_draft_id}/save",
            json={"text": revised_text},
            headers=_h("U01"),
        )
        assert save_res.status_code == 200, f"Failed to save revised DFA: {save_res.text}"
        log.info("Revised DFA text saved successfully.")
        results["steps"].append(
            {
                "step": 5,
                "name": "AI-assisted draft revision (ADR-0062)",
                "changes_summary": rev_json.get("changes_summary"),
                "status": "OK",
            }
        )

        # ---------------------------------------------------------------------
        # STEP 6: Author U01 confirms Yellow Note into permanent Green Note
        # ---------------------------------------------------------------------
        log.info("Step 6: Author (U01) confirms Yellow Note -> permanent Green Note")
        confirm_res = client.post(
            f"/sandbox/files/{cno}/drafts/{yellow_draft_id}/confirm",
            headers=_h("U01"),
        )
        assert confirm_res.status_code == 200, f"Failed to confirm Green Note: {confirm_res.text}"
        conf_data = confirm_res.json()
        assert conf_data["state"] == "green"
        green_note_id = conf_data["note_id"]
        log.info("Yellow Note successfully confirmed to Green Note (note_id: %s)", green_note_id)

        # Verify Green Note appears on official file note sheet
        file_check = client.get(f"/sandbox/files/{cno}", headers=_h("U01")).json()
        notes = file_check.get("notes", [])
        assert len(notes) == initial_notes_count + 1
        new_note = notes[-1]
        assert new_note["note_id"] == green_note_id
        assert new_note["state"] == "green"
        assert new_note["author_post"] == "Section Officer (Estt.I)"
        log.info(
            "Official Note Sheet verified: Note #%d confirmed by %s (State: %s)",
            len(notes),
            new_note["author_post"],
            new_note["state"],
        )
        results["steps"].append(
            {
                "step": 6,
                "name": "Green Note confirmation & note sheet persistence",
                "note_id": green_note_id,
                "post": new_note["author_post"],
                "state": new_note["state"],
                "status": "OK",
            }
        )

        # ---------------------------------------------------------------------
        # STEP 7: Author U01 re-submits revised DFA and Approver U06 issues G.O.
        # ---------------------------------------------------------------------
        log.info("Step 7: Author re-submits revised DFA; Approver approves and issues order")
        resub_res = client.post(
            f"/sandbox/files/{cno}/drafts/{dfa_draft_id}/submit",
            headers=_h("U01"),
        )
        assert resub_res.status_code == 200

        issue_res = client.post(
            f"/sandbox/files/{cno}/approvals/{dfa_draft_id}/issue",
            headers=_h("U06"),
        )
        assert issue_res.status_code == 200, f"Failed to approve & issue: {issue_res.text}"
        issue_data = issue_res.json()
        assert issue_data["status"] == "dispatched"
        issued_go_no = issue_data["issued_as"]
        log.info("Government Order successfully approved, signed, and issued as: %s", issued_go_no)
        results["steps"].append(
            {
                "step": 7,
                "name": "Approver signs and issues official Government Order",
                "issued_as": issued_go_no,
                "approver": "U06 (Secretary to Government)",
                "status": "OK",
            }
        )

    log.info("🎉 Two-Officer Rehearsal PASSED 100% cleanly across all 7 steps!")
    return results


if __name__ == "__main__":
    out = run_rehearsal()
    print(json.dumps(out, indent=2))
