"""Type C on synthetic set v2 (plan §6.2; ADR-0010 addendum): rules quoted from real public orders,
facts read from the efiles_v2 note layout. Mock status: every flag is an uncertain prompt."""

from __future__ import annotations

import datetime as dt

import pytest

from app.config import REPO_ROOT
from app.conflict.deterministic import ConflictType
from app.conflict.facts import extract_proposal_facts
from app.conflict.procedural import Action, AuthorityOutcome, check_authority, load_authority_rules
from app.identifiers.resolver import load_departments
from app.ingestion.metadata import extract_metadata

RULES = load_authority_rules(REPO_ROOT / "data" / "ontology" / "authority_rules_v2.yaml")
DEPTS = load_departments(REPO_ROOT / "data" / "ontology" / "departments.yaml")
GO = {
    "ESE01": "G.O.Ms.No.22, School Education (Services.II) Department, dated 20.05.2025",
    "FIN01": "G.O.Ms.No.51, Finance (Budget.I) Department, dated 01.04.2016",
    "FIN01-HR": "G.O.Ms.No.110, Finance (HR.I) Department, dated 17.06.2016",
    "GAD01": "G.O.Ms.No.74, General Administration (Cabinet) Department, dated 14.06.2017",
}


def _note(file_no: str, subject: str, proposal: str, date: str) -> str:
    dept = file_no.split("-")[0]
    return (
        f"File No.{file_no}\nNote # 1\nSub: {subject} – Reg.\nRef:\n1. {GO[dept]}.\n* * *\n"
        f"1) It is submitted that a reference has been received (PUC, p.1).\n"
        f"2) The orders on the subject are in {GO[dept]} (copy placed in References).\n"
        f"3) It is proposed that {proposal}.\n4) Approval Requested\n"
        f"   a) Approval for the proposal at the paras above.\n5) Submitted for orders.\n\n"
        f"{date} 10:49 AM\nL. BHARGAVI\nASSISTANT SECTION OFFICER\n"
    )


def _check(file_no: str, subject: str, proposal: str, date: str):  # type: ignore[no-untyped-def]
    text = _note(file_no, subject, proposal, date)
    meta = extract_metadata(text, DEPTS)
    d, m, y = (int(x) for x in date.split("/"))
    meta = meta.model_copy(update={"issue_date": meta.issue_date or dt.date(y, m, d)})
    res = extract_proposal_facts(text, meta, RULES, "NOTE-1")
    assert res.facts is not None, res.missing
    return res.facts, check_authority(res.facts, RULES, {"AP-ESE01-GOMS-22-2025"})


CASES = [
    (
        "ESE01-SERV20TRF/69/2025-SER.II",
        "Issue of transfer orders to teachers after web counselling",
        "the District Educational Officer may issue the transfer orders on the basis of the "
        "counselling lists, without waiting for the Committee",
        "12/06/2025",
        "ESE-TEACHER-TRANSFER-2025",
    ),
    (
        "ESE01-SERV20TRF/71/2025-SER.II",
        "Transfer of a Headmaster Gr.II on request — orders by the Regional Joint Director",
        "the transfer orders already issued by the Regional Joint Director may be ratified",
        "20/06/2025",
        "ESE-TEACHER-TRANSFER-2025",
    ),
    (
        "FIN01-BUDG0BRO/77/2016-BUDGET.I",
        "Request for re-appropriation of funds in the first quarter",
        "re-appropriation of funds may be sanctioned as requested",
        "16/05/2016",
        "FIN-NO-ADDITIONAL-FUNDS-H1-2016",
    ),
    (
        "FIN01-HRPLG0REC/88/2016-HR.I",
        "Direct recruitment — notification issued by a department on its own",
        "the recruitment notification already issued by the Head of the Department may be ratified",
        "21/11/2016",
        "FIN-DIRECT-RECRUITMENT-AGENCIES-2016",
    ),
    (
        "GAD01-SERA0SER/152/2018-SER.A",
        "Postings of Special Grade Deputy Collectors — proposal from a district",
        "the proposal may be returned to the Revenue Department, being the department concerned "
        "with postings of Special Grade Deputy Collectors",
        "12/02/2018",
        "GAD-DEPUTY-COLLECTORS-2017",
    ),
    (
        "GAD01-CABN0BR/150/2018-CABINET.II",
        "A.P. State Housing Board — reference from the Housing Department",
        "the Housing Department may be treated as the administrative department for the A.P. "
        "State Housing Board",
        "08/01/2018",
        "GAD-BR-HOUSING-BODIES-2017",
    ),
    (
        "GAD01-CABN0BR/146/2017-CABINET.II",
        "Corporate bodies for tourism and culture — allocation query",
        "the heritage corporation may be placed under the Municipal Administration & Urban "
        "Development Department",
        "28/03/2017",
        "GAD-BR-TOURISM-CULTURE-HERITAGE-2017",
    ),
]


@pytest.mark.parametrize(("file_no", "subject", "proposal", "date", "rule"), CASES)
def test_a_proposal_against_the_quoted_rule_is_an_uncertain_type_c(
    file_no: str, subject: str, proposal: str, date: str, rule: str
) -> None:
    _, res = _check(file_no, subject, proposal, date)
    assert res.outcome is AuthorityOutcome.CONFLICT
    assert [(f.type, f.cited, f.certain) for f in res.flags] == [(ConflictType.C, rule, False)]


def test_only_a_visible_source_is_quoted() -> None:
    _, res = _check(*CASES[0][:4])
    assert "AP-ESE01-GOMS-22-2025#para-5" in res.flags[0].explanation
    _, hidden = _check(*CASES[2][:4])  # G.O.51/2016 is not in the visible set
    assert (
        hidden.flags[0].evidence_ids == () and "no request for" not in hidden.flags[0].explanation
    )


@pytest.mark.parametrize(
    ("file_no", "subject", "proposal", "date"),
    [
        # the committee route is followed
        (
            "ESE01-SERV20TRF/90/2025-SER.II",
            "Transfer of teachers after web counselling",
            "the lists may be placed before the Committee for approval",
            "12/06/2025",
        ),
        # before the rules were issued
        (
            "ESE01-SERV20TRF/91/2025-SER.II",
            "Transfer of a teacher",
            "the District Educational Officer may issue the transfer orders",
            "02/05/2025",
        ),
        # third quarter: outside the barred period
        (
            "FIN01-BUDG0BRO/92/2016-BUDGET.I",
            "Request for re-appropriation of funds",
            "re-appropriation of funds may be sanctioned as requested",
            "14/11/2016",
        ),
        # inside the period, but the note proposes to refuse
        (
            "FIN01-BUDG0BRO/93/2016-BUDGET.I",
            "Request for additional funds",
            "the request may not be entertained in the first two quarters",
            "16/05/2016",
        ),
        # the subject goes to the department the rules name
        (
            "GAD01-SERA0SER/94/2018-SER.A",
            "Transfers of Deputy Collectors",
            "the orders may be issued by the General Administration Department",
            "12/02/2018",
        ),
        # two bodies named: the reader does not pick one
        (
            "GAD01-CABN0BR/95/2018-CABINET.II",
            "A.P. State Housing Board — administrative department",
            "the views of the Housing Department and the Planning Department may be obtained",
            "08/01/2018",
        ),
    ],
)
def test_no_flag_when_the_rule_is_kept_or_does_not_apply(
    file_no: str, subject: str, proposal: str, date: str
) -> None:
    _, res = _check(file_no, subject, proposal, date)
    assert res.flags == () and res.outcome is AuthorityOutcome.REVIEW_NEEDED  # never "clear"


def test_a_named_subject_gives_the_action_when_the_subject_has_no_action_word() -> None:
    facts, _ = _check(*CASES[5][:4])
    assert facts.action is Action.BUSINESS_ALLOCATION and facts.proposed_authority == "HOUSING"
