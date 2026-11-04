"""Canonical ID parser and reference normaliser (plan §4.4, §13.2 'Canonical IDs')."""

from __future__ import annotations

import csv
import datetime as dt

import pytest

from app.config import REPO_ROOT
from app.identifiers.canonical import (
    InvalidCanonicalIdError,
    clause_id,
    is_canonical_id,
    lookup_keys,
    parse_canonical_id,
)
from app.identifiers.resolver import Unresolved, load_departments, resolve_reference

DEPTS = load_departments(REPO_ROOT / "data" / "ontology" / "departments.yaml")
CORPUS = REPO_ROOT / "data" / "synthetic" / "mock_v1"


def _index() -> list[dict[str, str]]:
    with (CORPUS / "documents_index.csv").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@pytest.mark.parametrize("row", _index(), ids=lambda r: r["id"])
def test_every_corpus_id_parses_and_round_trips(row: dict[str, str]) -> None:
    cid = parse_canonical_id(row["canonical_id"])
    assert cid.render() == row["canonical_id"]
    assert cid.department == row["department"]


@pytest.mark.parametrize(
    "text",
    [
        "AP-FIN01-CIRMEMO-FIN01COOROMISC-93-2023-D20240305",
        "AP-GAZ-GAZETTE-EI-137-2024",
        "AP-USD01-NOTE-USD0131-4-2025-R1",
        "AP-FIN01-GOMS-88-2022#para-2.v",
    ],
)
def test_extended_forms_round_trip(text: str) -> None:
    assert str(parse_canonical_id(text)) == text


def test_date_tag_and_base_id() -> None:
    cid = parse_canonical_id("AP-FIN01-CIRMEMO-FIN01COOROMISC-93-2023-D20240305")
    assert cid.date_tag == "20240305"
    assert cid.suffix is None
    assert cid.base_id == "AP-FIN01-CIRMEMO-FIN01COOROMISC-93-2023"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "FIN01-GOMS-88-2022",
        "AP-FIN01-GOMS-088-2022",
        "AP-FIN01-GOMS-88-22",
        "AP-FIN01-XYZ-88-2022",
        "AP-GAZ-GOMS-1-2024",
        "AP-fin01-GOMS-88-2022",
        "AP-FIN01-GOMS-88-2022#",
    ],
)
def test_malformed_ids_rejected(bad: str) -> None:
    assert not is_canonical_id(bad)
    with pytest.raises(InvalidCanonicalIdError):
        parse_canonical_id(bad)


def test_clause_id() -> None:
    assert clause_id("AP-FIN01-GOMS-88-2022", "2(v)") == "AP-FIN01-GOMS-88-2022#para-2.v"
    assert clause_id("AP-FIN01-GOMS-88-2022", "3.2") == "AP-FIN01-GOMS-88-2022#para-3.2"
    with pytest.raises(InvalidCanonicalIdError):
        clause_id("AP-FIN01-GOMS-88-2022#para-1", "2")


@pytest.mark.parametrize(
    "text",
    [
        "G.O.Ms.No.45, Finance (HR.I) Department, Dt.12-05-2023",
        "GO Ms 45/2023",
        "G.O.(Ms) No. 45, dated 12.05.2023",
        "G.O.MS.No.45 Dt.12/05/23",
        "G.0.Ms.No.45, Dt.12-05-2023",
        "in G.O.Ms.No. 45, FIN01 Department, dated 12-05-2023 (Flag A)",
    ],
)
def test_go_variants_resolve_to_one_id(text: str) -> None:
    r = resolve_reference(text, DEPTS, default_dept="FIN01")
    assert r.canonical_id == "AP-FIN01-GOMS-45-2023"


def test_department_in_reference_beats_default() -> None:
    r = resolve_reference(
        "G.O.Ms.No.19, General Administration (Ser.A) Department, Dt.09-02-2018",
        DEPTS,
        default_dept="FIN01",
    )
    assert r.canonical_id == "AP-GAD01-GOMS-19-2018"
    assert r.issue_date == dt.date(2018, 2, 9)


def test_unknown_named_department_is_not_guessed() -> None:
    r = resolve_reference(
        "G.O.Ms.No.7, Revenue (Lands) Department, Dt.01-01-2020", DEPTS, default_dept="FIN01"
    )
    assert r.canonical_id is None and r.unresolved is Unresolved.NO_DEPARTMENT


def test_missing_year_is_not_guessed() -> None:
    r = resolve_reference("G.O.Ms.No.62 read above", DEPTS, default_dept="FIN01")
    assert r.canonical_id is None and r.unresolved is Unresolved.NO_YEAR


def test_no_default_department_means_unresolved() -> None:
    r = resolve_reference("G.O.Ms.No.62, Dt.14-06-2019", DEPTS)
    assert r.unresolved is Unresolved.NO_DEPARTMENT


def test_rt_order_and_nonexistent_order_still_resolve() -> None:
    """Resolution ≠ existence: G.O.Ms.104/2026 is not in the corpus; that is type E's lookup."""
    r = resolve_reference(
        "G.O.Ms.No.104, Finance (HR.I) Department, Dt.02-01-2026", DEPTS, default_dept="USD01"
    )
    assert r.canonical_id == "AP-FIN01-GOMS-104-2026"
    assert resolve_reference("G.O.Rt.No.1184, Dt.21-03-2025", DEPTS, "FIN01").canonical_id == (
        "AP-FIN01-GORT-1184-2025"
    )


def test_memo_forms_carry_issue_date_tag_by_default() -> None:
    """ADR-0007 (accepted 2026-11-03): memo / circular memo / Rc IDs end with -D<yyyymmdd>."""
    r = resolve_reference("Memo No.FIN01-HRPLG0(TRF)/3/2025-2, Dt.21-05-2025", DEPTS)
    assert r.canonical_id == "AP-FIN01-MEMO-FIN01HRPLG0TRF-3-2025-2-D20250521"
    tagged = resolve_reference("Circular Memo No.FINO1-COORO(MISC)/93/2023, Dt.05-03-2024", DEPTS)
    assert tagged.canonical_id == "AP-FIN01-CIRMEMO-FIN01COOROMISC-93-2023-D20240305"
    rc = resolve_reference("Rc.No.USD01-WRKS0/22/2025, Dt.02-06-2025", DEPTS)
    assert rc.canonical_id == "AP-USD01-RC-USD01WRKS0-22-2025-D20250602"
    plain = resolve_reference(
        "Rc.No.USD01-WRKS0/22/2025, Dt.02-06-2025", DEPTS, memo_date_tag=False
    )
    assert plain.canonical_id == "AP-USD01-RC-USD01WRKS0-22-2025"


def test_undated_memo_gets_no_tag() -> None:
    r = resolve_reference("Memo No.FIN01-HRPLG0(TRF)/3/2025", DEPTS)
    assert r.canonical_id == "AP-FIN01-MEMO-FIN01HRPLG0TRF-3-2025"


def test_lookup_keys_bridge_tagged_and_untagged_ids() -> None:
    assert lookup_keys("AP-USD01-RC-USD01WRKS0-22-2025-D20250602") == (
        "AP-USD01-RC-USD01WRKS0-22-2025-D20250602",
        "AP-USD01-RC-USD01WRKS0-22-2025",
    )
    assert lookup_keys("AP-FIN01-GOMS-88-2022#para-2") == ("AP-FIN01-GOMS-88-2022",)


def test_standing_order_needs_default_department() -> None:
    assert resolve_reference("Standing Order No.2/2020", DEPTS).unresolved is (
        Unresolved.NO_DEPARTMENT
    )
    assert resolve_reference("Standing Order No.2/2020", DEPTS, "USD01").canonical_id == (
        "AP-USD01-SO-2-2020"
    )


def test_file_reference_returns_file_number_only() -> None:
    r = resolve_reference("File No. USD01-12/19/2026-ESTT.I (Computer No. 2894562)", DEPTS)
    assert r.doc_type == "FILE" and r.canonical_id is None
    assert r.file_no == "USD01-12/19/2026-ESTT.I"


def test_plain_text_is_not_a_reference() -> None:
    r = resolve_reference("spouse cases shall be given preference", DEPTS, "FIN01")
    assert r.unresolved is Unresolved.NOT_A_REFERENCE


@pytest.mark.parametrize(
    "row",
    [r for r in _index() if not r["raw_reference"].startswith("File No.")],
    ids=lambda r: r["id"],
)
def test_corpus_own_references_resolve_to_their_ids(row: dict[str, str]) -> None:
    """Each own reference resolves to its ID. Mock v1 predates ADR-0007, so memo IDs match via
    `lookup_keys` (exact, then without the date tag)."""
    r = resolve_reference(row["raw_reference"], DEPTS, default_dept=row["department"])
    assert r.canonical_id is not None
    assert row["canonical_id"] in lookup_keys(r.canonical_id)
