"""Unusual-activity alerts for the monitoring officer (plan §10.4 audit + §4 security; ADR-0036).

Two parts:

1. **Signals on each question**, written into the query log as fixed codes (never text):
   ``instruction_like`` (words that read as instructions to the assistant — a prompt-injection or
   jailbreak attempt), ``bulk_request`` (everything at once, or records by restriction),
   ``named_unavailable`` (the question names an order the officer cannot open — hidden or
   non-existent, the same to the monitor as to the officer: no existence is revealed) and
   ``off_topic`` (outside what the assistant is for). The officer's answer is unchanged by any
   of them: nothing tells the asker a signal was recorded.

2. **Alerts**, worked out when the pad is opened, from the window's query records, the refused
   requests in the audit trail and the monitoring officers' reviews: repeated refusals in a short
   window (possible probing), instruction-like questions, attempts to open the monitoring pad,
   bulk requests, unusual volume, off-topic questions, after-hours use. Each is per officer per
   day, with a stable ID so a review stays attached.

Thresholds and patterns are MOCK (backend/config/monitoring.yaml) until the department sets them.
An alert asks a person to look; it is never a finding against an officer, and the assistant takes
no action on it.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from functools import cached_property
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.hitl.feedback import Action, HumanAction, TargetKind
from app.tracking.query_log import QueryRecord

INSTRUCTION_LIKE = "instruction_like"
BULK_REQUEST = "bulk_request"
NAMED_UNAVAILABLE = "named_unavailable"
OFF_TOPIC = "off_topic"
FLAGS = (INSTRUCTION_LIKE, BULK_REQUEST, NAMED_UNAVAILABLE, OFF_TOPIC)

# audit outcomes that mean "refused" (ADR-0016: hidden and unknown look the same)
REFUSED = frozenset({"denied", "not_available"})
PAD_ACTIONS = frozenset({"assist.monitor", "assist.usage", "assist.monitor.review"})

Severity = Literal["high", "medium", "low"]
_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


class Thresholds(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    refusals_in_window: int = Field(ge=2)
    window_minutes: int = Field(ge=1)
    questions_per_hour: int = Field(ge=1)
    off_topic_per_day: int = Field(ge=1)
    working_hours: tuple[int, int]
    utc_offset_minutes: int = Field(ge=-720, le=840)


class SignalConfig(BaseModel):
    """backend/config/monitoring.yaml — MOCK until the department decides (ADR-0036)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    status: str
    instruction_like: tuple[str, ...]
    bulk_request: tuple[str, ...]
    domain_terms: tuple[str, ...]
    thresholds: Thresholds

    @cached_property
    def _instruction(self) -> tuple[re.Pattern[str], ...]:
        return tuple(re.compile(p, re.I | re.S) for p in self.instruction_like)

    @cached_property
    def _bulk(self) -> tuple[re.Pattern[str], ...]:
        return tuple(re.compile(p, re.I | re.S) for p in self.bulk_request)

    @cached_property
    def _domain(self) -> re.Pattern[str]:
        return re.compile(
            r"(?<![a-z0-9])(?:" + "|".join(re.escape(t.lower()) for t in self.domain_terms) + ")"
        )

    def is_instruction_like(self, q: str) -> bool:
        return any(p.search(q) for p in self._instruction)

    def is_bulk(self, q: str) -> bool:
        return any(p.search(q) for p in self._bulk)

    def on_subject(self, q: str) -> bool:
        return bool(self._domain.search(" ".join(q.lower().split())))


def load_signal_config(path: Path) -> SignalConfig:
    return SignalConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def question_flags(
    cfg: SignalConfig,
    question: str,
    *,
    references: bool,
    named: bool,
    entities: bool,
    outcome: str | None,
    found: bool,
) -> tuple[str, ...]:
    """Fixed codes for one question. `references`: it cites an order (any reading); `named`: one
    of those resolved to a record the officer may open; `entities`: anything named or recalled;
    `found`: retrieval returned an authorised record."""
    out = []
    if cfg.is_instruction_like(question):
        out.append(INSTRUCTION_LIKE)
    if cfg.is_bulk(question):
        out.append(BULK_REQUEST)
    if references and not named:
        out.append(NAMED_UNAVAILABLE)
    if (
        outcome == "no_answer"
        and not references
        and not entities
        and not found
        and not cfg.on_subject(question)
    ):
        out.append(OFF_TOPIC)
    return tuple(out)


# --- alerts -------------------------------------------------------------------------------------


class Refusal(BaseModel):
    """A refused request from the audit trail: who, when, which kind of request. No IDs."""

    model_config = ConfigDict(frozen=True)

    ts: dt.datetime
    user_id: str
    action: str


class Person(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: str
    department: str


class AlertExample(BaseModel):
    model_config = ConfigDict(frozen=True)

    ts: dt.datetime
    query_id: str | None  # None for a refused page request (no question)
    what: str  # a fixed code: the flag, or the refused request kind
    question: str | None
    withheld: bool


class Alert(BaseModel):
    model_config = ConfigDict(frozen=True)

    alert_id: str
    rule: str
    severity: Severity
    title: str
    user_id: str
    role: str
    department: str
    day: dt.date
    first_seen: dt.datetime
    last_seen: dt.datetime
    count: int
    examples: tuple[AlertExample, ...]
    status: Literal["open", "reviewed", "escalated"] = "open"
    reviewed_by: str | None = None
    reviewed_at: dt.datetime | None = None


class DepartmentAlerts(BaseModel):
    model_config = ConfigDict(frozen=True)

    department: str
    high: int
    medium: int
    low: int
    open: int
    officers: int


class AlertsView(BaseModel):
    model_config = ConfigDict(frozen=True)

    config_version: str
    config_status: str
    alerts: tuple[Alert, ...]
    by_department: tuple[DepartmentAlerts, ...]
    by_rule: dict[str, int]


TITLES: dict[str, str] = {
    "repeated_refusals": "Repeated requests for records not open to them",
    "pad_probe": "Tried to open the monitoring pad",
    INSTRUCTION_LIKE: "Question reads as instructions to the assistant",
    BULK_REQUEST: "Asked for records in bulk or by restriction",
    NAMED_UNAVAILABLE: "Asked about an order not open to them",
    "volume_spike": "Unusually many questions in an hour",
    OFF_TOPIC: "Questions outside what the assistant is for",
    "after_hours": "Used outside working hours",
}


def alert_id(rule: str, user_id: str, day: dt.date) -> str:
    """Stable for one officer, rule and day, so a review stays attached when the pad is rebuilt."""
    return "AL-" + hashlib.sha256(f"{rule}|{user_id}|{day.isoformat()}".encode()).hexdigest()[:16]


def _max_in_window(times: Sequence[dt.datetime], minutes: int) -> int:
    ts = sorted(times)
    best, lo = 0, 0
    for hi, t in enumerate(ts):
        while t - ts[lo] > dt.timedelta(minutes=minutes):
            lo += 1
        best = max(best, hi - lo + 1)
    return best


def build_alerts(
    cfg: SignalConfig,
    records: Iterable[QueryRecord],
    refusals: Iterable[Refusal],
    reviews: Iterable[HumanAction],
    since: dt.date,
    viewer_rank: int,
    people: Mapping[str, Person] | None = None,
) -> AlertsView:
    """Alerts of the window, newest and most severe first (ADR-0036). A question's words appear
    only when the monitoring officer is cleared at least as high as the asker (ADR-0035)."""
    th = cfg.thresholds
    tz = dt.timezone(dt.timedelta(minutes=th.utc_offset_minutes))
    people = dict(people or {})
    recs = [r for r in records if r.ts.astimezone(tz).date() >= since]
    refs = [x for x in refusals if x.ts.astimezone(tz).date() >= since]
    for r in recs:  # the query log knows the asker's post and department at the time
        people.setdefault(r.user_id, Person(role=r.role, department=r.department))

    def day(t: dt.datetime) -> dt.date:
        return t.astimezone(tz).date()

    def words(r: QueryRecord) -> tuple[str | None, bool]:
        if not r.question:
            return None, False
        if r.clearance_rank is not None and viewer_rank >= r.clearance_rank:
            return r.question, False
        return None, True

    def ex_q(r: QueryRecord, what: str) -> AlertExample:
        q, held = words(r)
        return AlertExample(ts=r.ts, query_id=r.query_id, what=what, question=q, withheld=held)

    def ex_r(x: Refusal) -> AlertExample:
        return AlertExample(ts=x.ts, query_id=None, what=x.action, question=None, withheld=False)

    out: list[Alert] = []

    def raise_(
        rule: str, sev: Severity, uid: str, d: dt.date, items: list[AlertExample], count: int
    ) -> None:
        p = people.get(uid, Person(role="(unknown)", department="(unknown)"))
        items = sorted(items, key=lambda e: e.ts, reverse=True)
        out.append(
            Alert(
                alert_id=alert_id(rule, uid, d),
                rule=rule,
                severity=sev,
                title=TITLES[rule],
                user_id=uid,
                role=p.role,
                department=p.department,
                day=d,
                first_seen=min(e.ts for e in items),
                last_seen=max(e.ts for e in items),
                count=count,
                examples=tuple(items[:5]),
            )
        )

    q_by: dict[tuple[str, dt.date], list[QueryRecord]] = defaultdict(list)
    for r in recs:
        q_by[(r.user_id, day(r.ts))].append(r)
    x_by: dict[tuple[str, dt.date], list[Refusal]] = defaultdict(list)
    for x in refs:
        x_by[(x.user_id, day(x.ts))].append(x)

    for key in sorted(set(q_by) | set(x_by)):
        uid, d = key
        rs, xs = q_by.get(key, []), x_by.get(key, [])
        flagged = {f: [r for r in rs if f in r.flags] for f in FLAGS}

        pad = [x for x in xs if x.action in PAD_ACTIONS]
        if pad:
            raise_("pad_probe", "high", uid, d, [ex_r(x) for x in pad], len(pad))

        if flagged[INSTRUCTION_LIKE]:
            items = [ex_q(r, INSTRUCTION_LIKE) for r in flagged[INSTRUCTION_LIKE]]
            raise_(INSTRUCTION_LIKE, "high", uid, d, items, len(items))

        # refused requests: pages/records refused by the API + questions naming unavailable orders
        other = [x for x in xs if x.action not in PAD_ACTIONS]
        refused_at = [x.ts for x in other] + [r.ts for r in flagged[NAMED_UNAVAILABLE]]
        refused_items = [ex_r(x) for x in other] + [
            ex_q(r, NAMED_UNAVAILABLE) for r in flagged[NAMED_UNAVAILABLE]
        ]
        if _max_in_window(refused_at, th.window_minutes) >= th.refusals_in_window:
            raise_("repeated_refusals", "high", uid, d, refused_items, len(refused_items))
        elif flagged[NAMED_UNAVAILABLE]:
            items = [ex_q(r, NAMED_UNAVAILABLE) for r in flagged[NAMED_UNAVAILABLE]]
            raise_(NAMED_UNAVAILABLE, "low", uid, d, items, len(items))

        if flagged[BULK_REQUEST]:
            items = [ex_q(r, BULK_REQUEST) for r in flagged[BULK_REQUEST]]
            raise_(BULK_REQUEST, "medium", uid, d, items, len(items))

        if _max_in_window([r.ts for r in rs], 60) > th.questions_per_hour:
            raise_("volume_spike", "medium", uid, d, [ex_q(r, "question") for r in rs], len(rs))

        if flagged[OFF_TOPIC]:
            n = len(flagged[OFF_TOPIC])
            sev: Severity = "medium" if n >= th.off_topic_per_day else "low"
            raise_(OFF_TOPIC, sev, uid, d, [ex_q(r, OFF_TOPIC) for r in flagged[OFF_TOPIC]], n)

        start, end = th.working_hours
        late = [r for r in rs if not start <= r.ts.astimezone(tz).hour < end]
        if late:
            raise_("after_hours", "low", uid, d, [ex_q(r, "question") for r in late], len(late))

    latest: dict[str, HumanAction] = {}
    for a in sorted(reviews, key=lambda a: a.ts):
        if a.target_kind is TargetKind.ALERT:
            latest[a.query_id] = a
    status = {Action.REVIEWED: "reviewed", Action.ESCALATED: "escalated"}
    done = []
    for al in out:
        rv = latest.get(al.alert_id)
        if rv is not None and rv.action in status:
            al = al.model_copy(
                update={
                    "status": status[rv.action],
                    "reviewed_by": rv.user_id,
                    "reviewed_at": rv.ts,
                }
            )
        done.append(al)
    done.sort(key=lambda a: (a.status != "open", _RANK[a.severity], -a.last_seen.timestamp()))

    deps: dict[str, list[Alert]] = defaultdict(list)
    for al in done:
        deps[al.department].append(al)
    by_department = tuple(
        sorted(
            (
                DepartmentAlerts(
                    department=k,
                    high=sum(a.severity == "high" for a in v),
                    medium=sum(a.severity == "medium" for a in v),
                    low=sum(a.severity == "low" for a in v),
                    open=sum(a.status == "open" for a in v),
                    officers=len({a.user_id for a in v}),
                )
                for k, v in deps.items()
            ),
            key=lambda x: (-x.high, -x.open, x.department),
        )
    )
    by_rule: dict[str, int] = defaultdict(int)
    for al in done:
        by_rule[al.rule] += 1
    return AlertsView(
        config_version=cfg.version,
        config_status=cfg.status,
        alerts=tuple(done),
        by_department=by_department,
        by_rule=dict(by_rule),
    )
