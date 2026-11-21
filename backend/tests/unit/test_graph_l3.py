"""GraphRepository + L3 expansion: scope-constrained walks, no path leakage (plan §3.2, §5.2).

The graph is loaded from the mock corpus relations (test fixture only).
"""

from __future__ import annotations

from collections import deque

import pytest

from app.auth.models import DocumentAccessTags
from app.auth.policy import compute_scope
from app.auth.store import AccessTuple, Relation
from app.config import REPO_ROOT, load_runtime_config
from app.graph.repository import (
    Direction,
    EdgeKind,
    GraphEdge,
    GraphError,
    GraphNode,
    GraphRepository,
    InMemoryGraphRepository,
)
from app.retrieval.graph_expansion import (
    CITATION,
    HIGH_LEGAL_FORCE,
    SUPERSESSION,
    NotCalibratedError,
    ScopedChunkMatch,
    configured_max_hops,
    consolidate_evidence,
    expand,
    format_truncation_disclaimer,
    select_relationships_by_intent,
)
from tests.unit.mock_access import CLASSES, MATRIX, POLICY, USER_IDS, doc_tags, new_store, rows

TAGS = doc_tags()
CID = {r["id"]: r["canonical_id"] for r in rows("documents_index.csv")}
DOC = {v: k for k, v in CID.items()}
ALL_KINDS = frozenset(EdgeKind)


def _graph() -> InMemoryGraphRepository:
    g = InMemoryGraphRepository()
    for did, cid in CID.items():
        g.upsert_node(GraphNode(canonical_id=cid, tags=TAGS[did]))
    for r in rows("ground_truth/relations.csv"):
        if r["to_id"]:  # unresolved citations have no target node
            g.upsert_edge(
                GraphEdge(
                    source=r["from_canonical"],
                    kind=EdgeKind(r["relation"]),
                    target=r["to_canonical_or_raw"],
                    confirmed=r["explicit_in_text"] == "True",
                )
            )
    return g


GRAPH = _graph()


def _l3(uid: str, seeds: list[str], **kw: object):  # type: ignore[no-untyped-def]
    args: dict[str, object] = {
        "kinds": ALL_KINDS,
        "direction": Direction.BOTH,
        "max_hops": 10,
        "store": new_store(),
        "policy": POLICY,
        "classification": CLASSES,
    }
    args.update(kw)
    return expand(uid, [CID[s] for s in seeds], graph=GRAPH, **args)  # type: ignore[arg-type]


def _ids(exp) -> set[str]:  # type: ignore[no-untyped-def]
    return {DOC[h.canonical_id] for h in exp.hits}


def test_in_memory_repository_satisfies_protocol() -> None:
    assert isinstance(GRAPH, GraphRepository)


def test_supersession_chain_walk() -> None:
    exp = _l3("U01", ["D01"], kinds=frozenset({EdgeKind.SUPERSEDES}), direction=Direction.IN)
    assert [(DOC[h.canonical_id], h.hops) for h in exp.hits] == [("D03", 1), ("D04", 2)]
    assert exp.hits[-1].path == (CID["D01"], CID["D03"], CID["D04"])


def test_incoming_citations_never_include_documents_outside_scope() -> None:
    """Who cites G.O.Ms.31/2025? U01 must not learn about the confidential rejection D20."""
    u01 = _l3("U01", ["D04"], kinds=CITATION, direction=Direction.IN, max_hops=1)
    u02 = _l3("U02", ["D04"], kinds=CITATION, direction=Direction.IN, max_hops=1)
    assert _ids(u01) == {"D19"}
    assert _ids(u02) == {"D19", "D20"}


def test_walk_never_passes_through_a_forbidden_node() -> None:
    """D20 → D21 (Vigilance) → D22: U02 sees D20 but not D21/D22, so the walk stops at D20."""
    exp = _l3("U02", ["D20"], max_hops=5)
    assert {"D21", "D22", "D23"}.isdisjoint(_ids(exp))


def test_allowed_node_reachable_only_through_forbidden_one_stays_hidden() -> None:
    g = InMemoryGraphRepository()
    pub = DocumentAccessTags(doc_id="A", department="USD01", classification="UNCLASSIFIED")
    sec = DocumentAccessTags(doc_id="S", department="USD01", section="VIG", classification="SECRET")
    g.upsert_node(GraphNode(canonical_id="A", tags=pub))
    g.upsert_node(GraphNode(canonical_id="S", tags=sec))
    g.upsert_node(GraphNode(canonical_id="B", tags=pub.model_copy(update={"doc_id": "B"})))
    g.upsert_edge(GraphEdge(source="A", kind=EdgeKind.CITES, target="S"))
    g.upsert_edge(GraphEdge(source="S", kind=EdgeKind.CITES, target="B"))
    store = new_store()
    scope = compute_scope(store.principal("U01"), POLICY, CLASSES)
    hits = g.walk(["A"], scope, kinds=ALL_KINDS, direction=Direction.OUT, max_hops=5)
    assert hits == []  # B is public, but the only path to it runs through S
    top = compute_scope(store.principal("U06"), POLICY, CLASSES)
    assert [
        h.canonical_id
        for h in g.walk(["A"], top, kinds=ALL_KINDS, direction=Direction.OUT, max_hops=5)
    ] == ["S", "B"]


def _reference_bfs(uid: str, seed: str, hops: int) -> set[str]:
    """Independent check: BFS over the subgraph induced by the officer's allowed documents."""
    allowed = {d for d in CID if MATRIX[(d, uid)]}
    adj: dict[str, set[str]] = {}
    for r in rows("ground_truth/relations.csv"):
        a, b = r["from_id"], r["to_id"]
        if b and r["explicit_in_text"] == "True" and a in allowed and b in allowed:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    seen, q = {seed}, deque([(seed, 0)])
    while q:
        cur, d = q.popleft()
        if d == hops:
            continue
        for n in adj.get(cur, ()):
            if n not in seen:
                seen.add(n)
                q.append((n, d + 1))
    return seen - {seed}


@pytest.mark.parametrize("uid", USER_IDS)
def test_leakage_matrix_every_authorised_seed(uid: str) -> None:
    """For every officer and every seed they may see: hits are exactly the reference BFS over the
    authorised subgraph — nothing forbidden, nothing reached through a forbidden node."""
    store = new_store()
    for seed in (d for d in CID if MATRIX[(d, uid)]):
        exp = _l3(uid, [seed], store=store, max_hops=3)
        got = _ids(exp)
        assert all(MATRIX[(d, uid)] for d in got)
        assert got == _reference_bfs(uid, seed, 3), (uid, seed)


FORBIDDEN_PAIRS = sorted((u, d) for (d, u), ok in MATRIX.items() if not ok)


@pytest.mark.parametrize(("uid", "did"), FORBIDDEN_PAIRS)
def test_forbidden_seed_is_ignored(uid: str, did: str) -> None:
    exp = _l3(uid, [did])
    assert exp.seeds == () and exp.hits == ()


def test_unconfirmed_edges_need_explicit_opt_in() -> None:
    """D13 CONFLICTS_WITH D14 is inferred (not explicit): only shown for review."""
    kinds = frozenset({EdgeKind.CONFLICTS_WITH})
    assert _l3("U03", ["D13"], kinds=kinds, max_hops=1).hits == ()
    review = _l3("U03", ["D13"], kinds=kinds, max_hops=1, include_unconfirmed=True)
    assert _ids(review) == {"D14"}


def test_max_hops_and_revocation() -> None:
    one = _l3("U01", ["D01"], kinds=SUPERSESSION, direction=Direction.IN, max_hops=1)
    assert _ids(one) == {"D02", "D03"}  # 71/2019 amends, 88/2022 supersedes
    store = new_store()
    assert "D20" in _ids(_l3("U04", ["D04"], kinds=CITATION, direction=Direction.IN, store=store))
    store.delete(
        [
            AccessTuple(
                subject="user:U04",
                relation=Relation.ASSIGNED,
                object="file:USD01-12/58/2025-ESTT.I",
            )
        ]
    )
    assert "D20" not in _ids(
        _l3("U04", ["D04"], kinds=CITATION, direction=Direction.IN, store=store)
    )
    with pytest.raises(ValueError):
        _l3("U01", ["D01"], max_hops=0)


def test_unknown_user_gets_no_expansion() -> None:
    exp = _l3("U99", ["D01"])
    assert exp.scope_signature is None and exp.hits == ()


def test_max_hops_is_not_guessed_while_uncalibrated() -> None:
    runtime = load_runtime_config(REPO_ROOT / "backend" / "config" / "runtime.yaml")
    with pytest.raises(NotCalibratedError):
        configured_max_hops(runtime)


def test_edges_to_unknown_nodes_are_rejected() -> None:
    g = InMemoryGraphRepository()
    with pytest.raises(GraphError):
        g.upsert_edge(GraphEdge(source="X", kind=EdgeKind.CITES, target="Y"))


def test_graph_traversal_bounded_by_max_nodes() -> None:
    """Fault 3: operational limit on nodes prevents unbounded fan-out and reports truncation."""
    # Seed D01 has multiple in-edges (D02, D03)
    full = _l3("U01", ["D01"], kinds=SUPERSESSION, direction=Direction.IN, max_hops=1)
    assert len(full.hits) == 2
    assert not full.truncated
    assert full.truncation_reason is None

    # Bounded to 1 node:
    bounded = _l3(
        "U01", ["D01"], kinds=SUPERSESSION, direction=Direction.IN, max_hops=1, max_nodes=1
    )
    assert len(bounded.hits) == 1
    assert bounded.truncated is True
    assert bounded.truncation_reason == "max_nodes_exceeded (1)"


def test_graph_traversal_bounded_by_max_edges() -> None:
    """Fault 3: operational limit on edges traversed reports non-silent truncation."""
    bounded = _l3(
        "U01", ["D01"], kinds=SUPERSESSION, direction=Direction.IN, max_hops=2, max_edges=1
    )
    assert bounded.truncated is True
    assert bounded.truncation_reason == "max_edges_exceeded (1)"


def test_intent_based_relationship_selector() -> None:
    """Step 2 of Graph-Guided Hybrid Retrieval: restricts to statutory relations."""
    all_kinds = frozenset(EdgeKind)
    filtered = select_relationships_by_intent(all_kinds, is_conflict_or_amendment=True)
    assert filtered == HIGH_LEGAL_FORCE
    assert EdgeKind.AMENDS in filtered
    assert EdgeKind.SUPERSEDES in filtered
    assert EdgeKind.CITES not in filtered
    assert EdgeKind.REFERENCES not in filtered

    # Informational / non-conflict retains all kinds:
    non_conflict = select_relationships_by_intent(all_kinds, is_conflict_or_amendment=False)
    assert non_conflict == all_kinds


def test_evidence_consolidator_preserves_structural_force() -> None:
    """Step 4 of Graph-Guided Hybrid Retrieval: semantic relevance never overrides hierarchy."""
    exp = _l3("U01", ["D01"], kinds=SUPERSESSION, direction=Direction.IN, max_hops=1)
    # Suppose hybrid search only matched D02 with high score, D03 was below semantic cutoff:
    scoped = [ScopedChunkMatch(canonical_id=CID["D02"], score=0.89, matched_clause="Section 4.1")]
    ev = consolidate_evidence(
        exp.hits, scoped, truncated=exp.truncated, truncation_reason=exp.truncation_reason
    )

    # Both D02 and D03 must have structural anchors with legal_force="HIGH"
    anchor_cids = {a.canonical_id for a in ev.anchors}
    assert CID["D02"] in anchor_cids
    assert CID["D03"] in anchor_cids
    for a in ev.anchors:
        assert a.legal_force == "HIGH"


def test_non_silent_truncation_disclaimer() -> None:
    """Non-silent truncation guarantee: assistant disclaimer is generated when truncated."""
    disc = format_truncation_disclaimer(True, "max_nodes_exceeded (50)", 50)
    assert disc is not None
    assert "Archival Traversal Limit" in disc
    assert "50 related records" in disc
    assert "institutional archives" in disc

    assert format_truncation_disclaimer(False, None, 10) is None
