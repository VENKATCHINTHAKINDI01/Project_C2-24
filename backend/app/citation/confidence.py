"""How far each statement of an answer can be relied on (Tier 2 "structured-output confidence
scoring"; ADR-0054).

Six factors, each a fact the system already holds — never the model's own confidence:

- retrieval: how the cited record was found (exact reference … graph), or from the records;
- authority: the cited instrument's level (Act / Rules / G.O. … Noting = precedent);
- support: the quoted words were found in the cited text (or only "review needed", OCR text);
- validity: the cited order is in force on the as-of date — or the statement says it is not;
- consistency: no later order in the officer's records amends / supersedes it uncited;
- graph: the relations store answered, so supersession was actually checked.

The WEAKEST factor sets the band: a confident sentence resting on an outdated order is Low,
however good its retrieval. Each factor carries a plain reason the officer can read. Values are
MOCK (`backend/config/confidence.yaml`) until the owner / department confirm them.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from app.temporal.engine import Instrument, RelationKind, Status, TemporalRelation, status_as_of


class Band(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Factor(_Frozen):
    name: str  # retrieval | authority | support | validity | consistency | graph
    value: float
    reason: str


class Confidence(_Frozen):
    band: Band
    score: float  # the weakest factor
    factors: tuple[Factor, ...]

    @property
    def weakest(self) -> Factor:
        return min(self.factors, key=lambda f: f.value)


class ConfidenceConfig(_Frozen):
    version: str
    status: str
    bands: dict[str, float]
    retrieval: dict[str, float]
    authority: list[dict[str, float]]
    support: dict[str, float]
    validity: dict[str, float]
    consistency: dict[str, float]
    graph: dict[str, float]

    def authority_of(self, level: int) -> float:
        return next(
            (a["value"] for a in self.authority if level <= a["max_level"]),
            self.authority[-1]["value"],
        )


def load_confidence_config(path: Path) -> ConfidenceConfig:
    with path.open(encoding="utf-8") as fh:
        return ConfidenceConfig.model_validate(yaml.safe_load(fh))


@lru_cache
def default_confidence_config() -> ConfidenceConfig:
    return load_confidence_config(
        Path(__file__).resolve().parents[2] / "config" / "confidence.yaml"
    )


_SAYS_STATUS = re.compile(
    r"\b(supersed\w*|repeal\w*|rescind\w*|withdraw\w*|cancel\w*|expired?|lapsed|replaced|"
    r"no longer|not (?:yet )?in force|ceased|takes effect)\b",
    re.I,
)
_CHANGES = (RelationKind.SUPERSEDES, RelationKind.REPEALS, RelationKind.AMENDS)
_LEVEL_NAME = {
    1: "the Constitution", 2: "an Act", 3: "statutory Rules", 4: "a G.O.(Ms)", 5: "a G.O.(Rt)",
    6: "a Standing Order", 7: "Proceedings", 8: "a Circular / Memo", 9: "an Office Order",
    10: "a decision / noting (precedent, not an authority)",
}  # fmt: skip


class Cited(_Frozen):
    """What is known about one cited record (all already authorised for this officer)."""

    canonical_id: str
    rung: str | None  # L0 … L3, None when stated from the records
    hierarchy_level: int | None
    ocr: bool = False
    incomplete: bool = False


def assess(
    text: str,
    cited: Sequence[Cited],
    *,
    verified: bool,
    from_records: bool,
    as_of: dt.date,
    instruments: Mapping[str, Instrument],
    relations: Sequence[TemporalRelation],
    may_see: Callable[[str], bool],
    graph_down: bool,
    cfg: ConfidenceConfig,
) -> Confidence:
    """One statement's confidence. `instruments` / `relations` are the officer's visible facts;
    `may_see` decides whether a later amending order is one the officer may open."""
    f: list[Factor] = []
    ids = {c.canonical_id for c in cited}

    # retrieval
    if from_records or not cited:
        f.append(
            Factor(name="retrieval", value=cfg.retrieval["records"], reason="From the records")
        )
    else:
        best = max(cited, key=lambda c: cfg.retrieval.get(c.rung or "", 0.0))
        how = {
            "L0": "found by its exact reference",
            "L1": "found by its recorded details",
            "L2": "found by search",
            "L3": "reached through related orders",
        }.get(best.rung or "", "found")
        f.append(
            Factor(
                name="retrieval",
                value=cfg.retrieval.get(best.rung or "", 0.7),
                reason=how.capitalize(),
            )
        )

    # authority
    levels = [c.hierarchy_level for c in cited if c.hierarchy_level is not None]
    if levels:
        top = min(levels)
        f.append(
            Factor(
                name="authority",
                value=cfg.authority_of(top),
                reason=f"Rests on {_LEVEL_NAME.get(top, f'level {top}')}",
            )
        )

    # support
    if from_records:
        f.append(
            Factor(name="support", value=cfg.support["records"], reason="Stated from the records")
        )
    elif not verified:
        f.append(
            Factor(
                name="support",
                value=cfg.support["review"],
                reason="Not confirmed against the cited text",
            )
        )
    elif any(c.ocr for c in cited):
        f.append(
            Factor(name="support", value=cfg.support["ocr"], reason="Quoted from text read by OCR")
        )
    elif any(c.incomplete for c in cited):
        f.append(
            Factor(
                name="support",
                value=cfg.support["incomplete"],
                reason="Quoted from an incomplete passage",
            )
        )
    else:
        f.append(
            Factor(
                name="support",
                value=cfg.support["verified"],
                reason="Quoted words found in the source",
            )
        )

    # validity
    statuses = {
        cid: status_as_of(cid, as_of, instruments, list(relations))
        for cid in ids
        if cid in instruments
    }
    says = bool(_SAYS_STATUS.search(text))
    off = [cid for cid, st in statuses.items() if st.status is not Status.IN_FORCE]
    if not statuses:
        pass  # not an order (a note, a letter): validity does not apply
    elif all(st.status is Status.UNKNOWN for st in statuses.values()):
        f.append(
            Factor(
                name="validity", value=cfg.validity["unknown"], reason="Effective date not recorded"
            )
        )
    elif off and len(off) == len(statuses) and not says:
        st = statuses[off[0]]
        f.append(
            Factor(
                name="validity",
                value=cfg.validity["outdated"],
                reason=f"Cited order is {st.status.value.replace('_', ' ')} on {as_of:%d-%m-%Y}",
            )
        )
    elif off and says:
        f.append(
            Factor(name="validity", value=cfg.validity["stated"], reason="Its status is stated")
        )
    else:
        f.append(
            Factor(name="validity", value=cfg.validity["in_force"], reason="Cited order in force")
        )

    # consistency: a later order the officer may open changes a cited one, and is not cited
    later = sorted(
        {
            r.source
            for r in relations
            if r.kind in _CHANGES
            and r.target in ids
            and r.source not in ids
            and (src := instruments.get(r.source)) is not None
            and src.effective_from is not None
            and src.effective_from <= as_of
            and may_see(r.source)
        }
    )
    if later and not says:
        f.append(
            Factor(
                name="consistency",
                value=cfg.consistency["later_change"],
                reason=f"A later order in your records changes it ({later[0]})",
            )
        )
    elif ids & set(instruments):
        f.append(
            Factor(
                name="consistency", value=cfg.consistency["clear"], reason="No later change found"
            )
        )

    # graph
    if graph_down:
        f.append(
            Factor(
                name="graph",
                value=cfg.graph["unavailable"],
                reason="Supersession not checked just now",
            )
        )
    elif ids & set(instruments):
        f.append(Factor(name="graph", value=cfg.graph["checked"], reason="Supersession checked"))

    score = min(x.value for x in f)
    band = (
        Band.HIGH
        if score >= cfg.bands["high"]
        else Band.MEDIUM
        if score >= cfg.bands["medium"]
        else Band.LOW
    )
    return Confidence(band=band, score=round(score, 3), factors=tuple(f))


def overall(confidences: Sequence[Confidence]) -> Confidence | None:
    """The answer's confidence: its weakest statement (None when nothing is stated)."""
    return min(confidences, key=lambda c: c.score) if confidences else None


def as_json(c: Confidence | None) -> dict[str, Any] | None:
    return c.model_dump(mode="json") if c else None
