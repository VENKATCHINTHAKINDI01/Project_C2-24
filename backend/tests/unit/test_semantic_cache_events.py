"""A cached answer — exact or reworded — never survives the events that change what it may say
or who may see it (owner acceptance criterion 2, 18 Nov 2026; ADR-0053; CLAUDE.md §4.8):

1. the cited order is modified (a new version is ingested);
2. the cited order is superseded (a superseding order is ingested);
3. the officer loses access (their grants narrow);
4. the cited record is reclassified above the officer's clearance;
5. the cited record is removed (deleted or replaced).

1-2 are tested where invalidation happens (ingestion drops the answer; the reworded index then
points at nothing). 3-5 through the orchestrator: every hit re-checks each cited record against
the officer's access NOW, so even a change no hook sees is a miss."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from app.agents.orchestrator import TurnServices, run_turn
from app.auth.policy import scope_for
from app.cache.semantic import SemanticIndex
from app.config import REPO_ROOT, get_settings
from app.ingestion.pipeline import IngestionStores
from app.main import create_app
from app.memory.session import SessionMemory
from app.tracking.query_log import InMemoryQueryLog
from tests.unit.mock_access import CLASSES, POLICY, new_store
from tests.unit.test_ingestion_pipeline import _ingest, _src
from tests.unit.test_orchestrator import AnswersOnly

Q1 = "Which orders govern the outsourced data entry operators now?"
Q2 = "Which orders govern outsourced data entry operators?"  # reworded
TEXT = REPO_ROOT / "data" / "synthetic" / "mock_v1" / "ground_truth" / "text"


# ---- 1, 2: where invalidation happens (ingestion) ---------------------------------------------


def _cached(stores: IngestionStores, cid: str) -> tuple[Any, str]:
    scope = scope_for("U01", new_store(), POLICY, CLASSES)
    stores.reworded = SemanticIndex(enabled=True)
    stores.cache.put(Q1, scope, '{"status": "answered"}', frozenset({cid}))
    stores.reworded.remember(scope.signature, "anchors", Q1, Q1)
    earlier = stores.reworded.find(scope.signature, "anchors", Q2)
    assert earlier is not None and stores.cache.get(earlier, scope) is not None  # baseline: hit
    return scope, earlier


def test_1_a_new_version_of_the_cited_order_drops_the_reworded_answer() -> None:
    stores = IngestionStores()
    old = _ingest(stores, "D03")
    scope, earlier = _cached(stores, old.canonical_id or "")
    revised = (TEXT / "D03.txt").read_text("utf-8") + "\n9. This order is revised.\n"
    new = _ingest(stores, "D03", data=revised.encode(), src=_src("D03"))
    assert new.canonical_id == old.canonical_id and new.invalidated_answers == 1
    assert stores.cache.get(earlier, scope) is None  # the reworded index points at nothing


def test_2_a_superseding_order_drops_the_reworded_answer() -> None:
    stores = IngestionStores()
    old = _ingest(stores, "D03")
    scope, earlier = _cached(stores, old.canonical_id or "")
    new = _ingest(stores, "D04")  # G.O.Ms.No.31/2025 supersedes G.O.Ms.No.88/2022
    assert new.invalidated_answers == 1
    assert stores.cache.get(earlier, scope) is None


# ---- 3, 4, 5: through the orchestrator, re-checked on every hit ------------------------------


def _turns() -> tuple[Any, Callable[..., Any]]:
    app = create_app(get_settings().model_copy(update={"sandbox": True}))
    TestClient(app).__enter__()
    run = app.state.assist_runtime()
    run.stores.reworded = SemanticIndex(enabled=True)
    full = app.state.adapter.officer_context("U01")
    n = 0

    def ask(q: str, officer: Any = full) -> Any:
        store = run.store_for(officer)
        svc = TurnServices(
            officer=officer,
            ctx=run.tool_context(officer.user_id, store),
            memory=SessionMemory(),
            cache=run.stores.cache,
            query_log=InMemoryQueryLog(),
            texts=run.texts,
            llm=AnswersOnly(),
            departments=run.departments,
            file_papers=lambda f: [],
            tags_of=run.tags,
            reworded=run.stores.reworded,
        )
        nonlocal n
        n += 1
        return run_turn(svc, session_id=f"{n:016d}", message=q, request_id=f"R{n}")

    return run, ask


def _answered_and_reused(ask: Callable[..., Any]) -> set[str]:
    first = ask(Q1)
    assert first.outcome == "answered", first.outcome
    assert ask(Q2).cache_hit  # baseline: the reworded repeat is served
    return {c["canonical_id"] for s in first.result["statements"] for c in s["citations"]}


def test_3_an_officer_who_loses_access_never_gets_the_cached_answer() -> None:
    """The narrowed officer has a new scope signature: the earlier answer (citing a record they
    may no longer open) is never served, reworded or not. They get an answer of their own, which
    they may then reuse within their own scope."""
    from app.agents.tools import visible_document

    run, ask = _turns()
    cited = _answered_and_reused(ask)
    officer = ask.__defaults__[0]  # type: ignore[index]
    narrow = officer.model_copy(
        update={"assigned_files": frozenset(), "handled_files": frozenset(), "section": "NONE"}
    )
    ctx = run.tool_context("U01", run.store_for(narrow))
    lost = {cid for cid in cited if visible_document(ctx, cid) is None}
    assert lost  # the scenario: the narrowed officer may no longer open a cited record
    for q in (Q2, Q1):
        got = ask(q, narrow)
        shown = {c["canonical_id"] for s in got.result["statements"] for c in s["citations"]}
        assert not shown & lost, (q, shown)
        assert all(visible_document(ctx, cid) is not None for cid in shown)


def test_4_a_cited_record_reclassified_above_the_officer_is_never_served() -> None:
    run, ask = _turns()
    cited = _answered_and_reused(ask)
    top = max(CLASSES.levels, key=lambda lv: lv.rank).name
    for d in list(run.stores.index._docs):  # noqa: SLF001 — reclassify in place, no hook
        if d.canonical_id in cited:
            run.stores.index.upsert(
                d.model_copy(update={"tags": d.tags.model_copy(update={"classification": top})})
            )
    assert not ask(Q2).cache_hit and not ask(Q1).cache_hit


def test_5_a_cited_record_removed_is_never_served() -> None:
    run, ask = _turns()
    cited = _answered_and_reused(ask)
    for cid in cited:
        run.stores.index.remove(cid)
    assert not ask(Q2).cache_hit and not ask(Q1).cache_hit
