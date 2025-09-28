"""Graph primitives for assembling validated concepts into a hierarchy."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, MutableMapping, Set

from taxonomy.config.policies import HierarchyAssemblyPolicy
from taxonomy.entities.core import Concept
from taxonomy.utils.logging import get_logger

_LOGGER = get_logger(module=__name__)


@dataclass(slots=True)
class EdgeValidationResult:
    """Outcome of an edge validation attempt."""

    parent_id: str
    child_id: str
    valid: bool
    reason: str | None = None


class HierarchyGraph:
    """In-memory representation of a 4-level directed acyclic graph."""

    def __init__(self, policy: HierarchyAssemblyPolicy) -> None:
        self._policy = policy
        self._nodes: Dict[str, Concept] = {}
        self._children: MutableMapping[str, Set[str]] = defaultdict(set)
        self._parents: MutableMapping[str, Set[str]] = defaultdict(set)
        self._levels: MutableMapping[int, Set[str]] = defaultdict(set)

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------
    def __contains__(self, concept_id: str) -> bool:  # pragma: no cover - trivial
        return concept_id in self._nodes

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._nodes)

    @property
    def policy(self) -> HierarchyAssemblyPolicy:
        return self._policy

    def concepts(self) -> Iterator[Concept]:
        for concept in self._nodes.values():
            yield concept

    def get(self, concept_id: str) -> Concept | None:
        return self._nodes.get(concept_id)

    def children_of(self, concept_id: str) -> List[str]:
        return sorted(self._children.get(concept_id, set()))

    def parents_of(self, concept_id: str) -> List[str]:
        return sorted(self._parents.get(concept_id, set()))

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------
    def add_concept(self, concept: Concept) -> None:
        """Insert a concept into the graph enforcing policy invariants."""

        if concept.id in self._nodes:
            raise ValueError(f"concept '{concept.id}' already exists in the hierarchy")
        if len(self._nodes) >= self._policy.max_graph_size:
            raise ValueError(
                f"max_graph_size={self._policy.max_graph_size} exceeded while inserting '{concept.id}'"
            )
        if concept.level < 0 or concept.level > 3:
            raise ValueError(f"concept '{concept.id}' declares invalid level {concept.level}")

        unique_parents = list(dict.fromkeys(concept.parents))
        parent_concepts: List[Concept] = []
        for parent_id in unique_parents:
            parent = self._nodes.get(parent_id)
            if parent is None:
                raise ValueError(
                    f"concept '{concept.id}' references missing parent '{parent_id}'"
                )
            self._validate_edge(parent, concept)
            parent_concepts.append(parent)

        if (
            self._policy.enforce_unique_paths
            and len(unique_parents) > 1
            and concept.id not in set(self._policy.allow_multi_parent_exceptions)
        ):
            raise ValueError(
                f"concept '{concept.id}' violates unique path invariant with parents {unique_parents}"
            )

        concept.validate_hierarchy(parent_concepts)

        self._nodes[concept.id] = concept
        self._levels[concept.level].add(concept.id)

        if not unique_parents:
            self._parents.setdefault(concept.id, set())
        else:
            store = self._parents.setdefault(concept.id, set())
            for parent_id in unique_parents:
                store.add(parent_id)
                self._children[parent_id].add(concept.id)
        self._children.setdefault(concept.id, set())
        _LOGGER.debug("Inserted concept into hierarchy", concept_id=concept.id, level=concept.level)

    def _validate_edge(self, parent: Concept, child: Concept) -> EdgeValidationResult:
        """Validate a potential edge according to policy constraints."""

        if child.level <= parent.level:
            raise ValueError(
                f"edge {parent.id}->{child.id} violates level ordering: {parent.level} !< {child.level}"
            )
        if self._policy.strict_level_enforcement and not self._policy.allow_level_shortcuts:
            if child.level - parent.level != 1:
                raise ValueError(
                    f"edge {parent.id}->{child.id} violates strict level progression"
                )
        if not self._policy.strict_level_enforcement:
            if child.level - parent.level <= 0:
                raise ValueError(
                    f"edge {parent.id}->{child.id} must progress to a deeper level"
                )
        return EdgeValidationResult(parent.id, child.id, True)

    # ------------------------------------------------------------------
    # Analytics & validation helpers
    # ------------------------------------------------------------------
    def check_acyclicity(self) -> List[str]:
        """Return a topological ordering or raise when cycles exist."""

        if not self._policy.enforce_acyclicity:
            return [concept_id for concept_id in self._nodes]

        in_degree = {node: len(self._parents.get(node, set())) for node in self._nodes}
        queue = deque(node for node, degree in in_degree.items() if degree == 0)
        visited: List[str] = []

        while queue:
            node = queue.popleft()
            visited.append(node)
            for child in self._children.get(node, set()):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(visited) != len(self._nodes):
            raise ValueError("hierarchy graph contains a cycle")
        return visited

    def check_unique_paths(self) -> List[str]:
        """Return concept IDs that violate the unique path invariant."""

        if not self._policy.enforce_unique_paths:
            return []

        violations: List[str] = []
        allowed = set(self._policy.allow_multi_parent_exceptions)
        for concept_id, parents in self._parents.items():
            if self._nodes[concept_id].level == 0:
                continue
            if not parents:
                violations.append(concept_id)
                continue
            if len(parents) > 1 and concept_id not in allowed:
                violations.append(concept_id)
        return violations

    def find_orphans(self) -> List[dict]:
        """Identifies nodes that lack valid parents for their level."""

        orphans: List[dict] = []
        for concept in self._nodes.values():
            parents = self._parents.get(concept.id, set())
            if concept.level == 0:
                continue
            if not parents:
                orphans.append(
                    {
                        "concept_id": concept.id,
                        "level": concept.level,
                        "reason": "missing-parent",
                    }
                )
        return orphans

    def statistics(self) -> Dict[str, object]:
        """Return structural statistics for observability and manifests."""

        edge_count = sum(len(children) for children in self._children.values())
        out_degrees = [len(children) for children in self._children.values()]
        in_degrees = [len(parents) for parents in self._parents.values()]
        stats = {
            "node_count": len(self._nodes),
            "edge_count": edge_count,
            "level_counts": {level: len(nodes) for level, nodes in sorted(self._levels.items())},
            "max_out_degree": max(out_degrees, default=0),
            "max_in_degree": max(in_degrees, default=0),
        }
        return stats

    def adjacency(self) -> Dict[str, List[str]]:
        """Return adjacency mapping for export utilities."""

        return {node: sorted(children) for node, children in self._children.items()}


__all__ = ["HierarchyGraph", "EdgeValidationResult"]
