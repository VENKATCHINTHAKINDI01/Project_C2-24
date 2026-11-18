"""Make a graph store hold exactly what the build produced (ADR-0055).

The graph build job is the ONLY writer of the cloud graph tables (Cloud SQL `graph_nodes` /
`graph_edges`, Spanner Graph): the API reads them, and what it learns at run time (e-Office
papers, review confirmations) stays in its own in-memory graph layered on top. So each load makes
the store equal to the build: links and nodes the build no longer produces are deleted, the rest
upserted. Before, the load only added and updated, and links an earlier build produced but this one
does not (e.g. an unconfirmed SUPERSEDES candidate a better reading replaced) stayed live.

Guards, because a deletion cannot be undone:
- an empty build never syncs (a failed parse must not empty the graph);
- deleting more than `max_delete_share` of the links or nodes now held is refused unless allowed;
- a dry run reports exactly what would be added, updated and deleted, and changes nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from app.graph.repository import GraphEdge, GraphNode

EdgeKey = tuple[str, str, str]  # (source, kind, target)


class SyncRefusedError(RuntimeError):
    """The sync would delete too much, or the build is empty: nothing was changed."""


@dataclass(frozen=True)
class SyncPlan:
    nodes_held: int
    edges_held: int
    add_nodes: frozenset[str] = frozenset()
    delete_nodes: frozenset[str] = frozenset()
    add_edges: frozenset[EdgeKey] = frozenset()
    update_edges: frozenset[EdgeKey] = frozenset()  # same link, `confirmed` changed
    delete_edges: frozenset[EdgeKey] = frozenset()
    kinds_deleted: Mapping[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        kinds = ", ".join(f"{k} {n}" for k, n in sorted(self.kinds_deleted.items())) or "none"
        return (
            f"held {self.nodes_held} nodes / {self.edges_held} links; "
            f"add {len(self.add_nodes)} nodes / {len(self.add_edges)} links; "
            f"update {len(self.update_edges)} links; "
            f"delete {len(self.delete_nodes)} nodes / {len(self.delete_edges)} links "
            f"(by kind: {kinds})"
        )


def plan(
    held_nodes: Iterable[str],
    held_edges: Mapping[EdgeKey, bool],
    nodes: Iterable[GraphNode],
    edges: Iterable[GraphEdge],
) -> SyncPlan:
    """What must change for the store to equal the build. `held_edges`: key → confirmed."""
    held_n = set(held_nodes)
    new_n = {n.canonical_id for n in nodes}
    new_e = {(e.source, e.kind.value, e.target): e.confirmed for e in edges}
    gone = frozenset(set(held_edges) - set(new_e))
    kinds: dict[str, int] = {}
    for _, kind, _ in gone:
        kinds[kind] = kinds.get(kind, 0) + 1
    return SyncPlan(
        nodes_held=len(held_n),
        edges_held=len(held_edges),
        add_nodes=frozenset(new_n - held_n),
        delete_nodes=frozenset(held_n - new_n),
        add_edges=frozenset(set(new_e) - set(held_edges)),
        update_edges=frozenset(
            k for k, c in new_e.items() if k in held_edges and held_edges[k] != c
        ),
        delete_edges=gone,
        kinds_deleted=kinds,
    )


def check(
    p: SyncPlan, built_nodes: int, *, max_delete_share: float, allow_large_delete: bool
) -> None:
    """Refuse a sync that would empty the store or delete more than the allowed share."""
    if built_nodes == 0:
        raise SyncRefusedError("the build produced no nodes: nothing synced (a failed run?)")
    if allow_large_delete:
        return
    for what, gone, held in (
        ("links", len(p.delete_edges), p.edges_held),
        ("nodes", len(p.delete_nodes), p.nodes_held),
    ):
        if held and gone / held > max_delete_share:
            raise SyncRefusedError(
                f"would delete {gone} of {held} {what} ({gone / held:.0%} > "
                f"{max_delete_share:.0%}): nothing synced. Check the build; to proceed anyway, "
                "pass --allow-large-delete"
            )
