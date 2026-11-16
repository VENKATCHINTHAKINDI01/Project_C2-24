"""Two stores behind one rung (ADR-0028): e-Office papers in memory + the public corpus in the
cloud must answer exactly like one store holding both, under every scope; and the deployed
sandbox reads the cloud parts through the same ladder."""

from __future__ import annotations

import random
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.models import DocumentAccessTags
from app.config import get_settings
from app.graph.repository import Direction, EdgeKind, GraphEdge, GraphNode, InMemoryGraphRepository
from app.main import create_app
from app.retrieval.cloud import CloudRungs
from app.retrieval.composite import CompositeGraph, CompositeHybrid, CompositeScopedIndex
from app.retrieval.ladder import InMemoryKeywordIndex, ScoredDocument
from app.retrieval.scoped import IndexedDocument, InMemoryScopedIndex, L1Criteria
from tests.unit.test_bigquery_index import SCOPES, corpus
from tests.unit.test_graph_postgres import _random_graph
from tests.unit.test_graph_postgres import scope as gscope


def _split(items: list[Any], rng: random.Random) -> tuple[list[Any], list[Any]]:
    """Two stores; about one item in ten is held in both (the cited orders are)."""
    a, b = [], []
    for x in items:
        r = rng.random()
        (a if r < 0.45 else b).append(x)
        if r > 0.9:
            a.append(x)
    return a, b


@pytest.mark.parametrize("seed", range(6))
def test_two_graph_stores_walk_like_one(seed: int) -> None:
    nodes, edges = _random_graph(seed)
    rng = random.Random(seed)  # noqa: S311 — test data
    one, parts = InMemoryGraphRepository(), (InMemoryGraphRepository(), InMemoryGraphRepository())
    for n in nodes:
        one.upsert_node(n)
    for n in nodes:  # every store knows the nodes its edges touch
        for p in parts:
            p.upsert_node(n)
    a, b = _split(edges, rng)
    for e in edges:
        one.upsert_edge(e)
    for p, part in zip(parts, (a, b), strict=True):
        for e in part:
            p.upsert_edge(e)
    both = CompositeGraph(parts)
    for sc in (gscope("FIN"), gscope("GAD", wide=False, files=("F-1",)), gscope("ESE", rank=2)):
        for _ in range(25):
            seeds = [rng.choice(nodes).canonical_id for _ in range(3)]
            kw: dict[str, Any] = {
                "kinds": frozenset(rng.sample(list(EdgeKind), 5)),
                "direction": rng.choice(list(Direction)),
                "max_hops": rng.randint(1, 3),
                "include_unconfirmed": rng.random() > 0.5,
            }
            assert both.walk(seeds, sc, **kw) == one.walk(seeds, sc, **kw)


def test_a_walk_crosses_from_memory_to_the_cloud_and_never_through_a_closed_node() -> None:
    tag = {"department": "FIN", "section": "A", "classification": "UNCLASSIFIED"}

    def n(cid: str, **kw: Any) -> GraphNode:
        return GraphNode(
            canonical_id=cid, tags=DocumentAccessTags(doc_id=cid, **{**tag, "file_no": None, **kw})
        )

    mem, cloud = InMemoryGraphRepository(), InMemoryGraphRepository()
    for g, ids in ((mem, ("NOTE", "GO1")), (cloud, ("GO1", "GO2", "SECRET", "GO3"))):
        for cid in ids:
            g.upsert_node(n(cid, classification="SECRET") if cid == "SECRET" else n(cid))
    mem.upsert_edge(GraphEdge(source="NOTE", kind=EdgeKind.CITES, target="GO1"))
    cloud.upsert_edge(GraphEdge(source="GO2", kind=EdgeKind.SUPERSEDES, target="GO1"))
    cloud.upsert_edge(GraphEdge(source="SECRET", kind=EdgeKind.AMENDS, target="GO2"))
    cloud.upsert_edge(GraphEdge(source="GO3", kind=EdgeKind.AMENDS, target="SECRET"))
    hits = CompositeGraph((mem, cloud)).walk(
        ["NOTE"], gscope("FIN", rank=1), kinds=frozenset(EdgeKind), direction=Direction.BOTH,
        max_hops=4,
    )  # fmt: skip
    assert [h.canonical_id for h in hits] == ["GO1", "GO2"]  # GO3 only through SECRET: not reached


@pytest.mark.parametrize("seed", range(3))
def test_two_metadata_stores_answer_like_one(seed: int) -> None:
    docs = corpus(seed)
    rng = random.Random(seed)  # noqa: S311
    a, b = _split(docs, rng)
    one = InMemoryScopedIndex(docs)
    both = CompositeScopedIndex((InMemoryScopedIndex(a), InMemoryScopedIndex(b)))
    for sc in SCOPES:
        for c in (
            L1Criteria(),
            L1Criteria(department="FIN01"),
            L1Criteria(subject_terms=("leave",)),
        ):
            assert both.filter(c, sc) == one.filter(c, sc)
        for d in docs[:60]:
            assert {x.canonical_id for x in both.exact(d.canonical_id, sc)} == {
                x.canonical_id for x in one.exact(d.canonical_id, sc)
            }


class _Fixed:
    def __init__(self, hits: list[tuple[IndexedDocument, float]]) -> None:
        self.hits = hits

    def search(self, query: str, scope: Any, top_k: int) -> list[ScoredDocument]:
        return [ScoredDocument(doc=d, score=s) for d, s in self.hits if scope.admits(d.tags)]


def test_l2_scores_are_judged_by_each_stores_own_threshold() -> None:
    sc = SCOPES[-1]  # GAD01, department-wide, top clearance: sees GAD01 + published orders
    seen = [x for x in corpus(0) if sc.admits(x.tags)][:4]
    keyword = _Fixed([(seen[0], 6.0), (seen[1], 2.0)])  # BM25 scale, own threshold 4.0
    cloud = _Fixed([(seen[2], 0.9), (seen[3], 0.3)])  # 0-1 scale
    ladder_min = 3.0
    calibrated = CompositeHybrid(((keyword, 4.0), (cloud, 0.5)), ladder_min).search("q", sc, 10)
    passed = {s.doc.canonical_id for s in calibrated if s.score >= ladder_min}
    assert passed == {seen[0].canonical_id, seen[2].canonical_id}
    raw = CompositeHybrid(((keyword, 4.0), (cloud, None)), ladder_min).search("q", sc, 10)
    assert {s.doc.canonical_id for s in raw if s.score >= ladder_min} == {seen[0].canonical_id}
    assert len(raw) == 4  # uncalibrated hits are still listed


# ---- the sandbox reading a cloud part through the ladder ---------------------------------------

APP = create_app(get_settings().model_copy(update={"sandbox": True}))
WORD = "zzqvexillology"  # a word no synthetic paper contains


def _cloud_doc(cid: str, dept: str, cls: str) -> IndexedDocument:
    return IndexedDocument(
        canonical_id=cid,
        tags=DocumentAccessTags(
            doc_id=cid, department=dept, section=None, classification=cls, file_no=None
        ),
        doc_type="Government Order",
        issue_date=None,
        subject=f"Rules on {WORD} for departments",
    )


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(APP) as c:
        run = APP.state.assist_runtime()
        public = _cloud_doc("AP-FIN01-GOMS-9001-2024", "FIN01", "UNCLASSIFIED")
        secret = _cloud_doc("AP-USD01-GOMS-9002-2024", "USD01", "CONFIDENTIAL")
        docs = [public, secret]
        g = InMemoryGraphRepository()
        for x in docs:
            g.upsert_node(GraphNode(canonical_id=x.canonical_id, tags=x.tags))
        run.cloud = CloudRungs(
            index=InMemoryScopedIndex(docs),
            graph=g,
            l2=InMemoryKeywordIndex([(x, x.subject) for x in docs]),
            l2_min_score=None,
        )
        try:
            yield c
        finally:
            run.cloud = None


def test_the_ladder_reads_the_cloud_part_within_scope(client: TestClient) -> None:
    from app.auth.policy import scope_for
    from tests.unit.test_sandbox_api import USERS, _h

    run = APP.state.assist_runtime()
    secret_tags = _cloud_doc("x", "USD01", "CONFIDENTIAL").tags
    allowed_secret = 0
    for uid in USERS:
        body = client.post("/assist/search", json={"query": WORD}, headers=_h(uid)).text
        assert "9001-2024" in body  # a published order: every officer
        store = run.store_for(APP.state.adapter.officer_context(uid))
        may = scope_for(uid, store, run.policy, run.classification).admits(secret_tags)
        assert ("9002-2024" in body) == may  # the cloud part answers within the officer's scope
        allowed_secret += may
    assert 0 < allowed_secret < len(USERS)  # the test really separates officers


class _Refusing:
    """A cloud store that refuses every query, as BigQuery did without bigquery.jobs.create."""

    def exact(self, canonical_id: str, scope: Any) -> list[IndexedDocument]:
        raise RuntimeError("403 Access Denied: user c2-api does not have bigquery.jobs.create")

    def filter(self, criteria: Any, scope: Any) -> list[IndexedDocument]:
        raise RuntimeError("403 Access Denied: user c2-api does not have bigquery.jobs.create")


def test_a_refusing_cloud_store_fails_closed_with_a_neutral_message(client: TestClient) -> None:
    from app.main import NEUTRAL_FAILURE
    from tests.unit.test_sandbox_api import _h

    run = APP.state.assist_runtime()
    keep = run.cloud
    run.cloud = CloudRungs(index=_Refusing(), graph=InMemoryGraphRepository(), l2=None,
                           l2_min_score=None)  # fmt: skip
    try:
        with TestClient(APP, raise_server_exceptions=False) as c:
            r = c.post("/assist/reference", json={"text": "G.O.Ms.No.31/2018"}, headers=_h("U06"))
    finally:
        run.cloud = keep
    assert r.status_code == 503 and r.json() == {"detail": NEUTRAL_FAILURE}
    assert "bigquery" not in r.text.lower() and "denied" not in r.text.lower()


class _PassageText:
    """Cloud passages stand-in: text only for an officer whose scope admits the order."""

    def __init__(self, docs: list[IndexedDocument]) -> None:
        self.docs = {d.canonical_id: d for d in docs}
        self.asked: list[str] = []

    def text(self, cid: str, scope: Any) -> str:
        self.asked.append(cid)
        d = self.docs.get(cid)
        return (
            f"{WORD} rules: every department shall keep a register."
            if d and scope.admits(d.tags)
            else ""
        )


class _EchoLLM:
    name = "echo"

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_json(self, *, prompt_id: str, system: str, user: str, schema: Any) -> Any:
        self.prompts.append(user)
        return {"statements": []}


def test_a_cloud_only_order_is_quoted_from_its_passages_within_scope(client: TestClient) -> None:
    from tests.unit.test_sandbox_api import USERS, _h

    run = APP.state.assist_runtime()
    keep, keep_llm = run.cloud, run.llm
    texts = _PassageText(
        [
            _cloud_doc("AP-FIN01-GOMS-9001-2024", "FIN01", "UNCLASSIFIED"),
            _cloud_doc("AP-USD01-GOMS-9002-2024", "USD01", "CONFIDENTIAL"),
        ]
    )
    run.cloud = CloudRungs(**{**keep.__dict__, "passages": texts})  # type: ignore[union-attr]
    try:
        from app.auth.policy import scope_for

        conf = _cloud_doc("x", "USD01", "CONFIDENTIAL").tags
        for uid in USERS:
            llm, texts.asked = _EchoLLM(), []
            run.llm = llm
            client.post("/assist/ask", json={"question": f"{WORD} rules"}, headers=_h(uid))
            assert llm.prompts and 'doc="AP-FIN01-GOMS-9001-2024"' in llm.prompts[0]
            assert "register" in llm.prompts[0]  # the passage text, read from the cloud part
            store = run.store_for(APP.state.adapter.officer_context(uid))
            may = scope_for(uid, store, run.policy, run.classification).admits(conf)
            assert ("9002-2024" in llm.prompts[0]) == may
            assert ("AP-USD01-GOMS-9002-2024" in texts.asked) == may  # never even read otherwise
    finally:
        run.cloud, run.llm = keep, keep_llm
