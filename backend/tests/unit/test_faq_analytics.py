"""FAQ analytics on the monitoring pad (plan §10.4; ADR-0059): reworded asks grouped as one
question, breakdowns by department / role / intent, subject topics from readable questions only,
re-asked questions."""

from __future__ import annotations

import datetime as dt

from app.tracking.monitor import build_monitor
from app.tracking.query_log import QueryRecord

SINCE = dt.date(2026, 11, 1)


def _rec(
    qid: int,
    user: str,
    q: str,
    *,
    rank: int = 1,
    status: str = "answered",
    dept: str = "USD01",
    role: str = "Section Officer",
    intent: str = "precedent_lookup",
    flags: tuple[str, ...] = (),
    entities: tuple[str, ...] = (),
) -> QueryRecord:
    return QueryRecord(
        query_id=f"q{qid}",
        ts=dt.datetime(2026, 11, 15, 9, qid, tzinfo=dt.UTC),
        session_id="s",
        turn=1,
        user_id=user,
        department=dept,
        section="ESTT.I",
        role=role,
        query_hash=" ".join(q.lower().split()),
        intent=intent,
        entities=entities,
        ladder_level="L2",
        scope_signature="sig",
        latency_ms=1000,
        answer_status=status,
        question=q,
        clearance_rank=rank,
        flags=flags,
    )


def test_the_same_question_in_other_words_is_one_faq_entry() -> None:
    recs = [
        _rec(1, "U01", "Has a spouse transfer request been decided before?"),
        _rec(2, "U02", "Please, has a spouse transfer request been decided before?"),
        _rec(3, "U01", "has a spouse transfer request been decided before", flags=("reask",)),
        _rec(4, "U02", "What is the ceiling on transfers?", intent="current_rule"),
    ]
    m = build_monitor(recs, [], SINCE, viewer_rank=3)
    top = m.frequent[0]
    assert (top.times, top.variants, top.officers, top.reasked) == (3, 3, 2, 1)
    assert m.reasked == 1 and len(m.frequent) == 2


def test_questions_about_different_orders_are_never_grouped() -> None:
    recs = [
        _rec(1, "U01", "Is this order in force?", entities=("AP-FIN01-GOMS-88-2022",)),
        _rec(2, "U01", "Is this order in force?", entities=("AP-FIN01-GOMS-31-2025",)),
    ]
    assert len(build_monitor(recs, [], SINCE, viewer_rank=3).frequent) == 2


def test_breakdowns_by_department_role_and_intent() -> None:
    recs = [
        _rec(1, "U01", "Spouse transfer precedent?"),
        _rec(
            2,
            "U07",
            "Outsourcing ceiling?",
            dept="FIN01",
            status="no_answer",
            intent="current_rule",
        ),
        _rec(3, "U06", "Vigilance matters?", role="Secretary", flags=("reask",)),
    ]
    m = build_monitor(recs, [], SINCE, viewer_rank=3)
    by_dept = {b.name: (b.questions, b.no_answer) for b in m.by_department}
    assert by_dept == {"USD01 · ESTT.I": (2, 0), "FIN01 · ESTT.I": (1, 1)}
    assert {b.name: b.reasked for b in m.by_role} == {"Section Officer": 0, "Secretary": 1}
    assert {b.name for b in m.by_intent} == {"precedent_lookup", "current_rule"}


def test_topics_come_only_from_questions_the_viewer_may_read() -> None:
    """A withheld question's words are never counted: the topic list must not hint at what a
    higher-cleared officer asked."""
    recs = [
        _rec(1, "U01", "Spouse transfer precedent in Guntur?"),
        _rec(2, "U02", "Spouse transfer relaxation period?", status="no_answer"),
        _rec(3, "U06", "Vigilance enquiry against the superintendent?", rank=4),
        _rec(4, "U06", "Vigilance enquiry charges framed?", rank=4),
    ]
    low = {t.word: (t.questions, t.no_answer) for t in build_monitor(recs, [], SINCE, 1).topics}
    assert low["spouse"] == (2, 1) and low["transfer"] == (2, 1)
    assert "vigilance" not in low and "enquiry" not in low
    high = {t.word for t in build_monitor(recs, [], SINCE, 4).topics}
    assert {"vigilance", "enquiry"} <= high


def test_word_forms_count_as_one_topic() -> None:
    recs = [
        _rec(1, "U01", "Spouse transfer precedent?"),
        _rec(2, "U02", "Spouse transfers in 2025?"),
    ]
    topics = {t.word: t.questions for t in build_monitor(recs, [], SINCE, 3).topics}
    assert topics.get("transfer") == 2 and "transfers" not in topics
