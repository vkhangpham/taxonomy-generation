"""In-memory similarity graph and union-find utilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from taxonomy.pipeline.deduplication.similarity import SimilarityDecision


@dataclass
class EdgeMetadata:
    """Metadata captured for an edge in the similarity graph."""

    score: float
    threshold: float
    driver: str
    block: str
    features: Dict[str, float]
    weighted: Dict[str, float]


class UnionFind:
    """Disjoint-set data structure with path compression."""

    def __init__(self) -> None:
        self._parent: Dict[str, str] = {}
        self._rank: Dict[str, int] = {}

    def add(self, item: str) -> None:
        if item not in self._parent:
            self._parent[item] = item
            self._rank[item] = 0

    def find(self, item: str) -> str:
        parent = self._parent.get(item)
        if parent is None:
            self.add(item)
            return item
        if parent != item:
            self._parent[item] = self.find(parent)
        return self._parent[item]

    def union(self, a: str, b: str) -> None:
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a == root_b:
            return
        rank_a = self._rank[root_a]
        rank_b = self._rank[root_b]
        if rank_a < rank_b:
            self._parent[root_a] = root_b
        elif rank_a > rank_b:
            self._parent[root_b] = root_a
        else:
            self._parent[root_b] = root_a
            self._rank[root_a] += 1

    def components(self) -> Dict[str, Set[str]]:
        groups: Dict[str, Set[str]] = {}
        for item in self._parent:
            root = self.find(item)
            groups.setdefault(root, set()).add(item)
        return groups


class SimilarityGraph:
    """Graph representation of concept similarities."""

    def __init__(self) -> None:
        self.nodes: Set[str] = set()
        self.edges: Dict[Tuple[str, str], EdgeMetadata] = {}
        self.adjacency: Dict[str, Set[str]] = {}
        self._uf = UnionFind()

    def add_node(self, node_id: str) -> None:
        if node_id in self.nodes:
            return
        self.nodes.add(node_id)
        self.adjacency.setdefault(node_id, set())
        self._uf.add(node_id)

    def add_edge(
        self,
        node_a: str,
        node_b: str,
        decision: SimilarityDecision,
        *,
        block: str,
    ) -> None:
        if node_a == node_b:
            return
        ordered = tuple(sorted((node_a, node_b)))
        self.add_node(node_a)
        self.add_node(node_b)
        metadata = EdgeMetadata(
            score=decision.score,
            threshold=decision.threshold,
            driver=decision.driver,
            block=block,
            features={
                "jaro_winkler": decision.features.jaro_winkler,
                "token_jaccard": decision.features.token_jaccard,
                "abbrev_score": decision.features.abbrev_score,
            },
            weighted=dict(decision.features.weighted),
        )
        self.edges[ordered] = metadata
        self.adjacency[node_a].add(node_b)
        self.adjacency[node_b].add(node_a)
        self._uf.union(node_a, node_b)

    def get_edge(self, node_a: str, node_b: str) -> Optional[EdgeMetadata]:
        ordered = tuple(sorted((node_a, node_b)))
        return self.edges.get(ordered)

    def connected_components(self) -> List[Set[str]]:
        groups = self._uf.components()
        components = [group for group in groups.values() if group]
        components.sort(key=lambda group: (len(group), sorted(group)))
        return components

    def stats(self) -> Dict[str, int]:
        if not self.nodes:
            return {"nodes": 0, "edges": 0, "components": 0, "largest_component": 0}
        components = self.connected_components()
        largest = max((len(component) for component in components), default=1)
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "components": len(components),
            "largest_component": largest,
        }


__all__ = ["SimilarityGraph", "UnionFind", "EdgeMetadata"]
