"""Touchpoint 14 — draft for approval, deterministic parts (plan §11.5)."""

from __future__ import annotations

import json
from functools import cache

import pytest
from evaluation.harness.stack import build_stack
from evaluation.harness.suites import Harness

from app.agents.dfa import (
    ORDER_PARAGRAPHS_PENDING,
    DfaPreview,
    abstract_from_subject,
    draft_for_approval,
)
from app.config import REPO_ROOT
from app.conflict.facts import extract_proposal_facts
from app.retrieval.ladder import LadderConfig

SLOTS = json.loads((REPO_ROOT / "evaluation" / "slots_v1.json").read_text("utf-8"))


@cache
def _harness() -> Harness:
    cfg = LadderConfig(l2_top_k=10, l2_min_score=1.0, l3_max_hops=2)
    return Harness(build_stack(cfg, transcribe=True), SLOTS)


def _preview(user: str, did: str = "D27") -> DfaPreview:
    h = _harness()
    cid = h.s.cid_of[did]
    text, meta = h._note(cid)  # noqa: SLF001 — evaluation helper
    facts = extract_proposal_facts(text, meta, h.rules, cid)
    return draft_for_approval(
        ctx=h._tool_ctx(user, "2026-10-02"),  # noqa: SLF001
        file_no="USD01-12/19/2026-ESTT.I",
        subject=meta.subject or "",
        draft_note=cid,
        meta=meta,
        action=facts.facts.action if facts.facts else None,
        flags=h.presend(did, user).flags,
    )


def _docs(pv: DfaPreview) -> set[str]:
    h = _harness()
    return {h.s.doc_of.get(i.canonical_id, i.canonical_id) for i in pv.read_list}


@pytest.mark.parametrize(
    ("subject", "want"),
    [
        (
            "Establishment – Transfer of X – Reg.",
            "Establishment – Transfer of X – Orders – Issued.",
        ),
        ("Works – Sanction - Reg", "Works – Sanction – Orders – Issued."),
        ("Works – Sanction", "Works – Sanction – Orders – Issued."),
    ],
)
def test_abstract_from_the_file_subject(subject: str, want: str) -> None:
    assert abstract_from_subject(subject) == want


def test_read_list_has_the_current_orders_and_not_the_superseded_or_unresolvable() -> None:
    pv = _preview("U02")
    docs = _docs(pv)
    assert {"D04", "D09", "D11"} <= docs
    assert not docs & {"D01", "D02", "D03"}  # superseded along the chain to 31/2025
    d04 = next(i for i in pv.read_list if i.canonical_id == "AP-FIN01-GOMS-31-2025")
    assert d04.in_place_of == ("AP-FIN01-GOMS-88-2022",) and d04.cited_in_note is False
    assert [x.cited for x in pv.left_out] == ["AP-FIN01-GOMS-104-2026"]


def test_open_flags_travel_with_the_draft_and_paragraphs_are_not_invented() -> None:
    pv = _preview("U02")
    assert {f.type.value for f in pv.flags} == {"A", "C", "E", "F"}
    assert "Open points for the approving officer" in pv.body
    assert ORDER_PARAGRAPHS_PENDING in pv.body
    assert "not approved, signed or issued" in pv.body
    assert pv.citations == tuple(i.canonical_id for i in pv.read_list)


def test_current_is_not_claimed_without_coverage() -> None:
    pv = _preview("U02")
    assert not all(i.status_confirmed for i in pv.read_list)
    assert any("could not be confirmed" in c for c in pv.caveats)


def test_an_order_the_officer_cannot_see_is_never_listed() -> None:
    """The Works SO may not see the RESTRICTED Estt.I Standing Order (D11)."""
    pv = _preview("U03")
    assert "D11" not in _docs(pv)
    h = _harness()
    assert all(h.visible("U03", i.canonical_id) for i in pv.read_list)
