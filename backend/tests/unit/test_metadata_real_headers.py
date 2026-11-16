"""Own-reference reading for headers seen on real public orders and gazettes (corpus v2,
13 Nov 2026).
Snippets are short header lines in the printed form, not document bodies."""

from __future__ import annotations

import datetime as dt

import pytest

from app.config import REPO_ROOT
from app.identifiers.resolver import load_departments
from app.ingestion.metadata import (
    DocType,
    DocumentMetadata,
    extract_metadata,
    with_printed_masthead,
)

DEPTS = load_departments(REPO_ROOT / "data" / "ontology" / "departments.yaml")


def _go(own_line: str, heading: str = "FINANCE (HR-I Plg. & Policy) DEPARTMENT") -> str:
    return (
        "GOVERNMENT OF ANDHRA PRADESH\nABSTRACT\n"
        "PUBLIC SERVICES – Recruitments – Orders – Issued.\n"
        f"{heading}\n{own_line}\nRead the following:\n1. GO Ms No 110 Finance Department, dated "
        "17.06.2016.\nORDER:\nGovernment hereby order as follows.\n"
    )


@pytest.mark.parametrize(
    ("own_line", "cid", "issued"),
    [
        ("G.O. Ms. No.:117 Dated: 23.06.2016", "AP-FIN01-GOMS-117-2016", dt.date(2016, 6, 23)),
        ("G.O. MS. No.: 101 Dated: 14.08.2019", "AP-FIN01-GOMS-101-2019", dt.date(2019, 8, 14)),
        ("G.O.M s.No.141 Dated:16.08.2017.", "AP-FIN01-GOMS-141-2017", dt.date(2017, 8, 16)),
        ("G.O. Ms. No.150  Date: 08.08.2016", "AP-FIN01-GOMS-150-2016", dt.date(2016, 8, 8)),
        ("G.O.Ms.No.51 Dated: 01 April 2016", "AP-FIN01-GOMS-51-2016", dt.date(2016, 4, 1)),
        ("G.O.Ms.No. 63 Dated: 18th April 2016", "AP-FIN01-GOMS-63-2016", dt.date(2016, 4, 18)),
        ("G.O.Ms.No.61 Dated:-14.09.2021", "AP-FIN01-GOMS-61-2021", dt.date(2021, 9, 14)),
        ("G.O.Ms.No:38 Dated:22.04.2023", "AP-FIN01-GOMS-38-2023", dt.date(2023, 4, 22)),
    ],
)
def test_real_own_line_forms_resolve(own_line: str, cid: str, issued: dt.date) -> None:
    md = extract_metadata(_go(own_line), DEPTS)
    assert md.canonical_id == cid and md.issue_date == issued
    assert md.doc_type is DocType.GOVERNMENT_ORDER and not md.review_reasons


def test_heading_with_lower_case_section_names_the_department() -> None:
    md = extract_metadata(
        _go("G.O.Ms.No.28 Dated: 01-03-2018.", "FINANCE (HR-5-Pension, GPF) DEPARTMENT"), DEPTS
    )
    assert md.canonical_id == "AP-FIN01-GOMS-28-2018" and md.department == "FIN01"


def test_the_loose_form_needs_the_date_right_after_the_number() -> None:
    """A cited order with its department between number and date is not read as the own line."""
    md = extract_metadata(
        _go("G.O. Ms. No.:46, Finance (HRM.V) Department, Dated: 30.04.2015"), DEPTS
    )
    assert md.canonical_id != "AP-FIN01-GOMS-46-2015"


MAST = "Registered No. HSE-49/2016\nTHE ANDHRA PRADESH GAZETTE\nPUBLISHED BY AUTHORITY\n"


@pytest.mark.parametrize(
    ("head", "cid", "issued"),
    [
        (
            "PARTI EXTRAORDINARY\nNo.654 AMARAVATI, MONDAY, OCTOBER 5, 2020 G.340\n",
            "AP-GAZ-GAZETTE-EI-340-2020",
            dt.date(2020, 10, 5),
        ),
        (
            "W.No.18 AMARAVATI, TUESDAY, MAY 7, 2019 G.48\nPART I - NOTIFICATIONS BY GOVERNMENT\n",
            "AP-GAZ-GAZETTE-WI-48-2019",
            dt.date(2019, 5, 7),
        ),
        (
            "W.No.3 AMARAVATI, THURSDAY, JANUARY 27, 2022 G.648\nRULES SUPPLEMENT TO PART I\n",
            "AP-GAZ-GAZETTE-WRSI-648-2022",
            dt.date(2022, 1, 27),
        ),
    ],
)
def test_gazette_masthead_gives_the_gazette_id(head: str, cid: str, issued: dt.date) -> None:
    body = "NOTIFICATIONS BY GOVERNMENT\nAMENDMENT TO THE ANDHRA PRADESH SELECTION RULES, 2019.\n"
    md = extract_metadata(MAST + head + body + "G.O.Ms.No.07 Dated: 24.01.2022\n", DEPTS)
    assert (md.canonical_id, md.issue_date, md.department) == (cid, issued, "GAZ")
    assert md.doc_type is DocType.GAZETTE and md.instrument == "RULES"


def test_gazette_without_a_readable_part_is_not_given_an_id() -> None:
    """No part line ("PART I ...") on page 1 → never guessed; the document goes to review."""
    text = MAST + "No.32 AMARAVATI, FRIDAY, JANUARY 5, 2024 G.3644\nNOTIFICATIONS BY GOVERNMENT\n"
    md = extract_metadata(text + "Circular memo text without an own G.O. line.\n", DEPTS)
    assert md.canonical_id is None and md.review_reasons


def test_gazette_that_is_not_rules_has_no_rules_level() -> None:
    text = (
        MAST
        + "PART I EXTRAORDINARY\n"
        + "No.9 AMARAVATI, MONDAY, MARCH 4, 2024 G.137\nCommencement notice.\n"
    )
    md = extract_metadata(text, DEPTS)
    assert md.canonical_id == "AP-GAZ-GAZETTE-EI-137-2024" and md.instrument is None


def _order(abstract: str, reads: str, operative: str) -> str:
    return (
        f"GOVERNMENT OF ANDHRA PRADESH\nABSTRACT\n{abstract}\n"
        "GENERAL ADMINISTRATION (SERVICES.A) DEPARTMENT\nG.O.Ms.No.175 Dated:27.11.2017.\n"
        f"Read the following:-\n{reads}\n****\nORDER:\n{operative}\n"
        "(BY ORDER AND IN THE NAME OF THE GOVERNOR OF ANDHRA PRADESH)\n"
    )


def _rel(md: DocumentMetadata) -> set[tuple[str, str, bool]]:
    return {
        (r.kind.value, r.target, r.explicit) for r in md.relations if r.kind.value != "REFERENCES"
    }


def test_supersession_naming_the_earlier_order_by_number() -> None:
    text = _order(
        "Public Services – Prescription of minimum service – Orders – Issued.",
        "1. G.O.Ms.No.627 G.A.(Ser.A) Department, Dated:21.12.1983\n"
        "2. G.O.Ms.No.230, G.A.(Ser.A) Dept., Dt: 31.05.2014",
        "In exercise of the powers and in supersession of the ad-hoc rule issued in G.O.Ms.No.230 "
        "G.A.(Ser.A) Department, dated 31.05.2014, the Governor hereby makes the following rule.",
    )
    assert _rel(extract_metadata(text, DEPTS)) == {("SUPERSEDES", "AP-GAD01-GOMS-230-2014", True)}


def test_amendment_to_an_order_named_by_number_after_the_phrase() -> None:
    text = _order(
        "The A.P. Anti-Corruption Bureau Service Rules, 2019 – Amendment – Orders – Issued.",
        "1. G.O.Ms.No. 34, GA(SC.F) Department, dated: 15.04.2020.\n"
        "2. G.O.Ms.No.122, GA(SC.F) Department, dated:21.10.2021.",
        "The Governor of Andhra Pradesh hereby makes the following amendments to the Rules "
        "issued in G.O.Ms.No. 34, GA(SC.F) Department, dated 15.04.2020, "
        "as amended in G.O.Ms.No.122.",
    )
    assert _rel(extract_metadata(text, DEPTS)) == {("AMENDS", "AP-GAD01-GOMS-34-2020", True)}


def test_amendment_by_title_with_one_order_read_is_a_candidate_only() -> None:
    text = _order(
        "Guidelines for conducting AP-TET – Amendment – Orders – Issued.",
        "1. G. O. Ms. No. 25, General Administration (Ser.A) Department, dt: 04.05.2018.\n"
        "2. From the Commissioner, Lr. Rc. No. 01/TET/2018, dt: 18.05.2018.",
        "In the Government Order 1 st read above, guidelines were issued. Government hereby "
        "issue the following changes to the aforesaid guidelines.",
    )
    assert _rel(extract_metadata(text, DEPTS)) == {("AMENDS", "AP-GAD01-GOMS-25-2018", False)}


def test_ordinal_words_and_the_order_heading() -> None:
    text = _order(
        "Transfers – Guidelines – Orders – Issued.",
        "Ref: 1.G.O.Ms.No.54, G.A.(Ser.A) Department, dated 02.05.2018\n"
        "2.G.O.Ms.No.57, G.A.(Ser.A) Department, dated 08.05.2018",
        "In supersession of orders issued in the reference second read above, the Government "
        "hereby issue the following guidelines.",
    )
    assert _rel(extract_metadata(text, DEPTS)) == {("SUPERSEDES", "AP-GAD01-GOMS-57-2018", True)}


@pytest.mark.parametrize(
    ("abstract", "operative", "expected"),
    [
        (
            "PENSIONS – Dearness Relief with effect from 01.07.2016 – Orders – Issued.",
            "",
            dt.date(2016, 7, 1),
        ),
        (
            "Guidelines – Orders – Issued.",
            "These orders shall come into force with effect from 1st April, 2022.",
            dt.date(2022, 4, 1),
        ),
        (
            "Guidelines – Orders – Issued.",
            "with effect from 01.01.2015 for X and with effect from 01.07.2015 for Y.",
            None,
        ),
        (
            "Guidelines – Orders – Issued.",
            "These orders shall come into force with immediate effect.",
            None,
        ),
    ],
)
def test_stated_effective_date(abstract: str, operative: str, expected: dt.date | None) -> None:
    md = extract_metadata(
        _order(abstract, "1. G.O.Ms.No.627 G.A.(Ser.A) Department, Dated:21.12.1983", operative),
        DEPTS,
    )
    assert md.stated_effective_from == expected


def test_a_note_citing_a_gazette_resolves_to_its_masthead_id() -> None:
    """Gazette citations in notes (efiles_v2): edition and part give the ID; nothing guessed."""
    text = (
        "File No.FIN01-HRPEN0PEN/138/2024-HR.III\nNote # 1\n"
        "The relevant orders are in A.P. Gazette (Extraordinary / PART I) No.3880, dated\n"
        "19.02.2024 and A.P. Gazette (Weekly / Rules Supplement to Part I) No.648,"
        " dated 24.01.2022. See also A.P. Gazette No.12, dated 01.01.2020.\n"
    )
    meta = extract_metadata(text, DEPTS)
    ids = [r.canonical_id for r in meta.references if not r.raw.startswith("file:")]
    assert ids == ["AP-GAZ-GAZETTE-EI-3880-2024", "AP-GAZ-GAZETTE-WRSI-648-2022"]


def test_an_unnumbered_single_read_entry_is_read_and_amended_by_title() -> None:
    """G.O.Rt.No.2740/2019 GA (public): "Read:-" names one order without a number; the title says
    Amendment, so that order is the amended one (candidate, for review)."""
    text = (
        "GOVERNMENT OF ANDHRA PRADESH\nABSTRACT\n\n"
        "Group of Ministers constituted – Formation of Working Committee – Amendment - Orders – "
        "Issued.\n----------\nGENERAL ADMINISTRATION (CABINET.I) DEPARTMENT\n\n"
        "G.O.RT.No. 2740                                  Dated: 04-12-2019.\n"
        "                                                  Read:-\n\n"
        "G.O.Rt.No.2657, G.A (Cabinet.I) Department, Dated.26.11.2019.\n\n"
        "ORDER:\n\n The following amendment is issued to the para 3 of G.O. read above\n"
        "AMENDMENT\nFOR READ AS\n1. The above working committee shall submit a report by 31st "
        "March, 2020. 3. The above working committee shall submit a report by 30th June, 2020\n"
    )
    meta = extract_metadata(text, DEPTS)
    assert [r.canonical_id for r in meta.references] == ["AP-GAD01-GORT-2657-2019"]
    (rel,) = meta.relations
    assert (rel.kind.value, rel.target, rel.explicit) == (
        "AMENDS",
        "AP-GAD01-GORT-2657-2019",
        False,
    )


def test_a_read_heading_with_several_unnumbered_orders_is_not_guessed() -> None:
    text = (
        "GOVERNMENT OF ANDHRA PRADESH\nABSTRACT\nPensions – Orders – Issued.\n"
        "FINANCE (HR-III) DEPARTMENT\nG.O.MS.No. 7          Dated: 04-01-2024.\nRead:-\n"
        "G.O.Ms.No.3, Finance (HR-III) Department, Dated.02.01.2023.\n"
        "G.O.Ms.No.5, Finance (HR-III) Department, Dated.02.03.2023.\nORDER:\nText.\n"
    )
    assert extract_metadata(text, DEPTS).references == ()


# Page-1 text layers of two real gazettes whose Document AI text lost or scrambled the masthead.
_LAYER_3644 = (
    "PART I   EXTRAORDINARY\nRegistered No. HSE-49/2016\n"
    "No.32 AMARAVATI, FRIDAY, JANUARY 5, 2024 G.3644\nNOTIFICATIONS BY GOVERNMENT--x--\n"
)
_LAYER_1905 = (
    "RULES SUPPLEMENT TO PART I   EXTRAORDINARY\nRegistered No. HSE-49/2016\n"
    "No.1284 AMARAVATI, SATURDAY, NOVEMBER 18, 2023 G.1905\nNOTIFICATIONS BY GOVERNMENT--x--\n"
)
_OCR_3644 = (
    "Registered No. HSE-49/2016\nNo.32\nAMARAVATI, FRIDAY, JANUARY 5, 2024\nG.3644\n"
    "NOTIFICATIONS BY GOVERNMENT\n--x--\nGOVERNMENT OF ANDHRA PRADESH\n"
    "FINANCE(HR.III. PENSION,GPF)DEPARTMENT\nCircular.Memo.No. FIN01-HR0MISC/25/2023-HR-III/"
    "2036775, Dt:28/05/2023\nSub:- Pension Rules - qualifying service - Reg.\n"
)


@pytest.mark.parametrize(
    ("layer", "cid"),
    [(_LAYER_3644, "AP-GAZ-GAZETTE-EI-3644-2024"), (_LAYER_1905, "AP-GAZ-GAZETTE-ERSI-1905-2023")],
)
def test_the_printed_masthead_names_a_gazette_the_ocr_text_cannot(layer: str, cid: str) -> None:
    assert extract_metadata(_OCR_3644, DEPTS).canonical_id != "AP-GAZ-GAZETTE-EI-3644-2024"
    merged = with_printed_masthead(_OCR_3644, layer)
    assert merged is not None and extract_metadata(merged, DEPTS).canonical_id == cid


def test_no_masthead_in_the_layer_or_one_already_read_changes_nothing() -> None:
    assert with_printed_masthead(_OCR_3644, "some stray text layer") is None
    assert with_printed_masthead(_LAYER_3644 + _OCR_3644, _LAYER_1905) is None  # never overrides


def test_a_gazette_ranks_as_the_circular_memo_it_notifies() -> None:
    merged = with_printed_masthead(_OCR_3644, _LAYER_3644)
    assert merged is not None
    meta = extract_metadata(merged, DEPTS)
    assert (meta.canonical_id, meta.instrument) == ("AP-GAZ-GAZETTE-EI-3644-2024", "CIRCULAR_MEMO")


def test_a_note_citing_a_go_p_as_real_orders_print_it_is_read() -> None:
    """Type E on set v2: "G.O.(P).No.4, G.A.(Cabinet-II) Department, dt.28.11.2018" was not seen
    as a citation at all, so a missing authority raised nothing."""
    text = (
        "File No.GAD01-CABN0BR/204/2024-CABINET.II\nNote # 1\nSub: Allocation of business – Reg.\n"
        "Ref:\n1. G.O.(P).No.4, G.A.(Cabinet-II) Department, dt.28.11.2018.\n* * *\n"
        "1) It is submitted that a reference has been received.\n"
    )
    refs = [r for r in extract_metadata(text, DEPTS).references if not r.raw.startswith("file:")]
    assert [r.canonical_id for r in refs] == ["AP-GAD01-GOP-4-2018"]


def test_a_file_filed_as_gazette_that_prints_only_a_go_number_is_held_not_a_crash() -> None:
    """Whole-corpus run, 14 Nov 2026: three files in the gazette folder have no readable masthead
    and print a G.O. number with no department. The gazette source tag must not be borrowed as
    the order's department ("AP-GAZ-GOMS-49-2022" is not a valid ID and raised)."""
    text = (
        "GOVERNMENT OF ANDHRA PRADESH\nABSTRACT\n"
        "Rules - Amendment - Notification - Orders - Issued.\n"
        "G.O.Ms.No.49 Dated: 05-07-2022\nORDER:\nThe following notification shall be published.\n"
    )
    meta = extract_metadata(text, DEPTS, source_department="GAZ")
    assert meta.canonical_id is None
    assert any("not resolvable" in r for r in meta.review_reasons)
