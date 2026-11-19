"""Entity resolution — people and offices named in the records (Tier 2; ADR-0058). Extraction is
deterministic and never merges names by guess; answers are scoped: a name found only in records
outside the officer's scope gives exactly what an unknown name gives (CLAUDE.md §4.7, §5.6)."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.identifiers.entities import EntityIndex, EntityKind, in_question, mentions, person_key
from app.main import create_app

ROOT = Path(__file__).resolve().parents[3]
CORPUS = ROOT / "data" / "synthetic" / "mock_v1"

NOTE = """Subject: Establishment – Sri K. Venkata Ramana, Superintendent, Regional Office, Tirupati
– Request for transfer to Regional Office, Kurnool on spouse grounds – Reg.
1. Sri K. Venkata Ramana, Superintendent, Regional Office, Tirupati, has requested transfer.
V. Naga Lakshmi / Assistant Section Officer (Estt.I) / 26/05/2025 02:30 PM
P. Anil Kumar
Assistant Section Officer (Estt.I)
13/06/2022 11:42 AM
"""


def test_people_offices_and_signatures_are_found_with_their_roles() -> None:
    found = mentions(NOTE)
    people = {(m.key, m.role, m.signed) for m in found if m.kind is EntityKind.PERSON}
    assert ("k|venkata ramana", "Superintendent, Regional Office, Tirupati", False) in people
    assert ("v|naga lakshmi", "Assistant Section Officer (Estt.I)", True) in people
    assert ("p|anil kumar", "Assistant Section Officer (Estt.I)", True) in people  # 3-line form
    offices = {m.key for m in found if m.kind is EntityKind.OFFICE}
    assert offices == {"regional office|tirupati", "regional office|kurnool"}


@pytest.mark.parametrize(
    "written",
    ["Sri K. Venkata Ramana", "Sri K.Venkata Ramana", "K. Venkata Ramana", "Sri K Venkata Ramana"],
)
def test_the_same_person_written_differently_is_one_person(written: str) -> None:
    (q,) = [
        e for e in in_question(f"Decisions concerning {written}?") if e.kind is EntityKind.PERSON
    ]
    assert q.key == person_key("K", "Venkata Ramana") and not q.partial


def test_different_initials_are_different_people_and_a_bare_name_is_only_a_name_match() -> None:
    idx = EntityIndex.build(
        {"A": "Sri K. Venkata Ramana, Superintendent", "B": "Sri M. Venkata Ramana, Typist"}
    )
    (full,) = in_question("about Sri K. Venkata Ramana", idx.person_names())
    assert idx.keys_for(full) == ["k|venkata ramana"]  # never merged with M. Venkata Ramana
    (bare,) = in_question("about Venkata Ramana", idx.person_names())
    assert bare.partial and idx.keys_for(bare) == ["k|venkata ramana", "m|venkata ramana"]
    assert in_question("Who is the Deputy Secretary?", idx.person_names()) == []


def test_reindexing_a_record_replaces_its_mentions() -> None:
    idx = EntityIndex.build({"A": "Sri K. Venkata Ramana"})
    idx.add("A", "Smt. P. Sandhya Rani")
    assert "k|venkata ramana" not in idx.by_key and set(idx.records("p|sandhya rani")) == {"A"}


# ---- through the assistant ------------------------------------------------------------------


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    from evaluation.ask_golden import confirm_held_scans

    app = create_app(get_settings().model_copy(update={"sandbox": True}))
    seed = json.loads((CORPUS / "eoffice" / "seed.json").read_text("utf-8"))
    with TestClient(app) as c:
        confirm_held_scans(c, seed)
        yield c


def _ask(c: TestClient, uid: str, q: str) -> dict[str, Any]:
    r = c.post("/assist/ask", json={"question": q}, headers={"X-Sandbox-User": uid})
    assert r.status_code == 200, r.text
    return dict(r.json())


def _named(out: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in out["statements"] if s["source"] == "entity records"]


def test_an_officer_who_may_see_the_files_is_told_every_record_naming_the_person(
    client: TestClient,
) -> None:
    out = _ask(client, "U06", "Summarise all decisions concerning Sri K. Venkata Ramana.")
    (fact,) = _named(out)
    assert fact["text"].startswith("3 record(s) name Sri K. Venkata Ramana (Superintendent)")
    cited = [c["canonical_id"] for c in fact["citations"]]
    assert len(cited) == 3 and "AP-USD01-NOTE-USD0112-58-2025" in cited
    assert sum("USD0131-4-2025" in c for c in cited) == 2  # the vigilance file's two notes
    assert "File No.USD01-31/4/2025-VIG" in fact["text"]
    assert out["status"] == "answered"


def test_a_name_only_in_records_outside_the_scope_answers_like_an_unknown_name(
    client: TestClient,
) -> None:
    """Golden Q12: U03 may see none of D20-D23, so Sri K. Venkata Ramana is as unknown to U03 as a
    person who appears nowhere."""
    known = _ask(client, "U03", "Summarise all decisions concerning Sri K. Venkata Ramana.")
    unknown = _ask(client, "U03", "Summarise all decisions concerning Sri K. Venkata Rao.")
    for out in (known, unknown):
        assert not _named(out)
        assert "USD0112-58" not in json.dumps(out) and "USD0131" not in json.dumps(out)
    assert known["status"] == unknown["status"] and known["notices"] == unknown["notices"]
    assert known["documents"] == unknown["documents"]


def test_a_bare_name_says_it_matched_on_the_name(client: TestClient) -> None:
    (fact,) = _named(_ask(client, "U04", "What happened to Venkata Ramana's request?"))
    assert 'matched on the name "Venkata Ramana"; the question gave no initials' in fact["text"]


def test_records_an_officer_signed_are_marked(client: TestClient) -> None:
    (fact,) = _named(_ask(client, "U01", "Which files did S. Madhavi submit?"))
    assert fact["text"].count("signed by them") == 3


def test_no_officer_is_told_of_a_person_or_office_outside_their_access(client: TestClient) -> None:
    """Every officer x every person and office the records name: each record named is ALLOW in the
    independent access matrix, and nothing else is named."""
    with (CORPUS / "documents_index.csv").open(encoding="utf-8", newline="") as fh:
        index = [(r["canonical_id"], r["id"]) for r in csv.DictReader(fh)]
    with (CORPUS / "access_matrix.csv").open(encoding="utf-8", newline="") as fh:
        matrix = {r["doc_id"]: r for r in csv.DictReader(fh)}
    run = client.app.state.assist_runtime()  # type: ignore[attr-defined]
    names = []
    for recs in run.entities.by_key.values():
        ms = next(iter(recs.values()))
        names.append(ms[0].surface)
    users = [u for u in matrix["D01"] if u.startswith("U")]
    checked = 0

    def doc_of(cid: str) -> str | None:
        hits = [(len(c), d) for c, d in index if cid == c or cid.startswith(c + "-")]
        return max(hits)[1] if hits else None

    for uid in users:
        for name in names:
            for s in _named(_ask(client, uid, f"Which records concern {name}?")):
                for c in s["citations"]:
                    doc = doc_of(c["canonical_id"])
                    assert doc is not None and matrix[doc][uid] == "ALLOW", (uid, name, c)
                    checked += 1
    assert checked > 50


def test_two_officers_with_the_same_name_are_told_apart_by_their_officer_id() -> None:
    """Owner, 18 Nov 2026: the e-Office officer ID is the identity, the name only finds them."""
    from app.connectors.eoffice import Signer

    sheet = "1) Submitted.\n\n01/02/2025 10:00 AM\nK. SRAVANI\nSECTION OFFICER\n"
    idx = EntityIndex()
    idx.add("A", sheet, (Signer(officer_id="V01", name="K. Sravani", post="Section Officer"),))
    idx.add("B", sheet, (Signer(officer_id="V77", name="K. Sravani", post="Section Officer"),))
    (q,) = in_question("Which notes did K. Sravani sign?", idx.person_names(), idx.officer_ids())
    assert idx.keys_for(q) == ["officer:V01", "officer:V77"]  # two people, never merged
    (by_id,) = in_question("notes signed by V77", (), idx.officer_ids())
    assert idx.keys_for(by_id) == ["officer:V77"] and set(idx.records("officer:V77")) == {"B"}


def test_a_typed_signature_resolves_only_to_the_paper_s_own_signers() -> None:
    from app.connectors.eoffice import Signer

    sheet = (
        "5) Submitted for orders.\n\n21/12/2017 11:39 AM\nB. SURESH KUMAR, I.A.S\nJOINT SECRETARY\n"
    )
    (m,) = mentions(sheet, (Signer(officer_id="V20", name="B. Suresh Kumar", post="JS"),))
    assert (m.key, m.role, m.signed) == ("officer:V20", "Joint Secretary", True)
    (n,) = mentions(sheet)  # no officer recorded for this paper: a name, never a guessed ID
    assert n.key == "b|suresh kumar" and n.kind is EntityKind.PERSON


def test_abbreviations_and_ocr_noise_are_not_people() -> None:
    text = "Published in A.P. Gazette. U.O. Note dated … in respect of Ch. Suresh Babu."
    keys = {m.key for m in mentions(text)}
    assert keys == {"ch|suresh babu"}
    assert {m.key for m in mentions(text, loose=False)} == set()  # OCR'd public order: strict


def test_a_person_given_as_an_example_is_not_what_the_question_is_about() -> None:
    """Golden Q01: "… a spouse-ground transfer request like Sri Ch. Naveen Kumar's …" asks for
    precedents, not about Ch. Naveen Kumar."""
    q = "Has a spouse-ground transfer request like Sri Ch. Naveen Kumar's been decided before?"
    assert in_question(q) == []
    assert [e.key for e in in_question("What was decided on Sri Ch. Naveen Kumar's request?")] == [
        "ch|naveen kumar"
    ]
