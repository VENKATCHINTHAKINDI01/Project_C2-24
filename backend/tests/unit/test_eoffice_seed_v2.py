"""Mock e-Office seed v2 (ADR-0020, plan §11.6): synthetic, reproducible, no answer keys, never
reaches further than the v2 access matrix allows; v1 + v2 merge without identifier clashes."""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from app.config import REPO_ROOT, Settings
from app.connectors.eoffice import ConnectorError
from app.eoffice_mock.adapter import adapter_from_seed, load_seed, merge_seeds
from app.eoffice_mock.corpus import artefacts_from_index
from app.eoffice_mock.models import NoteState
from app.main import sandbox_ocr

V2 = REPO_ROOT / "data" / "synthetic" / "mock_v1" / "efiles_v2"
SEED_PATH = V2 / "eoffice" / "seed_v2.json"
GENERATOR = REPO_ROOT / "data" / "synthetic" / "tools" / "build_eoffice_seed_v2.py"
SEED = load_seed(SEED_PATH)
V1 = load_seed(REPO_ROOT / "data" / "synthetic" / "mock_v1" / "eoffice" / "seed.json")
RANK = {"UNCLASSIFIED": 0, "RESTRICTED": 1, "CONFIDENTIAL": 2, "SECRET": 3}
NOW = dt.datetime(2026, 1, 2, 10, 0, tzinfo=dt.UTC)


def test_seed_is_up_to_date_with_its_generator() -> None:
    res = subprocess.run(  # noqa: S603 — fixed local script, no user input
        [sys.executable, str(GENERATOR), "--check"], capture_output=True, text=True, check=False
    )
    assert res.returncode == 0, res.stderr


def test_counts_and_labels() -> None:
    assert SEED.synthetic and "not NIC e-Office" in SEED.banner
    assert SEED.corpus == "efiles_v2" and SEED.as_of == dt.date(2025, 12, 31)
    assert len(SEED.files) == 203 and len(SEED.receipts) == 203  # 201 + 2 demo holdback files
    assert len([p for p in SEED.profiles if p.login]) == 21
    assert {f.department for f in SEED.files} == {"FIN01", "GAD01", "ESE01"}


def test_seed_holds_no_answer_keys() -> None:
    """Scenario keys, conflict types and the cited-order lists stay out (CLAUDE.md §9.2)."""
    raw = SEED_PATH.read_text(encoding="utf-8")
    for word in ("planted", "conflict", "scenario", "ground_truth", "SUPERSEDES", "golden"):
        assert word not in raw, word
    plan = yaml.safe_load((V2 / "scenarios" / "scenarios.yaml").read_text(encoding="utf-8"))
    keys = {s["key"] for items in plan["departments"].values() for s in items}
    assert not {k for k in keys if re.search(rf"\b{re.escape(k)}\b", raw)}


def test_every_actor_is_a_profile_and_consulted_offices_cannot_log_in() -> None:
    ids = {p.user_id for p in SEED.profiles}
    actors = {n.author for n in SEED.notes} | {
        u for m in SEED.movements for u in (m.from_user, m.to_user)
    }
    assert actors <= ids
    for p in SEED.profiles:
        if p.user_id.startswith("POST-"):
            assert not p.login and {s.value for s in p.search_scopes} == {"individual"}


def test_notes_and_movements_run_forward_in_time() -> None:
    by_file: dict[str, list[dt.datetime]] = {}
    for n in sorted(SEED.notes, key=lambda n: (n.computer_no, n.note_no)):
        by_file.setdefault(n.computer_no, []).append(n.versions[0].saved_at)
        assert (n.state is NoteState.GREEN) == (n.confirmed_at is not None)
    for times in by_file.values():
        assert times == sorted(times)
    moves: dict[str, list[tuple[int, dt.datetime]]] = {}
    for m in SEED.movements:
        moves.setdefault(m.computer_no, []).append((m.seq, m.sent_at))
    for ms in moves.values():
        ms.sort()
        assert [s for s, _ in ms] == list(range(1, len(ms) + 1))
        assert [t for _, t in ms] == sorted(t for _, t in ms)


def test_reach_never_exceeds_the_access_matrix() -> None:
    """An officer may open a file (e-Office reach) and read it (clearance) only where the v2
    access matrix says ALLOW, and nowhere less (one section per profile: known gap, PROGRESS.md)."""
    with (V2 / "access_matrix.csv").open(encoding="utf-8", newline="") as fh:
        matrix = {r["file_no"]: r for r in csv.DictReader(fh)}
    adapter = adapter_from_seed(SEED, now=NOW)
    under = 0
    for p in SEED.profiles:
        if not p.login:
            continue
        for f in SEED.files:
            try:
                adapter.file_context(f.computer_no, p.user_id)
                reach = RANK[p.clearance] >= RANK[f.classification]
            except ConnectorError:
                reach = False
            allowed = matrix[f.file_no][p.user_id] == "ALLOW"
            assert not (reach and not allowed), (p.user_id, f.file_no)
            under += allowed and not reach
    assert under == 0  # today every second-section file passed through its Assistant Secretary


def test_v1_and_v2_merge_without_clashes() -> None:
    both = merge_seeds(V1, SEED)
    assert len(both.files) == len(V1.files) + 203
    assert both.as_of == max(V1.as_of, SEED.as_of)
    assert both.corpus == "mock_v1+efiles_v2"
    with pytest.raises(ConnectorError):
        merge_seeds(SEED, SEED)


def test_v2_needs_the_public_corpus_dir() -> None:
    with pytest.raises(ValueError, match="PUBLIC_CORPUS_DIR"):
        Settings(sandbox_seed="v2", sandbox_public_corpus_dir=None)


def _index(tmp: Path, rows: list[dict[str, str]]) -> Path:
    idx = tmp / "idx.csv"
    with idx.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return idx


def _row(file: str, sha: str) -> dict[str, str]:
    return {
        "id": "X",
        "file": file,
        "department": "FIN01",
        "section": "HR-I",
        "classification": "UNCLASSIFIED",
        "raw_reference": "",
        "sha256": sha,
    }


def test_public_index_checks_hash_and_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.pdf").write_bytes(b"%PDF-1.4 a")
    good = hashlib.sha256(b"%PDF-1.4 a").hexdigest()
    arts = artefacts_from_index(_index(tmp_path, [_row("a.pdf", good)]), root, "public://")
    assert arts[0].source_uri == "public://a.pdf" and arts[0].file_no is None
    with pytest.raises(ConnectorError, match="changed"):
        artefacts_from_index(_index(tmp_path, [_row("a.pdf", "0" * 64)]), root, "public://")
    (tmp_path / "out.pdf").write_bytes(b"x")
    with pytest.raises(ConnectorError, match="outside"):
        artefacts_from_index(_index(tmp_path, [_row("../out.pdf", "")]), root, "public://")


def test_v2_documents_carry_their_file() -> None:
    """Correspondence pages, one note sheet per file and one Yellow draft per pending file."""
    arts = artefacts_from_index(V2 / "eoffice" / "documents_index.csv", V2, "mock://efiles_v2/")
    files = {f.file_no: f for f in SEED.files}
    yellow = [n for n in SEED.notes if n.state is NoteState.YELLOW]
    assert len(arts) == len(SEED.correspondence) + len(SEED.files) + len(yellow)
    for a in arts:
        assert a.file_no in files
        assert a.classification == files[a.file_no].classification
        assert a.data.startswith(b"SYNTHETIC")
    drafts = [a for a in arts if a.filename.endswith("_DRAFT.txt")]
    assert len(drafts) == len(yellow) and all(b"[Draft note" in a.data for a in drafts)


def test_v2_replays_the_corpus_ocr_already_paid_for(tmp_path: Path) -> None:
    """v2: recorded Document AI responses from the data root are replayed (no GCP call); v1-only
    settings never pick them up."""
    version = "pretrained-ocr-v2.1.1-2025-01-31"
    rec = tmp_path / "staging" / "ocr_recorded" / "documentai" / version
    rec.mkdir(parents=True)
    data = b"%PDF-1.4 scan"
    doc = {"text": "G.O.Ms.No.1", "pages": [{"page_number": 1, "layout": {"confidence": 0.98}}]}
    (rec / f"{hashlib.sha256(data).hexdigest()}.json").write_text(json.dumps(doc))
    s = Settings(sandbox_seed="v2", sandbox_public_corpus_dir=tmp_path)
    engine = sandbox_ocr(s, {})
    assert engine is not None
    assert engine.read(data, "application/pdf", [1]).pages[0].confidence == 0.98
    assert sandbox_ocr(Settings(sandbox_seed="v1"), {}) is None


def test_no_file_document_is_readable_where_the_matrix_denies() -> None:
    """Zero disclosure on set v2 at document level (CLAUDE.md §2.4, §4): the assistant's own
    check on every note sheet, draft and correspondence page, for every officer. Found 13 Nov
    2026: UNCLASSIFIED file papers counted as "public" and were readable by every officer
    (e.g. open-file notices named Cabinet.II files to a Finance ASO)."""
    from app.auth.models import DocumentAccessTags
    from app.auth.policy import check, load_access_policy
    from app.auth.store import InMemoryAuthzStore
    from app.config import load_classification
    from app.connectors.eoffice import grants_from_context

    onto = REPO_ROOT / "data" / "ontology"
    policy = load_access_policy(onto / "access_policy.yaml")
    classes = load_classification(onto / "classification.yaml")
    with (V2 / "access_matrix.csv").open(encoding="utf-8", newline="") as fh:
        matrix = {r["file_no"]: r for r in csv.DictReader(fh)}
    with (V2 / "eoffice" / "documents_index.csv").open(encoding="utf-8", newline="") as fh:
        docs = [r for r in csv.DictReader(fh) if r["raw_reference"].startswith("File No.")]
    assert len(docs) > 400
    adapter = adapter_from_seed(SEED, now=NOW)
    leaks = []
    for p in SEED.profiles:
        if not p.login:
            continue
        store = InMemoryAuthzStore(grants_from_context(adapter.officer_context(p.user_id)))
        for r in docs:
            file_no = r["raw_reference"].removeprefix("File No.")
            tags = DocumentAccessTags(
                doc_id=r["id"],
                department=r["department"],
                section=r["section"] or None,
                classification=r["classification"],
                file_no=file_no,
            )
            if (
                check(p.user_id, tags, store, policy, classes).allowed
                and matrix[file_no][p.user_id] != "ALLOW"
            ):
                leaks.append((p.user_id, r["id"]))
    assert leaks == [], f"{len(leaks)} disclosures, e.g. {leaks[:3]}"


def test_the_scope_filter_agrees_that_file_papers_are_never_public() -> None:
    """The pushed-down filter (`Scope.admits`) must match `check`: an UNCLASSIFIED paper of a
    Cabinet.II file is outside a Finance ASO's scope; a published order stays public."""
    from app.auth.models import DocumentAccessTags
    from app.auth.policy import load_access_policy, scope_for
    from app.auth.store import InMemoryAuthzStore
    from app.config import load_classification
    from app.connectors.eoffice import grants_from_context

    onto = REPO_ROOT / "data" / "ontology"
    policy = load_access_policy(onto / "access_policy.yaml")
    classes = load_classification(onto / "classification.yaml")
    adapter = adapter_from_seed(SEED, now=NOW)
    store = InMemoryAuthzStore(grants_from_context(adapter.officer_context("V01")))
    scope = scope_for("V01", store, policy, classes)
    paper = DocumentAccessTags(
        doc_id="N1",
        department="GAD01",
        section="CABINET.II",
        classification="UNCLASSIFIED",
        file_no="GAD01-CABN0BR/211/2025-CABINET.II",
    )
    order = DocumentAccessTags(
        doc_id="AP-GAD01-GOMS-59-2018", department="GAD01", classification="UNCLASSIFIED"
    )
    assert not scope.admits(paper) and scope.admits(order)


def test_a_held_back_order_arrives_once_and_raises_an_event() -> None:
    """Demo holdback (data collection plan step 11): not in documents() until it arrives."""
    from app.connectors.eoffice import EventKind, SourceArtefact

    art = SourceArtefact(
        source_uri="public://staging/holdback/AP-GAD01-GOMS-139-2025/order.pdf",
        filename="order.pdf",
        department="GAD01",
        section="PRO-A",
        classification="UNCLASSIFIED",
        file_no=None,
        data=b"%PDF-",
    )
    adapter = adapter_from_seed(SEED, now=NOW, arrivals=[art])
    assert adapter.pending_orders() == [art.source_uri] and art not in adapter.documents()
    ev = adapter.order_arrives(art.source_uri)
    assert ev.kind is EventKind.ORDER_RECEIVED and ev.object_id == "AP-GAD01-GOMS-139-2025"
    assert art in adapter.documents() and adapter.pending_orders() == []
    with pytest.raises(ConnectorError):
        adapter.order_arrives(art.source_uri)
