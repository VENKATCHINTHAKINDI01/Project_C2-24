"""'File so far' (touchpoint 8): note chain by post, last direction, gaps named — never filled
(plan §11.5; TP08 answer key: "Notes #4–#5 are not available (say so; do not fill the gap)")."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

from app.ingestion.detect import detect_file
from app.ingestion.extract import extract_native
from app.noting.chain import file_so_far, parse_notes
from tests.unit.mock_access import CORPUS, rows

IDX = {r["id"]: r for r in rows("documents_index.csv")}


def _native(did: str) -> str:
    p = Path(CORPUS / IDX[did]["file"])
    return extract_native(p.read_bytes(), detect_file(p)).native_text


D22 = (CORPUS / "ground_truth" / "text" / "D22.txt").read_text("utf-8")  # scanned: hand text


def test_three_line_signatures_and_paragraph_numbers() -> None:
    notes = parse_notes(_native("D21"), "D21")
    assert [(n.note_no, n.post) for n in notes] == [
        (1, "Section Officer (Vigilance)"),
        (2, "Deputy Secretary"),
        (3, "Secretary to Government"),
    ]
    assert notes[0].paragraphs == (1, 3) and notes[0].signed_at == dt.datetime(2025, 4, 9, 11, 5)
    assert notes[2].text == "5. Approved. Order preliminary enquiry. Keep the file confidential."


def test_one_line_signatures() -> None:
    notes = parse_notes(D22, "D22")
    assert [(n.note_no, n.signer, n.post) for n in notes][2] == (
        8,
        "R. Vasantha Kumari",
        "Secretary to Government",
    )
    assert notes[0].paragraphs == (1, 2)


def test_page_furniture_inside_a_note_is_ignored() -> None:
    """D17 Note #5 breaks across a page: classification marks and footer sit inside it."""
    last = parse_notes(_native("D17"), "D17")[-1]
    assert last.note_no == 5 and last.post == "Secretary to Government"
    assert last.text == "9. Approved. Issue orders."


def test_chain_gaps_and_last_direction() -> None:
    fs = file_so_far([("D21", _native("D21")), ("D22", D22)])
    assert [n.note_no for n in fs.notes] == [1, 2, 3, 6, 7, 8]
    assert fs.gaps == ((4, 5),)  # named, not filled
    assert fs.chain == (
        "Section Officer (Vigilance)",
        "Deputy Secretary",
        "Secretary to Government",
        "Section Officer (Vigilance)",
        "Deputy Secretary",
        "Secretary to Government",
    )
    assert fs.last_direction is not None and fs.last_direction.note_no == 8
    assert "Issue charge memo" in fs.last_direction.text
    assert fs.sources == ("D21", "D22")


def test_nothing_visible_means_nothing_said() -> None:
    fs = file_so_far([])
    assert fs.notes == () and fs.gaps == () and fs.last_direction is None
