"""Action windows stated inside orders, and type F for the proposal's own date (plan §6.1, §6.2,
§6.4). D27 proposes a transfer on 22-09-2026; the only relaxation of the ban in force is
G.O.Ms.31/2025 para 2(i), 15-05-2025 to 31-05-2025."""

from __future__ import annotations

import datetime as dt

from app.conflict.deterministic import ConflictType
from app.conflict.windows import check_action_window
from app.ingestion.pipeline import IngestionStores
from app.temporal.engine import Instrument, RelationKind, TemporalRelation
from app.temporal.windows import windows_from_text
from tests.unit.mock_access import CORPUS
from tests.unit.test_agent_tools_and_memory import INSTRUMENTS, RELS
from tests.unit.test_ingestion_pipeline import IDX, _ingest
from tests.unit.test_presend import _run

CID = {d: IDX[d]["canonical_id"] for d in IDX}
WINDOWS = [
    w
    for d in ("D01", "D03", "D04")
    for w in windows_from_text(CID[d], (CORPUS / "ground_truth" / "text" / f"{d}.txt").read_text())
]


def _check(day: dt.date, known=INSTRUMENTS, rels=RELS):  # type: ignore[no-untyped-def]
    return check_action_window("transfer", day, WINDOWS, known, list(rels))


def test_window_read_with_its_clause_and_words() -> None:
    d04 = [w for w in WINDOWS if w.document_id == CID["D04"]]
    assert len(d04) == 1
    w = d04[0]
    assert w.source == "AP-FIN01-GOMS-31-2025#para-2.i"
    assert (w.start, w.end) == (dt.date(2025, 5, 15), dt.date(2025, 5, 31))
    assert "ban on transfers is relaxed" in w.evidence


def test_wrapped_lines_and_non_matching_sentences() -> None:
    text = (
        "2. Accordingly, the Government issue the following:\n"
        "(i) The ban on transfers is relaxed for the period from 15-05-2025 to\n"
        "31-05-2025.\n"
        "(iv) No relaxation of this ceiling shall be made without concurrence.\n"
        "3. After 31-05-2025 the ban on transfers shall come into force again.\n"
    )
    ws = windows_from_text("AP-FIN01-GOMS-31-2025", text)
    assert [(w.source, w.end) for w in ws] == [
        ("AP-FIN01-GOMS-31-2025#para-2.i", dt.date(2025, 5, 31))
    ]
    so = (CORPUS / "ground_truth" / "text" / "D11.txt").read_text()
    assert windows_from_text(CID["D11"], so) == ()  # mentions relaxation, opens no window


def test_outside_the_window_in_force_is_flagged_with_its_clause() -> None:
    flag = _check(dt.date(2026, 9, 22))  # D27
    assert flag is not None and flag.type is ConflictType.F
    assert flag.cited == "AP-FIN01-GOMS-31-2025#para-2.i"
    assert flag.evidence_ids == (CID["D04"],) and flag.certain
    assert "15-05-2025 to 31-05-2025" in flag.explanation


def test_inside_the_window_is_not_flagged() -> None:
    assert _check(dt.date(2025, 5, 27)) is None  # D19, approved within the 2025 window
    assert _check(dt.date(2022, 6, 20)) is None  # D17, within the 2022 window


def test_only_the_order_in_force_counts() -> None:
    """2 Sep 2023 (D18): G.O.Ms.88/2022 is in force; its window closed on 30-06-2022."""
    flag = _check(dt.date(2023, 9, 2))
    assert flag is not None and flag.cited == "AP-FIN01-GOMS-88-2022#para-2.i"


def test_no_order_for_the_action_or_none_visible_means_no_basis() -> None:
    assert (
        check_action_window("works_sanction", dt.date(2026, 9, 22), WINDOWS, INSTRUMENTS, [])
        is None
    )
    assert _check(dt.date(2026, 9, 22), known={}) is None  # officer sees none of the orders


def test_an_amended_order_makes_the_flag_uncertain() -> None:
    amend = TemporalRelation(
        source="AP-FIN01-GOMS-99-2025", kind=RelationKind.AMENDS, target=CID["D04"]
    )
    known = {
        **INSTRUMENTS,
        "AP-FIN01-GOMS-99-2025": Instrument(
            canonical_id="AP-FIN01-GOMS-99-2025",
            hierarchy_level=4,
            effective_from=dt.date(2025, 6, 1),
        ),
    }
    flag = _check(dt.date(2026, 9, 22), known=known, rels=(*RELS, amend))
    assert flag is not None and not flag.certain and "amended" in flag.explanation


def test_presend_d27_now_flags_f_uncertain_without_full_coverage() -> None:
    rep = _run("D27", "U01")
    f = [x for x in rep.flags if x.type is ConflictType.F]
    assert len(f) == 1 and f[0].cited.endswith("#para-2.i")
    assert not f[0].certain  # the Estt.I SO cannot see every Finance order on transfers
    assert "may not show every later order" in f[0].explanation
    assert _run("D19", "U01").flags == ()  # inside the window: clean


def test_ingestion_stores_the_windows() -> None:
    stores = IngestionStores()
    res = _ingest(stores, "D04")
    assert [w.source for w in stores.windows[res.canonical_id]] == [f"{res.canonical_id}#para-2.i"]
