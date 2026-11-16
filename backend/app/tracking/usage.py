"""Usage dashboard figures from the query log and the officers' feedback (plan §10.4; ADR-0034).

Aggregates only — counts, rates and times per day. No question text exists in the log, and the
dashboard shows no user, document or file ID. Two sources with the same answer: the in-memory
logs (sandbox, tests) and BigQuery (`<prefix>_audit.query_log` / `human_action`) through fixed
SQL whose only parameter is the number of days.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.hitl.feedback import HumanAction, TargetKind
from app.tracking.query_log import QueryRecord

OUTCOMES = ("answered", "review_needed", "no_answer", "not_run", "denied")


class DayUsage(BaseModel):
    model_config = ConfigDict(frozen=True)

    day: dt.date
    questions: int
    answered: int
    no_answer: int
    cache_hits: int
    p50_ms: int | None
    p90_ms: int | None


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True)

    since: dt.date
    days: tuple[DayUsage, ...]
    questions: int
    outcomes: dict[str, int]
    cache_hit_rate: float | None
    no_answer_rate: float | None
    p50_ms: int | None
    p90_ms: int | None
    answered_by: dict[str, int]  # search step that answered (L0..L3, or none)
    feedback: dict[str, int]  # thumbs_up, thumbs_down, confirmed, ... (counts)
    start: dict[str, Any] = Field(default_factory=dict)  # last sandbox build: when, seconds, warm


def _pct(values: Sequence[int], q: float) -> int | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return int(statistics.quantiles(sorted(values), n=100, method="inclusive")[round(q * 100) - 1])


def summarise(
    records: Iterable[QueryRecord],
    actions: Iterable[HumanAction],
    since: dt.date,
    start: Mapping[str, Any] | None = None,
) -> Usage:
    rows = [r for r in records if r.ts.date() >= since]
    by_day: dict[dt.date, list[QueryRecord]] = defaultdict(list)
    for r in rows:
        by_day[r.ts.date()].append(r)
    days = tuple(
        DayUsage(
            day=d,
            questions=len(rs),
            answered=sum(r.answer_status == "answered" for r in rs),
            no_answer=sum(r.answer_status == "no_answer" for r in rs),
            cache_hits=sum(r.cache_hit for r in rs),
            p50_ms=_pct([r.latency_ms for r in rs], 0.5),
            p90_ms=_pct([r.latency_ms for r in rs], 0.9),
        )
        for d, rs in sorted(by_day.items())
    )
    n = len(rows)
    outcomes = Counter(r.answer_status for r in rows)
    times = [r.latency_ms for r in rows]
    return Usage(
        since=since,
        days=days,
        questions=n,
        outcomes={k: outcomes.get(k, 0) for k in OUTCOMES},
        cache_hit_rate=round(sum(r.cache_hit for r in rows) / n, 3) if n else None,
        no_answer_rate=round(outcomes.get("no_answer", 0) / n, 3) if n else None,
        p50_ms=_pct(times, 0.5),
        p90_ms=_pct(times, 0.9),
        answered_by=dict(Counter(r.ladder_level or "none" for r in rows)),
        feedback=dict(
            Counter(
                a.action.value
                for a in actions
                if a.ts.date() >= since and a.target_kind is not TargetKind.ALERT
            )
        ),
        start=dict(start or {}),
    )


class Runner(Protocol):
    def run(self, sql: str, params: Sequence[tuple[str, str, Any]]) -> list[Mapping[str, Any]]: ...


# Fixed SQL; {qtable}/{atable} are validated table names, @since the only parameter.
DAYS_SQL = (
    "SELECT DATE(ts) AS day, COUNT(*) AS questions, "
    "COUNTIF(answer_status = 'answered') AS answered, "
    "COUNTIF(answer_status = 'no_answer') AS no_answer, COUNTIF(cache_hit) AS cache_hits, "
    "APPROX_QUANTILES(latency_ms, 100)[OFFSET(50)] AS p50_ms, "
    "APPROX_QUANTILES(latency_ms, 100)[OFFSET(90)] AS p90_ms "
    "FROM `{qtable}` WHERE DATE(ts) >= @since GROUP BY day ORDER BY day"
)
TOTALS_SQL = (
    "SELECT answer_status, IFNULL(ladder_level, 'none') AS rung, cache_hit, COUNT(*) AS n "
    "FROM `{qtable}` WHERE DATE(ts) >= @since GROUP BY answer_status, rung, cache_hit"
)
TIMES_SQL = (
    "SELECT APPROX_QUANTILES(latency_ms, 100)[OFFSET(50)] AS p50_ms, "
    "APPROX_QUANTILES(latency_ms, 100)[OFFSET(90)] AS p90_ms "
    "FROM `{qtable}` WHERE DATE(ts) >= @since"
)
ACTIONS_SQL = (
    "SELECT action, COUNT(*) AS n FROM `{atable}` WHERE DATE(ts) >= @since "
    "AND target_kind != 'alert' GROUP BY action"  # officers' feedback only (ADR-0036)
)


def _table(name: str) -> str:
    if not all(p.replace("-", "").replace("_", "").isalnum() for p in name.split(".")):
        raise ValueError("table must be project.dataset.table")
    return name


def summarise_bigquery(
    runner: Runner,
    query_table: str,
    action_table: str,
    since: dt.date,
    start: Mapping[str, Any] | None = None,
) -> Usage:
    q, a = _table(query_table), _table(action_table)
    p = [("since", "DATE", since)]
    days = tuple(DayUsage.model_validate(dict(r)) for r in runner.run(DAYS_SQL.format(qtable=q), p))
    outcomes: Counter[str] = Counter()
    rungs: Counter[str] = Counter()
    hits = 0
    for r in runner.run(TOTALS_SQL.format(qtable=q), p):
        outcomes[str(r["answer_status"])] += int(r["n"])
        rungs[str(r["rung"])] += int(r["n"])
        hits += int(r["n"]) if r["cache_hit"] else 0
    times = runner.run(TIMES_SQL.format(qtable=q), p)
    t = times[0] if times else {}
    n = sum(outcomes.values())
    feedback = {str(r["action"]): int(r["n"]) for r in runner.run(ACTIONS_SQL.format(atable=a), p)}
    return Usage(
        since=since,
        days=days,
        questions=n,
        outcomes={k: outcomes.get(k, 0) for k in OUTCOMES},
        cache_hit_rate=round(hits / n, 3) if n else None,
        no_answer_rate=round(outcomes.get("no_answer", 0) / n, 3) if n else None,
        p50_ms=t.get("p50_ms"),
        p90_ms=t.get("p90_ms"),
        answered_by=dict(rungs),
        feedback=feedback,
        start=dict(start or {}),
    )
