"""The monitoring officer's pad (plan §10.4 FAQ analytics + operations; ADR-0035).

Everything the pad shows is computed here from the query log and the feedback records of the
chosen window: overview, the activity log, the questions asked most often, each officer's
activity, questions nothing answered (gaps in the records), the slowest answers, feedback, the
cache and the last start.

Access-aware (plan §10.4 "aggregate views are themselves access-aware"): a question's words are
shown only when the monitoring officer is cleared at least as high as the officer who asked it;
otherwise the row is kept and its words are withheld. The pad never shows document text.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.hitl.feedback import Action, HumanAction, TargetKind
from app.tracking.query_log import QueryRecord
from app.tracking.signals import AlertsView
from app.tracking.usage import Runner, Usage, summarise

WITHHELD = "(asked under a clearance above yours: words withheld)"


class ActivityRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    ts: dt.datetime
    query_id: str
    user_id: str
    role: str
    department: str
    section: str | None
    question: str | None
    withheld: bool
    intent: str | None
    outcome: str
    answered_by: str | None
    latency_ms: int
    cache_hit: bool
    cited: int
    feedback: str | None
    flags: tuple[str, ...] = ()  # unusual-activity signal codes (ADR-0036)


class FrequentQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str | None
    withheld: bool
    times: int
    officers: int
    answered_rate: float
    avg_ms: int
    last_asked: dt.datetime


class OfficerActivity(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    role: str
    department: str
    questions: int
    answered: int
    no_answer: int
    avg_ms: int
    thumbs_up: int
    thumbs_down: int
    last_seen: dt.datetime


class FeedbackRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    ts: dt.datetime
    user_id: str
    target: str
    action: str
    reason: str | None
    edit_share: float | None


class MonitorData(BaseModel):
    model_config = ConfigDict(frozen=True)

    since: dt.date
    overview: Usage
    activity: tuple[ActivityRow, ...]
    frequent: tuple[FrequentQuestion, ...]
    officers: tuple[OfficerActivity, ...]
    gaps: tuple[FrequentQuestion, ...]  # asked, and no authorised record answered
    slowest: tuple[ActivityRow, ...]
    feedback: tuple[FeedbackRow, ...]
    cache: dict[str, Any]
    truncated: bool  # the window held more records than the pad reads
    alerts: AlertsView | None = None  # unusual activity (ADR-0036)


def _visible(r: QueryRecord, viewer_rank: int) -> tuple[str | None, bool]:
    if not r.question:
        return None, False
    if r.clearance_rank is not None and viewer_rank >= r.clearance_rank:
        return r.question, False
    return None, True


def _grouped(
    rows: Sequence[QueryRecord], viewer_rank: int, top: int
) -> tuple[FrequentQuestion, ...]:
    by_q: dict[str, list[QueryRecord]] = defaultdict(list)
    for r in rows:
        by_q[r.query_hash].append(r)
    out = []
    for rs in by_q.values():
        # the words of the most recent ask this viewer may read (any one of them is the question)
        shown = next(
            (
                q
                for r in sorted(rs, key=lambda x: x.ts, reverse=True)
                if (q := _visible(r, viewer_rank)[0])
            ),
            None,
        )
        out.append(
            FrequentQuestion(
                question=shown,
                withheld=shown is None and any(r.question for r in rs),
                times=len(rs),
                officers=len({r.user_id for r in rs}),
                answered_rate=round(sum(r.answer_status == "answered" for r in rs) / len(rs), 3),
                avg_ms=int(statistics.fmean(r.latency_ms for r in rs)),
                last_asked=max(r.ts for r in rs),
            )
        )
    out.sort(key=lambda f: (-f.times, -f.officers, f.last_asked), reverse=False)
    return tuple(out[:top])


def build_monitor(
    records: Iterable[QueryRecord],
    actions: Iterable[HumanAction],
    since: dt.date,
    viewer_rank: int,
    *,
    start: Mapping[str, Any] | None = None,
    cache: Mapping[str, Any] | None = None,
    activity_rows: int = 200,
    truncated: bool = False,
    alerts: AlertsView | None = None,
) -> MonitorData:
    rows = sorted((r for r in records if r.ts.date() >= since), key=lambda r: r.ts, reverse=True)
    # the officers' feedback; a monitoring officer's alert reviews are not feedback (ADR-0036)
    acts = [a for a in actions if a.ts.date() >= since and a.target_kind is not TargetKind.ALERT]
    on_query: dict[str, str] = {}
    for a in sorted(acts, key=lambda a: a.ts):
        on_query[a.query_id] = a.action.value  # latest action per answer

    def row(r: QueryRecord) -> ActivityRow:
        q, held = _visible(r, viewer_rank)
        return ActivityRow(
            ts=r.ts,
            query_id=r.query_id,
            user_id=r.user_id,
            role=r.role,
            department=r.department,
            section=r.section,
            question=q,
            withheld=held,
            intent=r.intent,
            outcome=r.answer_status,
            answered_by=r.ladder_level,
            latency_ms=r.latency_ms,
            cache_hit=r.cache_hit,
            cited=len(r.cited_ids),
            feedback=on_query.get(r.query_id),
            flags=r.flags,
        )

    thumbs: dict[str, Counter[str]] = defaultdict(Counter)
    for a in acts:
        if a.action in (Action.THUMBS_UP, Action.THUMBS_DOWN):
            thumbs[a.user_id][a.action.value] += 1
    per: dict[str, list[QueryRecord]] = defaultdict(list)
    for r in rows:
        per[r.user_id].append(r)
    officers = sorted(
        (
            OfficerActivity(
                user_id=u,
                role=rs[0].role,
                department=rs[0].department,
                questions=len(rs),
                answered=sum(r.answer_status == "answered" for r in rs),
                no_answer=sum(r.answer_status == "no_answer" for r in rs),
                avg_ms=int(statistics.fmean(r.latency_ms for r in rs)),
                thumbs_up=thumbs[u]["thumbs_up"],
                thumbs_down=thumbs[u]["thumbs_down"],
                last_seen=rs[0].ts,
            )
            for u, rs in per.items()
        ),
        key=lambda o: -o.questions,
    )
    return MonitorData(
        since=since,
        overview=summarise(rows, acts, since, start),
        activity=tuple(row(r) for r in rows[:activity_rows]),
        frequent=_grouped(rows, viewer_rank, 20),
        officers=tuple(officers),
        gaps=_grouped([r for r in rows if r.answer_status == "no_answer"], viewer_rank, 20),
        slowest=tuple(row(r) for r in sorted(rows, key=lambda r: -r.latency_ms)[:10]),
        feedback=tuple(
            FeedbackRow(
                ts=a.ts,
                user_id=a.user_id,
                target=a.target_kind.value,
                action=a.action.value,
                reason=a.reason.value if a.reason else None,
                edit_share=a.edit_share,
            )
            for a in sorted(acts, key=lambda a: a.ts, reverse=True)[:100]
        ),
        cache=dict(cache or {}),
        truncated=truncated,
        alerts=alerts,
    )


# BigQuery: the window's rows through fixed SQL (the only parameters are the date and a limit);
# the same Python then builds the pad, so both sources give the same answer.
ROW_LIMIT = 5000
QUERIES_SQL = "SELECT * FROM `{table}` WHERE DATE(ts) >= @since ORDER BY ts DESC LIMIT @limit"
ACTIONS_SQL = QUERIES_SQL


def rows_from_bigquery(
    runner: Runner, query_table: str, action_table: str, since: dt.date
) -> tuple[list[QueryRecord], list[HumanAction], bool]:
    for t in (query_table, action_table):
        if not all(p.replace("-", "").replace("_", "").isalnum() for p in t.split(".")):
            raise ValueError("table must be project.dataset.table")
    p = [("since", "DATE", since), ("limit", "INT64", ROW_LIMIT)]
    qs = [
        QueryRecord.model_validate({k: v for k, v in r.items() if k in QueryRecord.model_fields})
        for r in runner.run(QUERIES_SQL.format(table=query_table), p)
    ]
    acts = [
        HumanAction.model_validate({k: v for k, v in r.items() if k in HumanAction.model_fields})
        for r in runner.run(ACTIONS_SQL.format(table=action_table), p)
    ]
    return qs, acts, len(qs) >= ROW_LIMIT
