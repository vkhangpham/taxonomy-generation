"""Deterministic concept merge policy implementation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Sequence, Tuple

from taxonomy.config.policies import DeduplicationPolicy
from taxonomy.entities.core import Concept, MergeOp, SupportStats
from taxonomy.pipeline.deduplication.graph import SimilarityGraph
from taxonomy.utils.logging import get_logger


_LOGGER = get_logger(module=__name__)


class ParentCompatibilityError(RuntimeError):
    """Raised when parent compatibility checks fail."""


@dataclass
class MergeOutcome:
    """Represents the result of merging a connected component."""

    winner: Concept
    losers: List[Concept]
    merge_op: MergeOp


class ConceptMerger:
    """Apply deterministic merge policies to sets of similar concepts."""

    def __init__(self, policy: DeduplicationPolicy) -> None:
        self.policy = policy

    def reset(self) -> None:
        """Reset merger state between runs."""
        # Currently stateless, method retained for interface symmetry
        pass

    @staticmethod
    def _sort_key(concept: Concept) -> Tuple[int, int, str, str]:
        inst_count = concept.support.institutions
        label_length = len(concept.canonical_label)
        return (-inst_count, label_length, concept.canonical_label.lower(), concept.id)

    def select_winner(self, concepts: Sequence[Concept]) -> Concept:
        winner = min(concepts, key=self._sort_key)
        _LOGGER.debug("Selected merge winner", concept_id=winner.id)
        return winner

    def _parents_compatible(self, concepts: Sequence[Concept]) -> bool:
        if not self.policy.parent_context_strict or self.policy.cross_parent_merge_allowed:
            return True
        relevant = [concept for concept in concepts if concept.level > 0]
        if len(relevant) <= 1:
            return True
        shared_parents: set[str] | None = None
        for concept in relevant:
            parents = set(concept.parents)
            if not parents:
                return False
            if shared_parents is None:
                shared_parents = parents
            else:
                shared_parents &= parents
            if not shared_parents:
                return False
        return True

    def _aggregate_support(self, winner: Concept, losers: Sequence[Concept]) -> SupportStats:
        aggregate = SupportStats(
            records=winner.support.records,
            institutions=winner.support.institutions,
            count=winner.support.count,
        )
        for concept in losers:
            aggregate.records += concept.support.records
            aggregate.institutions += concept.support.institutions
            aggregate.count += concept.support.count
        return aggregate

    def _merge_aliases(self, winner: Concept, losers: Sequence[Concept]) -> List[str]:
        alias_set = set(winner.aliases)
        for concept in losers:
            alias_set.add(concept.canonical_label)
            alias_set.update(concept.aliases)
        alias_set.discard(winner.canonical_label)
        return sorted(alias_set)

    def _merge_parents(self, winner: Concept, losers: Sequence[Concept]) -> List[str]:
        parents = set(winner.parents)
        for concept in losers:
            parents.update(concept.parents)
        return sorted(parents)

    def _build_evidence(
        self,
        winner: Concept,
        losers: Sequence[Concept],
        graph: SimilarityGraph,
    ) -> dict[str, dict[str, Any]]:
        evidence: dict[str, dict[str, Any]] = {}
        for concept in losers:
            edge = graph.get_edge(winner.id, concept.id)
            if not edge:
                continue
            payload = {
                "score": round(edge.score, 4),
                "threshold": round(edge.threshold, 4),
                "driver": edge.driver,
                "block": edge.block,
                "features": dict(edge.features),
                "weighted": {k: round(v, 4) for k, v in edge.weighted.items()},
            }
            evidence[concept.id] = payload
        return evidence

    def merge(self, concepts: Sequence[Concept], graph: SimilarityGraph) -> MergeOutcome:
        if len(concepts) < 2:
            raise ValueError("merge requires at least two concepts")
        if not self._parents_compatible(concepts):
            component_ids = [concept.id for concept in concepts]
            _LOGGER.warning(
                "Skipping merge due to parent incompatibility",
                component_ids=component_ids,
                policy=self.policy.merge_policy,
            )
            raise ParentCompatibilityError("parent compatibility check failed")
        winner = self.select_winner(concepts)
        losers = [concept for concept in concepts if concept.id != winner.id]

        winner_copy = winner.model_copy(deep=True)
        winner_copy.aliases = self._merge_aliases(winner_copy, losers)
        winner_copy.parents = self._merge_parents(winner_copy, losers)
        winner_copy.support = self._aggregate_support(winner_copy, losers)

        merge_op = MergeOp(
            winners=[winner_copy.id],
            losers=[concept.id for concept in losers],
            rule=self.policy.merge_policy,
            evidence=self._build_evidence(winner_copy, losers, graph) or None,
        )

        _LOGGER.debug(
            "Merged component",
            winner=winner_copy.id,
            losers=[concept.id for concept in losers],
            alias_count=len(winner_copy.aliases),
        )

        return MergeOutcome(winner=winner_copy, losers=losers, merge_op=merge_op)


__all__ = ["ConceptMerger", "MergeOutcome", "ParentCompatibilityError"]
