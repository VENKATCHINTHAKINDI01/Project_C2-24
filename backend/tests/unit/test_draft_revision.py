"""Tests for draft revision based on reviewer remarks (plan §11.5; ADR-0045, ADR-0060)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from app.agents.llm import LLMError
from app.connectors.eoffice import DraftKind, DraftRequest
from app.eoffice_mock.models import DraftStatus
from app.noting.draft_revision import suggest_revision
from tests.unit.test_sandbox_api import APP, _h


class _FakeLLM:
    def __init__(self, revised_text: str, summary: str, fail: bool = False) -> None:
        self.name = "fake-gemini"
        self.revised_text = revised_text
        self.summary = summary
        self.fail = fail
        self.calls = 0

    def generate_json(
        self, *, prompt_id: str, system: str, user: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        self.calls += 1
        assert prompt_id == "draft_revise.v1"
        assert 'untrusted="true"' in user
        if self.fail:
            raise LLMError("simulated LLM failure")
        return {"revised_text": self.revised_text, "changes_summary": self.summary}


def test_suggest_revision_pure_function() -> None:
    # 1. Empty remarks
    res = suggest_revision(current_text="Draft text", review_remarks="")
    assert res.reason == "no_remarks"
    assert res.revised_text == "Draft text"

    # 2. Empty text
    res = suggest_revision(current_text="", review_remarks="Change something")
    assert res.reason == "no_text"

    # 3. Engine off (llm=None)
    res = suggest_revision(
        current_text="Original text", review_remarks="Reduce sanction amount", llm=None
    )
    assert res.reason == "engine_off"
    assert "Original text" in res.revised_text
    assert "Reduce sanction amount" in res.changes_summary

    # 4. Successful LLM call
    fake = _FakeLLM(
        revised_text="Revised text with Rs 50 lakhs",
        summary="Reduced ceiling to Rs 50 lakhs as requested.",
    )
    res = suggest_revision(
        current_text="Original text with Rs 1 crore",
        review_remarks="Reduce ceiling to Rs 50 lakhs",
        subject="Sanction of grant",
        llm=fake,
    )
    assert fake.calls == 1
    assert res.revised_text == "Revised text with Rs 50 lakhs"
    assert res.changes_summary == "Reduced ceiling to Rs 50 lakhs as requested."
    assert res.reason is None

    # 5. Engine down
    fail_llm = _FakeLLM("", "", fail=True)
    res = suggest_revision(
        current_text="Original text",
        review_remarks="Some change",
        llm=fail_llm,
    )
    assert res.reason == "engine_down"
    assert res.revised_text == "Original text"


def test_adapter_return_draft_stores_remarks_and_submit_clears() -> None:
    with TestClient(APP):
        adapter = APP.state.adapter
        cno = "1771342"
        # Create a DFA draft through connector contract
        receipt = adapter.create_draft(
            DraftRequest(
                kind=DraftKind.DFA_DRAFT,
                computer_no=cno,
                requested_by="U01",
                officer_clicked=True,
                body="G.O.Ms.No.____ Dated: ____\nSanction is accorded for Rs. 1,00,00,000/-.",
                citations=(),
                request_id="req-adapter-1",
            )
        )
        draft_id = receipt.draft_id
        # Author U01 submits for approval
        submitted = adapter.submit_draft(cno, draft_id, "U01")
        assert submitted.status is DraftStatus.SUBMITTED

        # Approver U06 (Secretary) returns with remarks
        returned = adapter.return_draft(
            cno,
            draft_id,
            "U06",
            remarks="Please reduce the amount to Rs 50 lakhs per G.O.Ms. 88.",
        )
        assert returned.status is DraftStatus.DRAFT
        assert returned.review_remarks == "Please reduce the amount to Rs 50 lakhs per G.O.Ms. 88."
        assert returned.returned_by == "U06"
        assert returned.returned_at is not None

        # Author re-submits: remarks and returned metadata are cleared
        resubmitted = adapter.submit_draft(cno, draft_id, "U01")
        assert resubmitted.status is DraftStatus.SUBMITTED
        assert resubmitted.review_remarks is None
        assert resubmitted.returned_by is None
        assert resubmitted.returned_at is None


def test_api_return_and_revise_flow() -> None:
    with TestClient(APP) as client:
        cno = "1771342"
        # 1. Author U01 creates a DFA draft
        create_resp = client.post(
            "/assist/draft",
            json={
                "computer_no": cno,
                "kind": "dfa_draft",
                "body": (
                    "G.O.Ms.No.____ Dated: ____\n"
                    "Government hereby sanction Rs 1,00,00,000 for hospital building."
                ),
                "citations": [],
                "request_id": "req-1",
            },
            headers=_h("U01"),
        )
        assert create_resp.status_code == 200, create_resp.text
        draft_id = create_resp.json()["draft_id"]

        # 2. Author U01 puts up draft for approval
        sub_resp = client.post(
            f"/sandbox/files/{cno}/drafts/{draft_id}/submit",
            headers=_h("U01"),
        )
        assert sub_resp.status_code == 200, sub_resp.text

        # 3. Senior approver U06 returns draft with remarks
        ret_resp = client.post(
            f"/sandbox/files/{cno}/approvals/{draft_id}/return",
            json={"remarks": "Revise sanction to Rs 50,00,000 as per policy."},
            headers=_h("U06"),
        )
        assert ret_resp.status_code == 200, ret_resp.text
        assert ret_resp.json()["review_remarks"] == "Revise sanction to Rs 50,00,000 as per policy."

        # 4. Author U01 views file page: draft contains review_remarks and returned_by_post
        page_resp = client.get(f"/sandbox/files/{cno}", headers=_h("U01"))
        assert page_resp.status_code == 200
        drafts = page_resp.json()["drafts"]
        my_draft = next((d for d in drafts if d["draft_id"] == draft_id), None)
        assert my_draft is not None
        assert my_draft["review_remarks"] == "Revise sanction to Rs 50,00,000 as per policy."
        assert my_draft["returned_by_post"] is not None

        # 5. Author U01 calls /assist/draft/revise
        rev_resp = client.post(
            "/assist/draft/revise",
            json={
                "computer_no": cno,
                "draft_id": draft_id,
                "current_text": my_draft["text"],
                "review_remarks": my_draft["review_remarks"],
            },
            headers=_h("U01"),
        )
        assert rev_resp.status_code == 200, rev_resp.text
        body = rev_resp.json()
        assert "revised_text" in body
        assert "changes_summary" in body


# ---- ADR-0062 addendum (24 Nov 2026): evidence check, cost controls, access ----------------


def test_a_revision_that_invents_a_figure_or_reference_is_withheld() -> None:
    from app.noting.draft_revision import unsupported_tokens

    draft = "Government hereby sanction Rs 1,00,00,000 under G.O.Ms.No.31, dated 12-05-2025."
    remarks = "Reduce the sanction to Rs 50,00,000."
    ok = "Government hereby sanction Rs 50,00,000 under G.O.Ms.No.31, dated 12-05-2025."
    bad = "Government hereby sanction Rs 50,00,000 under G.O.Ms.No.44, dated 01-04-2026."
    assert unsupported_tokens(ok, draft, remarks) == []
    assert {"G.O.Ms.No.44", "01-04-2026"} <= set(unsupported_tokens(bad, draft, remarks))

    good = suggest_revision(current_text=draft, review_remarks=remarks, llm=_FakeLLM(ok, "cut"))
    assert good.reason is None and good.revised_text == ok
    held = suggest_revision(current_text=draft, review_remarks=remarks, llm=_FakeLLM(bad, "x"))
    assert held.reason == "unsupported" and held.revised_text == draft  # officer keeps theirs
    assert "G.O.Ms.No.44" in held.unsupported and "withheld" in held.changes_summary


def test_revise_counts_against_the_daily_limit_and_is_logged() -> None:
    import datetime as dt

    from app.config import get_settings
    from app.main import create_app

    app = create_app(
        get_settings().model_copy(update={"sandbox": True, "draft_wording_per_day": 1})
    )
    body = {
        "computer_no": "1771342",
        "current_text": "Government hereby sanction Rs 1,00,00,000.",
        "review_remarks": "Reduce to Rs 50,00,000.",
    }
    with TestClient(app) as c:
        app.state.assist_runtime().llm = _FakeLLM("Government hereby sanction Rs 50,00,000.", "cut")
        try:
            first = c.post("/assist/draft/revise", json=body, headers=_h("U01")).json()
            second = c.post("/assist/draft/revise", json=body, headers=_h("U01")).json()
        finally:
            app.state.assist_runtime().llm = None
        log = app.state.model_usage.entries(dt.datetime(2000, 1, 1, tzinfo=dt.UTC))
    assert first["reason"] is None and first["usage"] == {"used": 1, "limit": 1}
    assert second["reason"] == "daily_limit" and second["engine"] is None
    assert [(e.action, e.outcome) for e in log if e.user_id == "U01"] == [
        ("draft.revise", "ok"),
        ("draft.revise", "daily_limit"),
    ]


def test_revise_and_return_stay_within_access() -> None:
    """An officer who cannot open the file gets the same 404 as for a file that does not
    exist; only the officer the draft is waiting on can return it."""
    body = {"computer_no": "1771342", "current_text": "x", "review_remarks": "y"}
    with TestClient(APP) as c:
        outsider = next(
            u for u in ("U02", "U03", "U04", "U05", "U07", "U08")
            if c.get("/sandbox/files/1771342", headers=_h(u)).status_code == 404
        )  # fmt: skip
        hidden = c.post("/assist/draft/revise", json=body, headers=_h(outsider))
        absent = c.post(
            "/assist/draft/revise", json={**body, "computer_no": "99999999"}, headers=_h(outsider)
        )
        assert hidden.status_code == absent.status_code == 404
        assert hidden.json()["detail"] == absent.json()["detail"]
        d = c.post(
            "/assist/draft",
            json={"computer_no": "1771342", "kind": "dfa_draft",
                  "body": "G.O.Ms.No.____ Dated: ____\nGovernment hereby order.",
                  "citations": [], "request_id": "r-acc"},
            headers=_h("U01"),
        ).json()["draft_id"]  # fmt: skip
        c.post(f"/sandbox/files/1771342/drafts/{d}/submit", headers=_h("U01"))
        not_approver = c.post(
            f"/sandbox/files/1771342/approvals/{d}/return",
            json={"remarks": "no"},
            headers=_h("U01"),  # the author cannot return their own draft
        )
        assert not_approver.status_code == 404
