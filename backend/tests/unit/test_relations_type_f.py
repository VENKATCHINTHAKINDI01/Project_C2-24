"""How an order changes earlier orders, read from its text (plan §5.7; ADR-0052).

Each case is a short SYNTHETIC text in the shape of a real AP order that the type F evaluation
missed (efiles_v2, 18 Nov 2026): amended orders the extractor did not link, so the pre-send check
could not say "the note relies on an order amended before it was written"."""

from __future__ import annotations

import pytest

from app.config import REPO_ROOT
from app.identifiers.resolver import load_departments
from app.ingestion.metadata import RelKind, extract_metadata

DEPTS = load_departments(REPO_ROOT / "data" / "ontology" / "departments.yaml")
HEAD = (
    "GOVERNMENT OF ANDHRA PRADESH\nABSTRACT\n{subj}\nFINANCE (HR.I) DEPARTMENT\n"
    "G.O.Ms.No.{no} Dated: {date}\n"
)


def rels(text: str) -> set[tuple[str, int]]:
    m = extract_metadata(text, DEPTS, source_department="FIN01")
    return {
        (r.kind.value, int(r.target.split("-")[3]))
        for r in m.relations
        if r.kind is not RelKind.REFERENCES and r.resolved
    }


def order(subj: str, no: int, date: str, read: str, body: str) -> str:
    return HEAD.format(subj=subj, no=no, date=date) + read + "\nORDER:\n" + body + "\n"


def test_partial_modification_of_an_order_read_above_amends_it() -> None:
    t = order(
        "Transfers - Extension of last date - Orders - Issued.", 123, "28-06-2016",
        "Read the following:-\n1. G.O.Ms.No.102, Finance (HR.I) Dept., dated: 10.06.2016.\n***",
        "In partial modification of the orders issued in reference first read above, the last "
        "date of transfers is extended up to 22.06.2016.",
    )  # fmt: skip
    assert rels(t) == {("AMENDS", 102)}


def test_one_unnumbered_read_entry_and_an_amendment_to_the_go_read_above() -> None:
    t = order(
        "Budget - Guidelines - Amendment - Issued.", 141, "25-10-2019",
        "Read the Following:\n\nG.O. Ms. No.101, Finance (Budget.I) Dept. dated 14.08.2019\n",
        "In continuation of the orders issued in the G.O. read above, Government hereby issue "
        "the following amendment to the G.O. read above.",
    )  # fmt: skip
    assert rels(t) == {("AMENDS", 101)}


def test_a_wrapped_date_is_not_a_read_list_item_and_g_o_does_not_end_a_sentence() -> None:
    t = order(
        "Allocation of posts - Procedural Guidelines - Amendment Orders - Issued.", 41,
        "01-04-2022",
        "Read the following:\n1. G.O.Ms.No.31, Finance (HR.I) Department, dated\n26.02.2022.\n"
        "2. G.O.Ms.No.45, Finance (HR.I) Department, dated 24.06.2019.\n***",
        "The following amendment is issued to para 7.1 of the G.O. 1st read above: For the words "
        "x read y.",
    )  # fmt: skip
    assert rels(t) == {("AMENDS", 31)}


def test_a_dearness_relief_rate_revised_changes_only_the_order_it_was_sanctioned_in() -> None:
    t = order(
        "PENSIONS - Dearness Relief - Revision of Dearness Relief - Orders - Issued.", 17,
        "03-02-2017",
        "Read thefollowing:-\n1. G.O.Ms.No.46, Finance(HR.V)Department, dated30.04.2015.\n"
        "2. G.O.Ms.No.173, Finance(HR.V)Department, dated30.08.2016\n***",
        "Government hereby order the revision of rates of Dearness Reliefto pensioners sanctioned "
        "in the G.O. 2ndread above, raising it by 3.144% from 15.196% of the basic pension to "
        "18.340% of the basic pension in respect of those whose pension was consolidated in the "
        "light of orders issued in the G.O. 1stread above. 2. Government also hereby order the "
        "revision of rates of Dearness Relief from 88.168% to 93.304% to the Pensioners not "
        "consolidated in terms of the orders issued in the reference 1st read above.",
    )  # fmt: skip
    assert rels(t) == {("AMENDS", 173)}


def test_amendment_to_rules_issued_in_one_order_read_with_others_changes_all_of_them() -> None:
    t = order(
        "Transfer Rules - Amendment - Orders - Issued.", 50, "20-07-2017",
        "Read the following:-\n1. G.O.Ms.No.32, Finance (HR.I) Dept., dt.04.06.2017.\n"
        "2. G.O.Ms.No.38, Finance (HR.I) Dept., dt.21.06.2017.\n"
        "3. G.O.Ms.No.43, Finance (HR.I) Dept., dt.30.06.2017.\n* * *",
        "Government hereby makes the following amendment to the Transfer Rules issued in "
        "G.O.Ms.No.32, Finance (HR.I) Department, dated 04.06.2017 read with G.O.Ms.No.38, Finance "
        "(HR.I) Department, dated 21.06.2017 and G.O.Ms.No.43, Finance (HR.I) Department, dated "
        "30.06.2017. AMENDMENT For Rule 12(a), the following shall be substituted.",
    )  # fmt: skip
    assert rels(t) == {("AMENDS", 32), ("AMENDS", 38), ("AMENDS", 43)}


def test_as_amended_in_is_history_not_a_second_order_changed() -> None:
    t = order(
        "Rules - Amendment - Notification - Orders - Issued.", 130, "09-09-2011",
        "Read the following:-\n1. G.O.Ms.No.20, Finance (HR.I) Dept., dt.03.03.2011.\n"
        "2. G.O.Ms.No.25, Finance (HR.I) Dept., dt.04.04.2011.\n***",
        "Government hereby make the following amendments to the Rules issued in G.O.Ms.No.20, "
        "Finance (HR.I) Department, dated 03.03.2011, as amended in G.O.Ms.No.25, Finance (HR.I) "
        "Department, dated 04.04.2011. AMENDMENTS In rule 4, for x read y.",
    )  # fmt: skip
    assert rels(t) == {("AMENDS", 20)}


@pytest.mark.parametrize("verb", ["withdraw", "cancel", "rescind"])
def test_orders_withdrawn_are_repealed(verb: str) -> None:
    t = order(
        "Guidelines - Withdrawal of the GOs - Orders - Issued.", 39, "29-04-2023",
        "Read the following:\n1. G.O.Ms.No.187, Finance (HR.I) Department, dated. 10.12.2022.\n"
        "2. G.O.Ms.No.190, Finance (HR.I) Department, dated. 21.12.2022.\n"
        "3. From the Commissioner, e-file Computer No.1749182.\n*****",
        "In the G.O. 1st read above, Guidelines were issued and in the G.O.Ms.No.190, certain "
        "amendments were issued. 2. The Government, after careful examination of the matter, "
        f"hereby {verb} the above G.O.Ms.No.187, Finance (HR.I) Dept., dated: 10.12.2022 read with "
        "amendment G.O.Ms.No.190, Finance (HR.I) Department, dated 21.12.2022. 3. Orders follow.",
    )  # fmt: skip
    assert rels(t) == {("REPEALS", 187), ("REPEALS", 190)}


def test_a_letter_in_the_read_list_is_never_the_order_amended() -> None:
    t = order(
        "Selection Rules - Amendment - Orders - Issued.", 70, "05-11-2018",
        "Read the following:\n1. G. O. Ms. No. 67, Finance (HR.I) Department, dt:26.10.2018.\n"
        "2. From the Commissioner, Lr.Rc.No ESE02-20021/6/2018-RECTMT, Dt: 27.10.2018.\n*****",
        "In the Government Order 1 st read above, the Rules were issued. 2. In the circumstances "
        "stated by the Commissioner in the letter 2 nd read above, Government hereby issue the "
        "following amendments to the aforesaid Rules issued in G. O. Ms. No. 67, Finance (HR.I) "
        "Department, dt: 26.10.2018. AMENDMENTS 1. Para 4 shall be substituted.",
    )  # fmt: skip
    assert rels(t) == {("AMENDS", 67)}
