"""Richer graph reasoning (Tier 2; ADR-0056): how an order changed over time, and how records of
other departments link to it — deterministic, from visible facts only (plan §3.2 L3, §6.1, §12.3;
CLAUDE.md §4.6-§4.7, §6.1)."""

from __future__ import annotations

import csv
import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.agents.graph_facts import CROSS_Q, HISTORY_Q
from app.agents.tools import STATUS_UNCONFIRMED
from app.config import get_settings
from app.main import create_app
from app.temporal.engine import Instrument, RelationKind, TemporalRelation
from app.temporal.history import Change, history, lineage

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "data" / "synthetic" / "mock_v1"
D = dt.date


def _inst(cid: str, on: dt.date | None, level: int = 4) -> Instrument:
    return Instrument(canonical_id=cid, hierarchy_level=level, effective_from=on)


def _rel(src: str, kind: RelationKind, dst: str, confirmed: bool = True) -> TemporalRelation:
    return TemporalRelation(source=src, kind=kind, target=dst, confirmed=confirmed)


S, A, C, X = (
    RelationKind.SUPERSEDES,
    RelationKind.AMENDS,
    RelationKind.CLARIFIES,
    RelationKind.REPEALS,
)
INST = {
    "G19": _inst("G19", D(2019, 6, 14)),
    "A19": _inst("A19", D(2019, 6, 28)),
    "G22": _inst("G22", D(2022, 6, 3)),
    "G25": _inst("G25", D(2025, 5, 12)),
    "M25": _inst("M25", D(2025, 5, 21), level=5),
    "OTHER": _inst("OTHER", D(2020, 1, 1)),
}
RELS = [
    _rel("A19", A, "G19"),
    _rel("G22", S, "G19"),
    _rel("G22", S, "A19"),
    _rel("G25", S, "G22"),
    _rel("M25", C, "G25"),
]


# ---- the pure history -------------------------------------------------------------------------


def test_a_lineage_is_told_in_date_order_with_what_is_in_force() -> None:
    h = history("G25", D(2026, 11, 18), INST, RELS)
    assert [(e.canonical_id, e.change, e.targets) for e in h.events] == [
        ("G19", Change.ISSUED, ()),
        ("A19", Change.AMENDED, ("G19",)),
        ("G22", Change.SUPERSEDED, ("A19", "G19")),
        ("G25", Change.SUPERSEDED, ("G22",)),
        ("M25", Change.CLARIFIED, ("G25",)),
    ]
    assert h.in_force == ("G25", "M25")
    assert "OTHER" not in h.lineage  # not joined to the order by any link
    assert history("G19", D(2026, 11, 18), INST, RELS).events == h.events  # any member: same story


def test_an_as_of_question_sees_the_past_as_it_was() -> None:
    h = history("G25", D(2021, 1, 1), INST, RELS)
    assert [e.canonical_id for e in h.events] == ["G19", "A19"]
    assert h.in_force == ("G19", "A19")
    assert set(h.lineage) == {"G19", "A19", "G22", "G25", "M25"}  # later orders: not yet told


def test_an_unconfirmed_link_is_for_review_and_never_changes_the_story() -> None:
    inst = INST | {"G26": _inst("G26", D(2026, 1, 1))}
    h = history("G25", D(2026, 11, 18), inst, [*RELS, _rel("G26", X, "G25", confirmed=False)])
    assert "G26" not in h.members and h.in_force == ("G25", "M25")
    assert h.pending_review == (("G26", "REPEALS", "G25"),)


def test_an_undated_member_is_never_placed_by_guess() -> None:
    inst = INST | {"M2X": _inst("M2X", None)}
    h = history("G25", D(2026, 11, 18), inst, [*RELS, _rel("M2X", C, "G25")])
    assert h.undated == ("M2X",) and "M2X" not in h.members


def test_a_record_the_officer_may_not_see_never_joins_two_parts_of_a_lineage() -> None:
    """Callers pass only visible facts: without G22, the 2019 and 2025 orders are unrelated."""
    visible = {k: v for k, v in INST.items() if k != "G22"}
    h = history("G25", D(2026, 11, 18), visible, RELS)
    assert set(h.lineage) == {"G25", "M25"}
    assert not any("G22" in (e.canonical_id, *e.targets) for e in h.events)


def test_a_very_long_lineage_is_cut_nearest_first() -> None:
    rels = [_rel(f"O{i + 1}", S, f"O{i}") for i in range(60)]
    members, cut = lineage("O30", rels, limit=10)
    assert cut and len(members) == 10 and members[0] == "O30"
    assert set(members) <= {f"O{i}" for i in range(25, 36)}


@pytest.mark.parametrize(
    ("q", "history_q", "cross_q"),
    [
        ("How have the transfer guidelines changed over the years?", True, False),
        ("What amendments were made to G.O.Ms.No.62/2019?", True, False),
        ("Which other departments refer to G.O.Ms.No.19/2018?", False, True),
        ("Is any department relying on this circular?", False, True),
        ("Has a spouse-ground transfer request been decided before?", False, False),
        ("Is Circular Memo No.USD01-WRKS0/9/2023 still valid?", False, False),
        ("Summarise the vigilance matters in the Department.", False, False),
    ],
)
def test_graph_questions_are_recognised_by_fixed_rules(
    q: str, history_q: bool, cross_q: bool
) -> None:
    assert bool(HISTORY_Q.search(q)) is history_q
    assert bool(CROSS_Q.search(q)) is cross_q


# ---- through the assistant (sandbox, synthetic set v1) ----------------------------------------


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    from evaluation.ask_golden import confirm_held_scans  # type: ignore[import-not-found]

    app = create_app(get_settings().model_copy(update={"sandbox": True}))
    seed = json.loads((CORPUS / "eoffice" / "seed.json").read_text("utf-8"))
    with TestClient(app) as c:
        confirm_held_scans(c, seed)  # SIMULATED reviewer: the 2019 orders are scans
        yield c


def _ask(c: TestClient, uid: str, q: str) -> dict[str, Any]:
    r = c.post("/assist/ask", json={"question": q}, headers={"X-Sandbox-User": uid})
    assert r.status_code == 200, r.text
    return dict(r.json())


def _facts(out: dict[str, Any], source: str) -> list[dict[str, Any]]:
    return [s for s in out["statements"] if s["source"] == source]


def test_an_order_history_is_dated_cited_and_says_what_is_in_force(client: TestClient) -> None:
    out = _ask(client, "U06", "How has G.O.Ms.No.14/2021 changed over time?")
    facts = _facts(out, "order records")
    assert [f["text"][:10] for f in facts[:2]] == ["18-03-2021", "06-08-2024"]
    assert "superseded G.O.Ms.No.14" in facts[1]["text"]
    assert {c["canonical_id"] for c in facts[1]["citations"]} == {
        "AP-USD01-GOMS-27-2024",
        "AP-USD01-GOMS-14-2021",
    }
    assert facts[-1]["text"].startswith("In force on") and "G.O.Ms.No.27" in facts[-1]["text"]
    assert out["status"] == "answered"  # the records answer it, model or not


def test_the_whole_transfer_series_from_2019_is_told(client: TestClient) -> None:
    out = _ask(client, "U01", "How have the transfer guidelines in G.O.Ms.No.31/2025 changed?")
    told = " ".join(f["text"] for f in _facts(out, "order records"))
    for ref in ("G.O.Ms.No.62", "G.O.Ms.No.71", "G.O.Ms.No.88", "G.O.Ms.No.31", "Memo No.3/2025"):
        assert ref in told
    assert told.index("G.O.Ms.No.88, Finance Department, dated 03-06-2022 superseded") < (
        told.index("G.O.Ms.No.31, Finance Department, dated 12-05-2025 superseded")
    )


def test_what_is_in_force_is_not_said_when_the_status_may_not_be_reported(
    client: TestClient,
) -> None:
    """U01 (Urban Services) may see the Finance orders but not all of Finance: the dated changes
    are shown (each is a visible record), "in force" is not, and the neutral notice is given."""
    out = _ask(client, "U01", "How has G.O.Ms.No.31/2025 changed over the years?")
    facts = _facts(out, "order records")
    assert facts and not any(f["text"].startswith(("In force", "None of")) for f in facts)
    assert any(STATUS_UNCONFIRMED in n for n in out["notices"])


def test_an_order_the_officer_may_not_see_and_one_that_does_not_exist_answer_alike(
    client: TestClient,
) -> None:
    """D11 (Standing Order 2/2020) is DENY for U03 in the independent access matrix."""
    hidden = _ask(client, "U03", "How has Standing Order No.2/2020 changed over time?")
    absent = _ask(client, "U03", "How has Standing Order No.7/2020 changed over time?")
    for out in (hidden, absent):
        assert not [s for s in out["statements"] if s["source"] != "evidence"]
        assert "AP-USD01-SO-2-2020" not in json.dumps(out)
    assert hidden["notices"] == absent["notices"]


def test_an_as_of_history_is_told_once_and_only_up_to_that_day(client: TestClient) -> None:
    out = _ask(client, "U07", "How have the transfer guidelines changed as on 01-01-2021?")
    texts = [f["text"] for f in _facts(out, "order records")]
    assert texts and len(texts) == len(set(texts))
    assert not any("G.O.Ms.No.88" in t or "G.O.Ms.No.31" in t for t in texts)


def test_other_departments_linked_to_an_order_are_named_by_department(client: TestClient) -> None:
    out = _ask(client, "U06", "Which other departments refer to G.O.Ms.No.88/2022?")
    facts = {
        f["text"].split(":")[0]: f
        for f in _facts(out, "link records")
        if ", through " not in f["text"].split(":")[0]  # direct links only
    }
    assert set(facts) == {"General Administration (GAD01)", "Urban Services (USD01)"}
    usd = facts["Urban Services (USD01)"]
    assert {c["canonical_id"] for c in usd["citations"]} >= {
        "AP-USD01-NOTE-USD0112-31-2022",
        "AP-USD01-NOTE-USD0112-77-2023",
    }
    assert "cites G.O.Ms.No.88" in usd["text"]
    assert (
        "G.O.Ms.No.88, Finance Department, dated 03-06-2022 refers to G.O.Ms.No.19"
        in (facts["General Administration (GAD01)"]["text"])
    )


def test_no_links_is_said_plainly(client: TestClient) -> None:
    out = _ask(client, "U03", "Which other departments refer to G.O.Ms.No.14/2021?")
    (fact,) = _facts(out, "link records")
    assert fact["text"].startswith("The link records show no record of another department")


def _doc_of(cid: str, index: list[tuple[str, str]]) -> str | None:
    hits = [(len(c), d) for c, d in index if cid == c or cid.startswith(c + "-")]
    return max(hits)[1] if hits else None


def test_no_officer_is_told_of_a_record_outside_their_access(client: TestClient) -> None:
    """Every officer x every order x both questions: each record named in a history or a link
    statement (text or citation) is ALLOW for that officer in the independent access matrix."""
    with (CORPUS / "documents_index.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    with (CORPUS / "access_matrix.csv").open(encoding="utf-8", newline="") as fh:
        matrix = {r["doc_id"]: r for r in csv.DictReader(fh)}
    index = [(r["canonical_id"], r["id"]) for r in rows]
    orders = [r for r in rows if not r["doc_type"].startswith(("Noting", "Report", "Annexure"))]
    users = [u for u in matrix["D01"] if u.startswith("U")]
    checked = 0
    for uid in users:
        for r in orders:
            ref = r["raw_reference"].split(", Dt.")[0]
            for q in (
                f"How has {ref} changed over time?",
                f"Which other departments refer to {ref}?",
            ):
                out = _ask(client, uid, q)
                for s in out["statements"]:
                    if s["source"] == "evidence":
                        continue
                    for c in s["citations"]:
                        doc = _doc_of(c["canonical_id"], index)
                        assert doc is not None and matrix[doc][uid] == "ALLOW", (uid, q, c)
                        checked += 1
                    for cid, doc in index:
                        if cid in s["text"]:
                            assert matrix[doc][uid] == "ALLOW", (uid, q, cid)
    assert checked > 100  # the sweep really named records


def test_in_force_is_said_only_when_every_member_s_status_may_be_reported(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The coverage rule applies to each order the "in force" sentence names: if the officer may
    not be told the status of one member of the lineage, the sentence is not given at all."""
    import app.agents.graph_facts as gf

    real = gf.status_covered
    monkeypatch.setattr(
        gf,
        "status_covered",
        lambda ctx, d: d.canonical_id != "AP-USD01-GOMS-14-2021" and real(ctx, d),
    )
    out = _ask(client, "U06", "How has G.O.Ms.No.27/2024 changed over time?")
    facts = _facts(out, "order records")
    assert facts and not any(f["text"].startswith(("In force", "None of")) for f in facts)
    assert any(STATUS_UNCONFIRMED in n for n in out["notices"])


def test_a_two_link_chain_reaching_a_third_department_is_told_through_its_stepping_stone(
    client: TestClient,
) -> None:
    """GAD G.O.Ms.19/2018 ← Finance G.O.Ms.88/2022 ← Urban Services notes: the notes are named
    with the order they pass through; a chain back into the stepping stone's own department
    (Finance → Finance) is not told."""
    out = _ask(client, "U06", "Which other departments refer to G.O.Ms.No.19/2018?")
    texts = [f["text"] for f in _facts(out, "link records")]
    via88 = [t for t in texts if t.startswith("Urban Services (USD01), through G.O.Ms.No.88")]
    assert len(via88) == 1 and "AP-USD01-NOTE-USD0112-31-2022 cites G.O.Ms.No.88" in via88[0]
    assert not any(t.startswith("Finance (FIN01), through") for t in texts)


def test_a_chain_never_passes_through_or_ends_at_a_record_the_officer_may_not_see(
    client: TestClient,
) -> None:
    """D20 (USD01-12/58/2025) is DENY for U01: the chain through the GAD circular that only it
    completes is not told at all, and no chain names it."""
    six = _ask(client, "U06", "Which other departments refer to G.O.Ms.No.19/2018?")
    one = _ask(client, "U01", "Which other departments refer to G.O.Ms.No.19/2018?")
    assert "AP-USD01-NOTE-USD0112-58-2025" in json.dumps(six["statements"])
    assert "AP-USD01-NOTE-USD0112-58-2025" not in json.dumps(one)
    assert not any("through Circular Memo" in f["text"] for f in _facts(one, "link records"))
    fin = _ask(client, "U07", "Which other departments refer to G.O.Ms.No.19/2018?")
    assert "NOTE" not in json.dumps(fin["statements"])  # U07 may see no Urban Services file


def test_the_orders_an_e_file_cites_are_told_with_what_changed_after_it_cited_them(
    client: TestClient,
) -> None:
    out = _ask(
        client, "U06", "How have the orders cited in File No.USD01-12/31/2022-ESTT.I changed?"
    )
    facts = [f["text"] for f in _facts(out, "order records")]
    assert facts[0].startswith(
        "The noting in File No.USD01-12/31/2022-ESTT.I, written on 20-06-2022, cites G.O.Ms.No.88"
    )
    assert "2 change(s) to these orders took effect after it was written" in facts[0]
    assert any("G.O.Ms.No.31" in t and "superseded G.O.Ms.No.88" in t for t in facts)


def test_a_file_the_officer_may_not_see_and_one_that_does_not_exist_answer_alike(
    client: TestClient,
) -> None:
    """File USD01-12/31/2022-ESTT.I (D17-D19) is DENY for U03."""
    hidden = _ask(
        client, "U03", "How have the orders cited in File No.USD01-12/31/2022-ESTT.I changed?"
    )
    absent = _ask(
        client, "U03", "How have the orders cited in File No.USD01-12/99/2022-ESTT.I changed?"
    )
    for out in (hidden, absent):
        assert not [s for s in out["statements"] if s["source"] != "evidence"]
        assert "USD0112-31-2022" not in json.dumps(out)
    assert hidden["notices"] == absent["notices"]


def test_no_officer_is_told_of_a_file_record_outside_their_access(client: TestClient) -> None:
    """Every officer x every e-File: each record named by the file-history answer is ALLOW."""
    seed = json.loads((CORPUS / "eoffice" / "seed.json").read_text("utf-8"))
    with (CORPUS / "documents_index.csv").open(encoding="utf-8", newline="") as fh:
        index = [(r["canonical_id"], r["id"]) for r in csv.DictReader(fh)]
    with (CORPUS / "access_matrix.csv").open(encoding="utf-8", newline="") as fh:
        matrix = {r["doc_id"]: r for r in csv.DictReader(fh)}
    users = [u for u in matrix["D01"] if u.startswith("U")]
    checked = 0
    for uid in users:
        for f in seed["files"]:
            q = f"How have the orders cited in File No.{f['file_no']} changed?"
            for s in _ask(client, uid, q)["statements"]:
                if s["source"] == "evidence":
                    continue
                for c in s["citations"]:
                    doc = _doc_of(c["canonical_id"], index)
                    assert doc is not None and matrix[doc][uid] == "ALLOW", (uid, q, c)
                    checked += 1
                for cid, doc in index:
                    if cid in s["text"]:
                        assert matrix[doc][uid] == "ALLOW", (uid, q, cid)
    assert checked > 30


def test_a_gazette_publication_is_not_another_department(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Set v2 (deploy check, 18 Nov): a Gazette notification of the same order ("GAZ") was listed
    as a department linked to it. Only departments of the department table count."""
    import app.agents.answer as answer
    from app.agents.graph_facts import CrossDepartment, LinkedRecord
    from app.graph.repository import EdgeKind

    real = answer.cross_department_links

    def with_gazette(ctx: Any, seed: str) -> CrossDepartment | None:
        cd = real(ctx, seed)
        if cd is None:
            return None
        gaz = LinkedRecord(canonical_id="AP-GAZ-GAZETTE-X-1-2022", department="GAZ",
                           doc_type="Gazette", issue_date=None, kind=EdgeKind.REFERENCES,
                           outward=False)  # fmt: skip
        return cd.model_copy(update={"links": (*cd.links, gaz)})

    monkeypatch.setattr(answer, "cross_department_links", with_gazette)
    out = _ask(client, "U06", "Which other departments refer to G.O.Ms.No.88/2022?")
    assert "GAZ" not in json.dumps(_facts(out, "link records"))
