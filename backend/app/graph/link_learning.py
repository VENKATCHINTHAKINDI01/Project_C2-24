"""Learning the links between orders from officers' work (ADR-0074; plan §3.6, §8).

CLAUDE.md §5.7, §6 and §8 apply.

What this module decides, and what it never decides:
- It keeps officers' signals on a link (Useful / Not right, and later the signals of their work) and
  their explicit decisions (validate / reject / ask for more evidence), with who, post, department,
  time and the governance version in force.
- From the signals it may say a link is SUPPORTED_BY_USE: operational support only.
- A link is VALIDATED only by (a) the newer order's own text stating it (an extracted, confirmed
  edge), or (b) an authenticated officer's validate decision, made by a post the governance config
  allows, within their department, on records they may open, with the sentence of the newer order
  that establishes it. Usage and approvals never validate (owner, 27 Nov 2026).
- The state is computed from the records at read time; a changed threshold can move a link in or
  out of SUPPORTED_BY_USE, never into VALIDATED (no retroactive legal status).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import threading
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Protocol

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.auth.models import DocumentAccessTags, Scope
from app.graph.repository import Direction, EdgeKind, GraphEdge, GraphNode, GraphRepository
from app.pg import Pg

# legally consequential relations: validation needs an authenticated human decision (rule 4)
CONSEQUENTIAL = frozenset({"SUPERSEDES", "AMENDS", "REPEALS"})
LINK_KINDS = CONSEQUENTIAL | {"CLARIFIES"}


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Permission(StrEnum):
    VIEW = "view"  # sees the AI's findings
    FLAG = "flag"  # also sees the evidence and flags corrections (Useful / Not right)
    VALIDATE = "validate"  # also validates, rejects, asks for more evidence

    @property
    def rank(self) -> int:
        return {"view": 0, "flag": 1, "validate": 2}[self.value]


class Designation(_Frozen):
    post: str = Field(min_length=2)
    permission: Permission


class ValidationAuthority(_Frozen):
    status: Literal["TO_CONFIRM", "CONFIRMED"]
    minimum_designation: str
    department_scoped: bool = True
    require_authenticated_identity: Literal[True] = True
    default_permission: Permission = Permission.VIEW
    designations: tuple[Designation, ...]


class UsageSupport(_Frozen):
    enabled: bool = True
    minimum_score: int = Field(5, ge=1)
    minimum_distinct_officers: int = Field(2, ge=2)
    max_score_per_officer: int = Field(3, ge=1)  # one officer cannot carry a link alone
    exclude_test_activity: bool = True
    exclude_automated_activity: bool = True
    test_officers: tuple[str, ...] = ()


class LegalValidation(_Frozen):
    # fixed by the owner's rules: these cannot be switched on in the config
    auto_validate_from_usage: Literal[False] = False
    auto_validate_from_approval: Literal[False] = False
    require_human_validation: Literal[True] = True
    require_documentary_evidence: Literal[True] = True


class Governance(_Frozen):
    version: str = Field(min_length=1)
    validation_authority: ValidationAuthority
    usage_support: UsageSupport
    legal_validation: LegalValidation
    signal_weights: dict[str, int]

    def permission(self, post: str) -> Permission:
        """The post's permission: the longest configured designation the post starts with
        ("Section Officer, Finance" → "Section Officer"); posts not listed get the default."""
        p = post.strip().lower()
        best: Designation | None = None
        for d in self.validation_authority.designations:
            if p.startswith(d.post.lower()) and (best is None or len(d.post) > len(best.post)):
                best = d
        return best.permission if best else self.validation_authority.default_permission

    def may_validate(self, post: str, department: str, departments: Iterable[str]) -> bool:
        """Backend rule 4: a validating post, and (department-scoped) both records in the
        officer's own department."""
        if self.permission(post) is not Permission.VALIDATE:
            return False
        if not self.validation_authority.department_scoped:
            return True
        return all(d == department for d in departments)


def load_governance(path: str | Path) -> tuple[Governance, str]:
    """The governance settings and their version as recorded with every signal and decision:
    the file's own `version` plus a hash of its text, so any change to the file is visible."""
    raw = Path(path).read_text("utf-8")
    data = yaml.safe_load(raw)
    gov = Governance.model_validate(data["relationship_governance"])
    return gov, f"{gov.version}+{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


# ---- records ----
class LinkKey(_Frozen):
    source: str  # the newer order
    kind: str
    target: str  # the older order


class LinkSignal(_Frozen):
    at: dt.datetime
    request_id: str
    user_id: str
    post: str
    department: str
    source: str
    kind: str
    target: str
    code: str  # e.g. useful, not_right (ADR-0074 §3)
    weight: int
    reason: str | None = None
    file_no: str | None = None
    test: bool = False
    automated: bool = False
    config_version: str


class LinkDecision(_Frozen):
    at: dt.datetime
    request_id: str
    user_id: str
    post: str
    department: str
    source: str
    kind: str
    target: str
    action: Literal["validate", "reject", "request_evidence"]
    reason: str
    evidence: str | None = None  # the sentence of the newer order shown and checked
    config_version: str


class LinkStore(Protocol):
    def add_signal(self, s: LinkSignal) -> None: ...

    def add_decision(self, d: LinkDecision) -> None: ...

    def signals(self, keys: Sequence[LinkKey]) -> list[LinkSignal]: ...

    def decisions(self, keys: Sequence[LinkKey]) -> list[LinkDecision]: ...


class InMemoryLinkStore:
    def __init__(self) -> None:
        self._s: list[LinkSignal] = []
        self._d: list[LinkDecision] = []
        self._lock = threading.Lock()

    def add_signal(self, s: LinkSignal) -> None:
        with self._lock:
            self._s.append(s)

    def add_decision(self, d: LinkDecision) -> None:
        with self._lock:
            self._d.append(d)

    def signals(self, keys: Sequence[LinkKey]) -> list[LinkSignal]:
        want = {(k.source, k.kind, k.target) for k in keys}
        with self._lock:
            return [s for s in self._s if (s.source, s.kind, s.target) in want]

    def decisions(self, keys: Sequence[LinkKey]) -> list[LinkDecision]:
        want = {(k.source, k.kind, k.target) for k in keys}
        with self._lock:
            return [d for d in self._d if (d.source, d.kind, d.target) in want]


_S_COLS = tuple(LinkSignal.model_fields)
_D_COLS = tuple(LinkDecision.model_fields)


class PostgresLinkStore:
    """`link_signals` / `link_decisions` (migration 0008): append-only for the API."""

    def __init__(self, pg: Pg) -> None:
        self.pg = pg

    def _add(self, table: str, cols: tuple[str, ...], row: BaseModel) -> None:
        # table and column names are this module's constants; values are bound parameters
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"  # noqa: S608
        with self.pg.tx() as cur:
            cur.execute(sql, tuple(getattr(row, c) for c in cols))

    def add_signal(self, s: LinkSignal) -> None:
        self._add("link_signals", _S_COLS, s)

    def add_decision(self, d: LinkDecision) -> None:
        self._add("link_decisions", _D_COLS, d)

    def _read(
        self, table: str, cols: tuple[str, ...], keys: Sequence[LinkKey]
    ) -> list[tuple[Any, ...]]:
        if not keys:
            return []
        where = " OR ".join(["(source = %s AND kind = %s AND target = %s)"] * len(keys))
        args = [v for k in keys for v in (k.source, k.kind, k.target)]
        with self.pg.tx() as cur:
            sql = f"SELECT {', '.join(cols)} FROM {table} WHERE {where} ORDER BY at"  # noqa: S608
            cur.execute(sql, args)
            return list(cur.fetchall())

    def signals(self, keys: Sequence[LinkKey]) -> list[LinkSignal]:
        rows = self._read("link_signals", _S_COLS, keys)
        return [LinkSignal(**dict(zip(_S_COLS, r, strict=True))) for r in rows]

    def decisions(self, keys: Sequence[LinkKey]) -> list[LinkDecision]:
        rows = self._read("link_decisions", _D_COLS, keys)
        return [LinkDecision(**dict(zip(_D_COLS, r, strict=True))) for r in rows]


# ---- state ----
class LinkState(StrEnum):
    CANDIDATE = "candidate"  # from the collection tools; no wording found
    SUGGESTED = "suggested"  # a sentence of the newer order names the older one
    SUPPORTED_BY_USE = "supported_by_use"  # operational support only, never legal validity
    VALIDATED = "validated"  # stated in the order, or an authenticated officer validated it
    REJECTED = "rejected"  # an authenticated officer rejected it


class LinkStatus(_Frozen):
    state: LinkState
    score: int = 0
    officers: int = 0  # distinct officers whose use supports it
    stated_in_text: bool = False
    contested: bool = False  # "Not right" after it was validated: please review
    evidence_requested: bool = False
    decided_post: str | None = None
    decided_at: dt.datetime | None = None


def _counted(s: LinkSignal, gov: Governance) -> bool:
    u = gov.usage_support
    if u.exclude_test_activity and (s.test or s.user_id in u.test_officers):
        return False
    return not (u.exclude_automated_activity and s.automated)


def link_status(
    *,
    stated_in_text: bool,
    wording_found: bool,
    signals: Sequence[LinkSignal],
    decisions: Sequence[LinkDecision],
    gov: Governance,
) -> LinkStatus:
    """The state of one link from its records (ADR-0074 §5–§6). Per officer per day only the
    strongest positive and the strongest negative signal count, and each officer's total is
    capped, so repeated use by one officer cannot pass for independent adoption."""
    per_day: dict[tuple[str, dt.date], tuple[int, int]] = {}
    for s in signals:
        if not _counted(s, gov):
            continue
        k = (s.user_id, s.at.date())
        pos, neg = per_day.get(k, (0, 0))
        per_day[k] = (max(pos, s.weight), min(neg, s.weight))
    per_officer: dict[str, int] = defaultdict(int)
    for (user, _), (pos, neg) in per_day.items():
        per_officer[user] += pos + neg
    cap = gov.usage_support.max_score_per_officer
    totals = {u: max(-cap, min(cap, v)) for u, v in per_officer.items()}
    score = sum(totals.values())
    officers = sum(1 for v in totals.values() if v > 0)

    final = [d for d in decisions if d.action in ("validate", "reject")]
    last = max(final, key=lambda d: d.at) if final else None
    since = last.at if last else None
    asked = any(
        d.action == "request_evidence" and (since is None or d.at > since) for d in decisions
    )
    common = {
        "score": score,
        "officers": officers,
        "stated_in_text": stated_in_text,
        "evidence_requested": asked,
    }
    if last is not None:
        contested = last.action == "validate" and any(
            s.weight < 0 and s.at > last.at and _counted(s, gov) for s in signals
        )
        state = LinkState.VALIDATED if last.action == "validate" else LinkState.REJECTED
        return LinkStatus(
            state=state, contested=contested, decided_post=last.post, decided_at=last.at, **common
        )
    if stated_in_text:
        return LinkStatus(state=LinkState.VALIDATED, **common)
    u = gov.usage_support
    if u.enabled and score >= u.minimum_score and officers >= u.minimum_distinct_officers:
        return LinkStatus(state=LinkState.SUPPORTED_BY_USE, **common)
    return LinkStatus(state=LinkState.SUGGESTED if wording_found else LinkState.CANDIDATE, **common)


# ---- documentary evidence ----
_CID = re.compile(r"^AP-[A-Z0-9]+-(?P<type>[A-Z]+)-(?P<no>\d+)-(?P<year>\d{4})$")
_REPLACES = re.compile(
    r"supersed|in\s+supersession|cancel|rescind|withdraw|repeal|stands?\s+(?:modified|replaced)|"
    r"in\s+(?:partial\s+)?modification|amend|hereby\s+(?:amended|modified)|in\s+place\s+of",
    re.I,
)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.;])\s+(?=[A-Z(])|\n{2,}", text) if s.strip()]


def names_order(sentence: str, older_id: str) -> bool:
    """The sentence refers to the older order by its number and year (not any digit)."""
    m = _CID.match(older_id)
    if not m:
        return False
    flat = sentence.replace(",", "")
    return bool(
        re.search(rf"(?<![\d/]){int(m['no'])}(?!\d)", flat)
        and m["year"] in flat
        and re.search(r"G\.?\s?O|order|circular|memo|notification", flat, re.I)
    )


_NTH = {
    "1st": 1,
    "first": 1,
    "2nd": 2,
    "second": 2,
    "3rd": 3,
    "third": 3,
    "4th": 4,
    "fourth": 4,
    "5th": 5,
    "fifth": 5,
    "6th": 6,
    "sixth": 6,
}
_READ_ABOVE = re.compile(
    r"\b(1st|2nd|3rd|4th|5th|6th|first|second|third|fourth|fifth|sixth)\s+read\s+above", re.I
)


def _read_list(text: str) -> dict[int, str]:
    """The order's "Read the following:" list, by number (G.O.s cite earlier orders through it:
    "in supersession of the orders issued in the G.O. 1st read above")."""
    m = re.search(
        r"Read(?:\s+the\s+following)?\s*:?\s*\n(?P<body>.*?)(?:\n\s*ORDER\b|\n\s*\n)",
        text,
        re.S | re.I,
    )
    if not m:
        return {}
    return {int(n): line for n, line in re.findall(r"^\s*(\d+)\.\s+(.+)$", m["body"], re.M)}


def _refers(sentence: str, older_id: str, listed: set[int], only_one: bool) -> bool:
    if names_order(sentence, older_id):
        return True
    if any(_NTH[m.group(1).lower()] in listed for m in _READ_ABOVE.finditer(sentence)):
        return True
    return only_one and bool(re.search(r"\bread\s+above\b", sentence, re.I))


def _listed(newer_text: str, older_id: str) -> tuple[set[int], bool]:
    items = _read_list(newer_text)
    listed = {n for n, line in items.items() if names_order(line, older_id)}
    return listed, len(items) == 1 and bool(listed)


def wording(newer_text: str, older_id: str) -> str | None:
    """The newer order's sentence that names the older one, directly or as "the G.O. 1st read
    above", with replacing or amending words."""
    listed, only_one = _listed(newer_text, older_id)
    for s in _sentences(newer_text):
        if _REPLACES.search(s) and _refers(s, older_id, listed, only_one):
            return s[:600]
    return None


def evidence_holds(newer_text: str, older_id: str, quoted: str) -> bool:
    """Rule 4's documentary evidence: the quoted sentence is in the newer order's text (spaces
    aside) and refers to the older order."""
    q = " ".join(quoted.split())
    if len(q) < 20 or q not in " ".join(newer_text.split()):
        return False
    listed, only_one = _listed(newer_text, older_id)
    return _refers(q, older_id, listed, only_one)


# ---- work signals (ADR-0074 §3, step 2) ----
_STILL_IN_FORCE = re.compile(r"\b(?:still|continues?|remains?)\s+in\s+force\b", re.I)
_WRONG_REMARK = re.compile(r"\b(?:wrong|incorrect|not\s+applicable|invalid|superseded)\b", re.I)

WorkEventKind = Literal[
    "note_written",
    "note_confirmed",
    "draft_approved",
    "draft_returned",
    "presend",
    "flag_feedback",
    "file_created",
    "receipt_added",
]


def _cites(text: str, cid: str) -> bool:
    """Whether `text` names `cid` either by canonical ID or by G.O./order number and year."""
    if not text:
        return False
    return cid in text or names_order(text, cid)


def work_signals(
    *,
    links: Sequence[LinkKey],
    event_kind: WorkEventKind,
    text: str,
    earlier_text: str = "",
    initial_text: str = "",
    remarks: str = "",
    prior_flagged_older: Sequence[str] = (),
    flag_action: Literal["accept", "dismiss"] | None = None,
    flag_older_id: str | None = None,
) -> list[tuple[LinkKey, str, str | None]]:
    """Derive W1–W7 and C1–C4 work signals over visible links (ADR-0074 §3).

    Callers must pass only links whose both ends the acting officer may open (rule 1).
    Returns `(link, code, reason)` tuples; never sets or alters legal validity.
    """
    out: list[tuple[LinkKey, str, str | None]] = []
    flagged = set(prior_flagged_older)

    if event_kind == "flag_feedback":
        if flag_older_id and flag_action in ("accept", "dismiss"):
            code = "flag_accepted" if flag_action == "accept" else "flag_dismissed"
            reason = None if flag_action == "accept" else "not a conflict"
            for lk in links:
                if lk.target == flag_older_id:
                    out.append((lk, code, reason))
        return out

    if event_kind == "presend":
        for lk in links:
            if lk.target in flagged and _cites(text, lk.source) and not _cites(text, lk.target):
                out.append((lk, "presend_fixed", None))
        return out

    if event_kind == "draft_approved":
        for lk in links:
            if _cites(text, lk.source):
                out.append((lk, "draft_approved", None))
        return out

    if event_kind == "draft_returned":
        if not remarks.strip():
            return out
        for lk in links:
            if (
                _cites(remarks, lk.source)
                or _cites(remarks, lk.target)
                or (_WRONG_REMARK.search(remarks) and _cites(text, lk.source))
            ):
                out.append((lk, "draft_returned_wrong", remarks.strip()[:200]))
        return out

    # note_written (write_note / send_file) and note_confirmed
    if event_kind == "note_written" and _STILL_IN_FORCE.search(remarks):
        for lk in links:
            if _cites(text, lk.target) or _cites(remarks, lk.target):
                out.append((lk, "presend_still_in_force", remarks.strip()[:200]))

    sentences = _sentences(text)
    for lk in links:
        if event_kind == "note_confirmed" and initial_text and _cites(initial_text, lk.source):
            if _cites(text, lk.source):
                out.append((lk, "draft_kept", None))
            else:
                out.append((lk, "draft_removed", None))

        for s in sentences:
            if _REPLACES.search(s) and (lk.target in s or names_order(s, lk.target)):
                out.append((lk, "note_states_supersession", None))
                break
            if _STILL_IN_FORCE.search(s) and _cites(s, lk.target):
                out.append((lk, "note_states_in_force", None))
                break

        cites_new = _cites(text, lk.source)
        cites_old = _cites(text, lk.target)
        if (
            cites_new
            and not cites_old
            and (_cites(earlier_text, lk.target) or lk.target in flagged)
        ):
            out.append((lk, "note_cites_newer", None))
        elif cites_old and not cites_new:
            out.append((lk, "note_cites_older", None))

    return out


# ---- nightly roll-up, audit & cache invalidation (ADR-0074 §7, step 3) ----


class _AuditSink(Protocol):
    def record(
        self,
        request_id: str,
        user_id: str,
        action: str,
        outcome: str,
        ids: tuple[str, ...] = (),
        detail: str = "",
    ) -> Any: ...


class _DocCache(Protocol):
    def invalidate_documents(self, canonical_ids: frozenset[str]) -> int: ...


class RollupResult(_Frozen):
    checked: int
    updated: int
    state_changes: int
    invalidated_entries: int
    changed_edges: tuple[LinkKey, ...] = ()


def rollup_links(
    *,
    graph: GraphRepository,
    link_store: LinkStore,
    texts: Mapping[str, str],
    gov: Governance,
    gov_version: str,
    audit: _AuditSink | None = None,
    caches: Sequence[_DocCache] = (),
    request_id: str = "rollup",
) -> RollupResult:
    """Recompute state, score and evidence on every candidate/learning graph edge (ADR-0074 §7).

    Writes updated attributes back to `graph`, audits every state transition with the signals and
    decisions that caused it, and invalidates cached answers touching any changed link.
    """
    edges = [e for e in graph.edges() if e.kind.value in LINK_KINDS]
    keys = [LinkKey(source=e.source, kind=e.kind.value, target=e.target) for e in edges]
    sig_map: dict[tuple[str, str, str], list[LinkSignal]] = defaultdict(list)
    for s in link_store.signals(keys):
        sig_map[(s.source, s.kind, s.target)].append(s)
    dec_map: dict[tuple[str, str, str], list[LinkDecision]] = defaultdict(list)
    for d in link_store.decisions(keys):
        dec_map[(d.source, d.kind, d.target)].append(d)

    updated = 0
    state_changes = 0
    changed_edges: list[LinkKey] = []
    changed_docs: set[str] = set()

    for e in edges:
        key = (e.source, e.kind.value, e.target)
        sigs = sig_map.get(key, [])
        decs = dec_map.get(key, [])
        said = wording(texts.get(e.source, ""), e.target)
        val_dec = next((d for d in reversed(decs) if d.action == "validate"), None)
        stated_in_text = bool(
            e.confirmed and val_dec is None and e.state in (None, LinkState.VALIDATED.value)
        )
        st = link_status(
            stated_in_text=stated_in_text,
            wording_found=said is not None,
            signals=sigs,
            decisions=decs,
            gov=gov,
        )
        new_confirmed = st.state is LinkState.VALIDATED
        new_evidence = (val_dec.evidence if val_dec else None) or said or e.evidence
        if (e.confirmed, e.state, e.score, e.evidence) == (
            new_confirmed,
            st.state.value,
            st.score,
            new_evidence,
        ):
            continue
        graph.upsert_edge(
            GraphEdge(
                source=e.source,
                kind=e.kind,
                target=e.target,
                confirmed=new_confirmed,
                state=st.state.value,
                score=st.score,
                evidence=new_evidence,
            )
        )
        updated += 1
        if e.state != st.state.value:
            state_changes += 1
            changed_edges.append(LinkKey(source=e.source, kind=e.kind.value, target=e.target))
            changed_docs.update((e.source, e.target))
            if audit is not None:
                audit.record(
                    request_id,
                    "system.rollup",
                    "graph.link.state_change",
                    st.state.value,
                    ids=(e.source, e.kind.value, e.target, gov_version),
                    detail=(
                        f"{e.state or 'none'}->{st.state.value} "
                        f"score={st.score} signals={len(sigs)} decisions={len(decs)}"
                    ),
                )

    invalidated = 0
    if changed_docs:
        doc_set = frozenset(changed_docs)
        for cache in caches:
            invalidated += cache.invalidate_documents(doc_set)

    return RollupResult(
        checked=len(edges),
        updated=updated,
        state_changes=state_changes,
        invalidated_entries=invalidated,
        changed_edges=tuple(changed_edges),
    )


# ---- File CITES order, File RELATED TO file, Order APPLIES TO section (ADR-0074 §3.3, §4) ----

FILE_NODE_PREFIX = "FILE:"
SECTION_NODE_PREFIX = "SECTION:"


def file_node_id(file_no: str) -> str:
    """Canonical graph node ID for a file (never collides with document IDs)."""
    return f"{FILE_NODE_PREFIX}{file_no}"


def section_node_id(department: str, section: str) -> str:
    """Canonical graph node ID for a dealing section."""
    return f"{SECTION_NODE_PREFIX}{department}:{section}"


class FileLinkSource(_Frozen):
    """Summary of one file's records used to derive File/Order/Section graph links."""

    file_no: str
    tags: DocumentAccessTags
    texts: tuple[str, ...] = ()
    cited_orders: tuple[str, ...] = ()
    linked_files: tuple[str, ...] = ()


class FileGraphSyncResult(_Frozen):
    file_cites_order: int
    file_related_to_file: int
    order_applies_to_section: int


def build_file_and_section_links(
    graph: GraphRepository,
    files: Sequence[FileLinkSource],
    *,
    order_ids: Iterable[str] = (),
) -> FileGraphSyncResult:
    """Derive File CITES order, File RELATED TO file, and Order APPLIES TO section edges (§4).

    Every `FILE:` and `SECTION:` node carries access tags so `GraphRepository.walk` enforces the
    officer's scope at every step.
    """
    orders = tuple(dict.fromkeys(order_ids))
    known_files = {f.file_no: f for f in files}
    file_cites: dict[str, set[str]] = defaultdict(set)
    order_to_files: dict[str, set[str]] = defaultdict(set)

    cites_count = 0
    related_count = 0
    applies_count = 0

    for f in files:
        fn_id = file_node_id(f.file_no)
        graph.upsert_node(
            GraphNode(canonical_id=fn_id, tags=f.tags.model_copy(update={"doc_id": fn_id}))
        )
        cited = set(f.cited_orders)
        if orders and f.texts:
            joined = "\n".join(t for t in f.texts if t)
            for oid in orders:
                if _cites(joined, oid):
                    cited.add(oid)
        for oid in sorted(cited):
            if graph.node(oid) is None:
                continue
            file_cites[f.file_no].add(oid)
            order_to_files[oid].add(f.file_no)
            graph.upsert_edge(
                GraphEdge(
                    source=fn_id,
                    kind=EdgeKind.CITES,
                    target=oid,
                    confirmed=True,
                    state=LinkState.VALIDATED.value,
                )
            )
            cites_count += 1

    seen_related: set[tuple[str, str]] = set()
    for f in files:
        fn_id = file_node_id(f.file_no)
        for other in f.linked_files:
            if other == f.file_no or other not in known_files:
                continue
            pair = (f.file_no, other)
            if pair not in seen_related:
                seen_related.add(pair)
                graph.upsert_edge(
                    GraphEdge(
                        source=fn_id,
                        kind=EdgeKind.RELATED_TO,
                        target=file_node_id(other),
                        confirmed=True,
                        state=LinkState.VALIDATED.value,
                    )
                )
                related_count += 1

    for sharing_files in order_to_files.values():
        ordered = sorted(sharing_files)
        for i, f_a in enumerate(ordered):
            for f_b in ordered[i + 1 :]:
                pair = (f_a, f_b)
                if pair not in seen_related:
                    seen_related.add(pair)
                    graph.upsert_edge(
                        GraphEdge(
                            source=file_node_id(f_a),
                            kind=EdgeKind.RELATED_TO,
                            target=file_node_id(f_b),
                            confirmed=True,
                            state=LinkState.VALIDATED.value,
                        )
                    )
                    related_count += 1

    seen_applies: set[tuple[str, str]] = set()
    for oid, f_nos in order_to_files.items():
        for f_no in sorted(f_nos):
            f = known_files[f_no]
            if not f.tags.section:
                continue
            sec_id = section_node_id(f.tags.department, f.tags.section)
            if (oid, sec_id) in seen_applies:
                continue
            seen_applies.add((oid, sec_id))
            graph.upsert_node(
                GraphNode(
                    canonical_id=sec_id,
                    tags=DocumentAccessTags(
                        doc_id=sec_id,
                        department=f.tags.department,
                        section=f.tags.section,
                        classification=f.tags.classification,
                    ),
                )
            )
            graph.upsert_edge(
                GraphEdge(
                    source=oid,
                    kind=EdgeKind.APPLIES_TO,
                    target=sec_id,
                    confirmed=True,
                    state=LinkState.VALIDATED.value,
                )
            )
            applies_count += 1

    return FileGraphSyncResult(
        file_cites_order=cites_count,
        file_related_to_file=related_count,
        order_applies_to_section=applies_count,
    )


def files_following_order(graph: GraphRepository, order_id: str, scope: Scope) -> list[str]:
    """Return file numbers whose records cite `order_id`, constrained by `scope` (ADR-0074 §4)."""
    hits = graph.walk(
        [order_id],
        scope,
        kinds=frozenset({EdgeKind.CITES}),
        direction=Direction.IN,
        max_hops=1,
        max_nodes=50,
    )
    return sorted(
        h.canonical_id[len(FILE_NODE_PREFIX) :]
        for h in hits
        if h.canonical_id.startswith(FILE_NODE_PREFIX)
    )


def linking_signals(
    *,
    links: Sequence[LinkKey],
    action: Literal["add_reference", "link_files", "receipt_added"],
    primary_orders: Sequence[str],
    other_orders: Sequence[str] = (),
    receipt_text: str = "",
) -> list[tuple[LinkKey, str, str | None]]:
    """Derive L1–L3 signals over visible links (ADR-0074 §3.3, §5 rule 1)."""
    primary = set(primary_orders)
    other = set(other_orders)
    out: list[tuple[LinkKey, str, str | None]] = []

    if action == "add_reference":
        for lk in links:
            if lk.source in primary and (not other or lk.target in other):
                out.append((lk, "file_adds_reference", None))
        return out

    if action == "link_files":
        for lk in links:
            if (lk.source in primary and lk.target in other) or (
                lk.target in primary and lk.source in other
            ):
                out.append((lk, "files_linked", None))
        return out

    # receipt_added (L3): letter cites newer order in place of older order on the file
    for lk in links:
        if (
            _cites(receipt_text, lk.source)
            and not _cites(receipt_text, lk.target)
            and (not other or lk.target in other)
        ):
            out.append((lk, "receipt_cites_newer", None))
    return out


# ---- monitoring pad: links that changed state this week, with evidence (ADR-0074 §9 step 5) ----


class LinkChangeSummary(_Frozen):
    """One link state transition for the monitoring pad, with its documentary evidence."""

    ts: dt.datetime
    source: str
    kind: str
    target: str
    from_state: str | None = None
    to_state: str
    score: int = 0
    evidence: str | None = None
    detail: str = ""
    gov_version: str = ""


_CHANGE_RE = re.compile(r"^([^\s>-]+)->([^\s]+)(?:\s+score=(-?\d+))?")


def recent_link_changes(
    events: Sequence[Any],
    graph: GraphRepository,
    *,
    since: dt.datetime,
    visible: Callable[[str], bool],
) -> list[LinkChangeSummary]:
    """Return `graph.link.state_change` events from `since` onward whose ends pass `visible`."""
    edge_map = {(e.source, e.kind.value, e.target): e for e in graph.edges()}
    out: list[LinkChangeSummary] = []
    for ev in events:
        if getattr(ev, "action", None) != "graph.link.state_change":
            continue
        at = getattr(ev, "at", None)
        if at is None or at < since:
            continue
        ids = tuple(getattr(ev, "ids", ()))
        if len(ids) < 3:
            continue
        src, kind, tgt = ids[0], ids[1], ids[2]
        if not (visible(src) and visible(tgt)):
            continue
        gov_version = ids[3] if len(ids) > 3 else ""
        detail = getattr(ev, "detail", "") or ""
        m = _CHANGE_RE.match(detail)
        from_state = None if not m or m.group(1) == "none" else m.group(1)
        to_state = m.group(2) if m else getattr(ev, "outcome", "")
        score = int(m.group(3)) if m and m.group(3) is not None else 0
        edge = edge_map.get((src, kind, tgt))
        out.append(
            LinkChangeSummary(
                ts=at,
                source=src,
                kind=kind,
                target=tgt,
                from_state=from_state,
                to_state=to_state,
                score=score,
                evidence=edge.evidence if edge is not None else None,
                detail=detail,
                gov_version=gov_version,
            )
        )
    out.sort(key=lambda r: r.ts, reverse=True)
    return out
