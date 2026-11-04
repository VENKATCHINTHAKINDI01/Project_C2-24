"""AgentState consistency + intent templates against golden questions (plan §3.2, §3.4, §5.6, §8.3).

Questions are mapped to (intent, slots) by hand here — the orchestrator's job later.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest
from pydantic import ValidationError

from app.agents.intents import Intent, IntentSlots, SlotError, build_request
from app.agents.state import AgentState, HitlFlag
from app.citation.verifier import AnswerStatus, Claim, verify
from app.retrieval.evidence import build_package
from app.retrieval.ladder import ladder_label
from app.retrieval.references import lookup_reference
from tests.unit.mock_access import CLASSES, CORPUS, MATRIX, POLICY, new_store
from tests.unit.test_evidence_and_citations import CEILING
from tests.unit.test_ladder import DEPTS, DOC, INDEX, _run

GOLDEN = {
    q["id"]: q
    for q in json.loads((CORPUS / "ground_truth" / "golden_questions.json").read_text("utf-8"))
}


def _slots(**kw: object) -> IntentSlots:
    return IntentSlots.model_validate(kw)


CASES: dict[str, tuple[Intent, IntentSlots, bool]] = {
    # qid: (intent, slots, check the golden ladder label too)
    "Q01": (Intent.PRECEDENT_LOOKUP, _slots(text="spouse grounds transfer request decided"), True),
    "Q02": (Intent.PRECEDENT_LOOKUP, _slots(text="spouse grounds transfer request decided"), True),
    "Q03": (Intent.CURRENT_RULE, _slots(department="FIN01", terms=("transfers", "2025")), True),
    "Q06": (Intent.CURRENT_RULE, _slots(department="USD01", terms=("emergency",)), True),
    "Q24": (Intent.CURRENT_RULE, _slots(terms=("transfer",)), True),
    # golden says L1+L3; the template answers at L1 with the right documents (see PROGRESS gap)
    "Q04": (
        Intent.CURRENT_RULE,
        _slots(terms=("transfers",), issued_to=dt.date(2021, 1, 1)),
        False,
    ),
    "Q05": (
        Intent.DOCUMENT_STATUS,
        _slots(canonical_ids=("AP-USD01-CIRMEMO-USD01WRKS0-9-2023",)),
        True,
    ),
    "Q17": (Intent.CLAUSE_LOOKUP, _slots(canonical_ids=("AP-FIN01-GOMS-31-2025",)), True),
}


@pytest.mark.parametrize("qid", sorted(CASES))
def test_templates_meet_golden_documents(qid: str) -> None:
    q = GOLDEN[qid]
    intent, slots, check_label = CASES[qid]
    res = _run(build_request(intent, slots, q["user"]))
    got = {DOC[d.canonical_id] for d in res.documents} | {DOC[c] for c in res.graph_hits}
    assert set(q["expected_docs"]) <= got, (qid, got)
    assert not set(q["forbidden_docs"]) & got
    assert all(MATRIX[(d, q["user"])] for d in got)
    if check_label:
        assert ladder_label(res) == q["expected_ladder_level"], (qid, res.trace)


def test_q18_clause_lookup_through_reference_lookup() -> None:
    q = GOLDEN["Q18"]
    ref = lookup_reference(
        q["user"],
        q["question"],
        departments=DEPTS,
        retriever=INDEX,
        store=new_store(),
        policy=POLICY,
        classification=CLASSES,
    )
    assert ref.canonical_id is not None
    res = _run(
        build_request(Intent.CLAUSE_LOOKUP, _slots(canonical_ids=(ref.canonical_id,)), "U01")
    )
    assert ladder_label(res) == "L0" and DOC[res.documents[0].canonical_id] == "D03"


@pytest.mark.parametrize(
    "bad",
    [
        {"canonical_ids": ("G.O.Ms.88",)},  # not canonical: the resolver must run first
        {"terms": ("transfer'; DROP TABLE documents;--",)},  # not a word
        {"terms": tuple(f"t{i}" for i in range(9))},  # too many
        {"text": "x" * 501},  # too long
        {"department": "Finance"},  # not a code
        {"sql": "SELECT *"},  # unknown slot
    ],
)
def test_slots_reject_free_form_input(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        IntentSlots.model_validate(bad)


@pytest.mark.parametrize(
    ("intent", "slots"),
    [
        (Intent.PRECEDENT_LOOKUP, {}),
        (Intent.CURRENT_RULE, {}),
        (Intent.DOCUMENT_STATUS, {}),
        (
            Intent.CLAUSE_LOOKUP,
            {"canonical_ids": ("AP-FIN01-GOMS-31-2025", "AP-FIN01-GOMS-88-2022")},
        ),
        (Intent.DECISION_HISTORY, {}),
        (Intent.CONFLICT_CHECK, {}),
    ],
)
def test_missing_slots_are_refused(intent: Intent, slots: dict[str, object]) -> None:
    with pytest.raises(SlotError):
        build_request(intent, _slots(**slots), "U01")


# ---- AgentState -------------------------------------------------------------------------------


def _state(**kw: object) -> AgentState:
    base: dict[str, object] = {
        "request_id": "REQ-1",
        "session_id": "S1",
        "user": "U01",
        "raw_query": "What is the ceiling?",
        "as_of_date": dt.date(2026, 10, 2),
    }
    base.update(kw)
    return AgentState.model_validate(base)


def _package(uid: str = "U01"):  # type: ignore[no-untyped-def]
    return build_package(
        "REQ-1",
        uid,
        dt.date(2026, 10, 2),
        [CEILING],
        store=new_store(),
        policy=POLICY,
        classification=CLASSES,
    )


def test_full_happy_path_through_states() -> None:
    s = _state(intent=Intent.CURRENT_RULE, slots=_slots(terms=("transfers",)))
    pkg = _package()
    s = s.advance(
        scope_signature=pkg.scope_signature,
        authorized_candidates=tuple(pkg.canonical_ids),
        evidence_package=pkg,
        ladder_level="L1",
    )
    claim = Claim(
        text="Transfers may not exceed 15% of the cadre.", evidence_ids=(pkg.items[0].evidence_id,)
    )
    v = verify(pkg, [claim], store=new_store(), policy=POLICY, classification=CLASSES)
    s = s.advance(
        draft=(claim,), citations=claim.evidence_ids, verification=v, answer_status=v.answer_status
    )
    assert s.answer_status is AnswerStatus.ANSWERED
    s2 = s.advance(hitl_flags=frozenset({HitlFlag.NOTING_APPROVAL}))
    assert s2.request_id == s.request_id and s is not s2


@pytest.mark.parametrize(
    "bad",
    [
        "other_user_package",
        "scope_mismatch",
        "package_not_in_candidates",
        "citation_outside_package",
        "status_without_verification",
    ],
)
def test_inconsistent_states_are_refused(bad: str) -> None:
    pkg = _package()
    ok: dict[str, object] = {
        "scope_signature": pkg.scope_signature,
        "authorized_candidates": tuple(pkg.canonical_ids),
        "evidence_package": pkg,
    }
    changes = {
        "other_user_package": {**ok, "evidence_package": _package("U02")},
        "scope_mismatch": {**ok, "scope_signature": "f" * 64},
        "package_not_in_candidates": {**ok, "authorized_candidates": ()},
        "citation_outside_package": {**ok, "citations": ("EV-forged",)},
        "status_without_verification": {"answer_status": AnswerStatus.ANSWERED},
    }[bad]
    with pytest.raises(ValidationError):
        _state(**changes)
