"""Collision registry: section-code / registry suffixes, stability, ambiguous lookup (ADR-0007).

The order numbers are illustrative; no real record is asserted to collide.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from app.identifiers.canonical import parse_canonical_id
from app.identifiers.collisions import (
    CollisionError,
    CollisionRegistry,
    Evidence,
    LookupStatus,
    SuffixKind,
    normalise_section_code,
)

BASE = "AP-FIN01-GOMS-126-2023"
T0 = dt.datetime(2026, 11, 3, tzinfo=dt.UTC)
EV = Evidence(method="heading_ocr", page=1, text="FINANCE (HR.III) DEPARTMENT")


@pytest.mark.parametrize(
    ("label", "code"),
    [
        ("HR.III", "HRIII"),
        ("(HR-III)", "HRIII"),
        ("H.R. III", "HRIII"),
        ("hr.iii", "HRIII"),
        ("W&P", "WP"),
        ("", None),
        (None, None),
        ("3", None),  # no letter
        ("C01", None),  # looks like a registry suffix
        ("R1", None),  # looks like a revision
        ("X", None),  # too short
        ("A" * 13, None),  # too long
    ],
)
def test_normalise_section_code(label: str | None, code: str | None) -> None:
    assert normalise_section_code(label) == code


def test_first_record_keeps_bare_id_and_second_gets_section_suffix() -> None:
    reg = CollisionRegistry(clock=T0)
    first = reg.assign(BASE, "goir:gid=1", section_label="HR.I")
    second = reg.assign(BASE, "goir:gid=2", section_label="HR.III", evidence=EV)
    assert first.canonical_id == BASE and first.suffix_kind is SuffixKind.NONE
    assert second.canonical_id == "AP-FIN01-GOMS-126-2023-HRIII"
    assert second.suffix_kind is SuffixKind.SECTION and second.evidence == EV
    assert parse_canonical_id(second.canonical_id).suffix == "HRIII"  # fits the existing format


def test_registry_suffix_when_no_section_code_or_it_does_not_distinguish() -> None:
    reg = CollisionRegistry(clock=T0)
    reg.assign(BASE, "s1", section_label="HR.III")
    same = reg.assign(BASE, "s2", section_label="HR-III")  # same code as the existing record
    none = reg.assign(BASE, "s3")  # no reliable code
    assert same.canonical_id == f"{BASE}-C01" and same.suffix_kind is SuffixKind.REGISTRY
    assert none.canonical_id == f"{BASE}-C02"


def test_assignment_is_tied_to_source_identity_and_never_reassigned() -> None:
    reg = CollisionRegistry(clock=T0)
    reg.assign(BASE, "s1")
    a = reg.assign(BASE, "s2")
    assert reg.assign(BASE, "s2", section_label="HR.III") == a  # idempotent, not upgraded
    with pytest.raises(CollisionError):
        reg.assign("AP-FIN01-GOMS-127-2023", "s2")  # same source, different base → review


def test_discovery_order_does_not_change_existing_ids(tmp_path: Path) -> None:
    """Suffixes come from the registry, not from collection or issue order."""
    path = tmp_path / "collisions.json"
    reg = CollisionRegistry(path, clock=T0)
    a = reg.assign(BASE, "s-late-issued")
    b = reg.assign(BASE, "s-early-issued")
    reloaded = CollisionRegistry(path)
    c = reloaded.assign(BASE, "s-third")
    assert reloaded.by_source("s-late-issued") == a
    assert reloaded.by_source("s-early-issued") == b
    assert (a.canonical_id, b.canonical_id, c.canonical_id) == (BASE, f"{BASE}-C01", f"{BASE}-C02")


def test_bare_base_lookup_is_ambiguous_but_exact_ids_resolve() -> None:
    reg = CollisionRegistry(clock=T0)
    assert reg.lookup(BASE).status is LookupStatus.NOT_FOUND
    reg.assign(BASE, "s1")
    assert reg.lookup(BASE).status is LookupStatus.FOUND  # no collision yet
    reg.assign(BASE, "s2", section_label="HR.III")
    amb = reg.lookup(BASE)
    assert amb.status is LookupStatus.AMBIGUOUS and amb.canonical_id is None
    assert amb.candidates == (BASE, f"{BASE}-HRIII")
    hit = reg.lookup(f"{BASE}-HRIII")
    assert hit.status is LookupStatus.FOUND and hit.canonical_id == f"{BASE}-HRIII"
    assert reg.by_source("s1") is not None and reg.by_source("s1").canonical_id == BASE  # type: ignore[union-attr]


def test_group_records_relationship_and_evidence() -> None:
    reg = CollisionRegistry(clock=T0)
    reg.assign(BASE, "s1", section_label="HR.I", evidence=EV)
    reg.assign(BASE, "s2")
    group = reg.group(BASE)
    assert [g.base_id for g in group] == [BASE, BASE]
    assert group[0].section_code == "HRI"  # kept even though the first record is unsuffixed


def test_persisted_file_is_complete_and_atomic(tmp_path: Path) -> None:
    path = tmp_path / "reg" / "collisions.json"
    reg = CollisionRegistry(path, clock=T0)
    reg.assign(BASE, "s1")
    reg.assign(BASE, "s2", section_label="HR.III", evidence=EV)
    reg.assign(BASE, "s3")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["counters"] == {BASE: 1}
    assert [a["canonical_id"] for a in data["assignments"]] == [
        BASE,
        f"{BASE}-HRIII",
        f"{BASE}-C01",
    ]
    assert not list(path.parent.glob(".collisions-*"))  # no temp files left behind


def test_tampered_registry_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "collisions.json"
    reg = CollisionRegistry(path, clock=T0)
    reg.assign(BASE, "s1")
    reg.assign(BASE, "s2")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["counters"][BASE] = 0  # would let C01 be handed out twice
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CollisionError):
        CollisionRegistry(path)
    data["counters"][BASE] = 1
    data["assignments"].append(dict(data["assignments"][1]))  # duplicate source / ID
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(CollisionError):
        CollisionRegistry(path)


@pytest.mark.parametrize(
    "base",
    [
        "AP-FIN01-MEMO-FIN01HRPLG0TRF-3-2025-2",  # suffix slot used by the e-File suffix
        "AP-USD01-NOTE-USD0131-4-2025-R1",  # suffix slot used by a revision
    ],
)
def test_ids_already_using_the_suffix_slot_go_to_review_on_collision(base: str) -> None:
    reg = CollisionRegistry(clock=T0)
    reg.assign(base, "s1")
    with pytest.raises(CollisionError):
        reg.assign(base, "s2", section_label="HR.III")


def test_dated_memo_collision_keeps_date_tag_after_suffix() -> None:
    base = "AP-FIN01-CIRMEMO-FIN01COOROMISC-93-2023-D20240305"
    reg = CollisionRegistry(clock=T0)
    reg.assign(base, "s1")
    a = reg.assign(base, "s2")
    assert a.canonical_id == "AP-FIN01-CIRMEMO-FIN01COOROMISC-93-2023-C01-D20240305"
    assert parse_canonical_id(a.canonical_id).date_tag == "20240305"


@pytest.mark.parametrize("bad", ["", "not-an-id", "AP-FIN01-GOMS-126-2023#para-1"])
def test_invalid_inputs_are_refused(bad: str) -> None:
    reg = CollisionRegistry(clock=T0)
    with pytest.raises(CollisionError):
        reg.assign(bad or BASE, bad)
