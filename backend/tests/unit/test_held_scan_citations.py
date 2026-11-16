"""Regression (checkpoint eval, 4 Nov 2026): a cited order whose scan is still held for review was
reported as type E "not found in the records available to you" — on D28 and on the clean control
D24. The record exists; it is just not indexed yet. When the officer may see a record of the cited
order's department that is awaiting review, the E flag is kept but marked uncertain, says the order
may be awaiting review, the citation is listed in `awaiting_review`, and the held record itself is
never named (plan §6.2, §5.6).
"""

from __future__ import annotations

from app.conflict.deterministic import ConflictFlag, ConflictType
from app.conflict.presend import PreSendOutcome, PreSendReport, presend_check
from app.ingestion.pipeline import IngestStatus
from tests.unit.mock_access import CLASSES, POLICY, new_store
from tests.unit.test_agent_tools_and_memory import INSTRUMENTS, RELS
from tests.unit.test_conflict_procedural import RULES
from tests.unit.test_ingestion_pipeline import IDX
from tests.unit.test_presend import TAGS, _note

D13 = IDX["D13"]["canonical_id"]  # 2023 Works circular — a photo, held until Document AI
D01 = IDX["D01"]["canonical_id"]  # 2019 Finance order — a scan, open to every officer
D24 = IDX["D24"]["canonical_id"]  # a RESTRICTED Works note: Works officers only
HELD_D13 = {k: v for k, v in INSTRUMENTS.items() if k != D13}  # as the app runs without OCR


def _run(did: str, uid: str, awaiting: tuple[str, ...]) -> PreSendReport:
    text, meta = _note(did)
    return presend_check(
        IDX[did]["canonical_id"],
        text,
        meta,
        user_id=uid,
        instruments=HELD_D13,
        relations=[r for r in RELS if D13 not in (r.source, r.target)],
        tags_of={k: v for k, v in TAGS.items() if k != D13},
        rules=RULES,
        store=new_store(),
        policy=POLICY,
        classification=CLASSES,
        awaiting_review=tuple(TAGS[a] for a in awaiting),
    )


def _types(rep: PreSendReport) -> set[str]:
    return {f.type.value for f in rep.flags}


def _e(rep: PreSendReport) -> list[ConflictFlag]:
    return [f for f in rep.flags if f.type is ConflictType.E]


def test_without_awaiting_records_a_missing_citation_is_a_certain_type_e() -> None:
    rep = _run("D24", "U03", ())
    assert [f.certain for f in _e(rep)] == [True]
    assert "not found in the records available to you" in _e(rep)[0].explanation
    assert rep.awaiting_review == ()


def test_clean_control_citing_a_held_scan_is_not_told_the_order_is_missing() -> None:
    rep = _run("D24", "U03", (D13,))
    (e,) = _e(rep)
    assert not e.certain
    assert "awaiting review" in e.explanation
    assert "not found in the records available to you" not in e.explanation
    assert [a for a in rep.awaiting_review if a.startswith(D13)] == list(rep.awaiting_review)
    assert len(rep.awaiting_review) == 1
    assert rep.outcome is not PreSendOutcome.CLEAR


def test_d28_keeps_its_real_flags_and_its_e_becomes_uncertain() -> None:
    rep = _run("D28", "U03", (D13,))
    assert [f.certain for f in _e(rep)] == [False]
    assert ConflictType.C.value in _types(rep)
    assert rep.outcome is PreSendOutcome.CONFLICTS_FOUND


def test_a_held_record_the_officer_cannot_see_does_not_soften_e() -> None:
    """A held RESTRICTED Works note is out of the Estt.I SO's (U01) scope: it must not count."""
    rep = _run("D24", "U01", (D24,))
    assert [f.certain for f in _e(rep)] == [True]
    assert rep.awaiting_review == ()


def test_a_held_record_of_another_department_does_not_soften_e() -> None:
    """The Works SO cites a Works circular; a held Finance scan says nothing about it."""
    rep = _run("D24", "U03", (D01,))
    assert [f.certain for f in _e(rep)] == [True]


def test_the_report_never_names_the_held_record() -> None:
    rep = _run("D24", "U03", (D13,))
    held_uri = TAGS[D13].doc_id
    assert held_uri not in rep.model_dump_json()


def test_ingestion_tracks_held_records_until_they_are_indexed() -> None:
    from evaluation.harness.stack import build_stack

    from app.retrieval.ladder import LadderConfig

    cfg = LadderConfig(l2_top_k=10, l2_min_score=1.0, l3_max_hops=2)
    raw = build_stack(cfg, transcribe=False)
    assert "D13" in raw.stores.awaiting and raw.stores.awaiting["D13"].department == "USD01"
    full = build_stack(cfg, transcribe=True)
    assert "D13" not in full.stores.awaiting  # the confirmed text was indexed
    assert set(full.stores.awaiting) == set(raw.stores.awaiting) - set(full.transcribed)
    assert any(r.status is IngestStatus.HELD for r in raw.stores.results.values())
