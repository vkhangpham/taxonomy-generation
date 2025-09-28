"""Deduplication processor orchestrating blocking, similarity, and merging."""

from __future__ import annotations

import itertools
import threading
from time import perf_counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence

from taxonomy.config.policies import DeduplicationPolicy
from taxonomy.entities.core import Concept, MergeOp
from taxonomy.pipeline.deduplication.blocking import (
    AcronymBlocker,
    BlockingOutput,
    CompositeBlocker,
    PhoneticBlocker,
    PrefixBlocker,
)
from taxonomy.pipeline.deduplication.graph import SimilarityGraph
from taxonomy.pipeline.deduplication.merger import (
    ConceptMerger,
    MergeOutcome,
    ParentCompatibilityError,
)
from taxonomy.pipeline.deduplication.similarity import SimilarityScorer
from taxonomy.utils import jaro_winkler_similarity
from taxonomy.utils.logging import get_logger


_LOGGER = get_logger(module=__name__)


@dataclass
class DeduplicationResult:
    """Aggregate result from deduplication processing."""

    concepts: List[Concept]
    merge_ops: List[MergeOp]
    stats: Dict[str, object]
    samples: List[Dict[str, object]] = field(default_factory=list)


class DeduplicationProcessor:
    """Coordinator for the deduplication pipeline.

    The processor retains only the last occurrence when duplicate concept IDs are
    provided while logging the conflict and exposing aggregate duplicate metrics
    with the result. Calls to :meth:`process` are serialized with an internal
    threading lock so a single processor instance can be reused safely across
    threads without additional coordination.
    """

    def __init__(self, policy: DeduplicationPolicy) -> None:
        self.policy = policy
        strategies = [PrefixBlocker(policy)]
        if policy.phonetic_enabled:
            strategies.append(PhoneticBlocker(policy))
        if policy.acronym_blocking_enabled:
            strategies.append(AcronymBlocker(policy))
        self.blocker = CompositeBlocker(strategies, policy)
        self.scorer = SimilarityScorer(policy)
        self.graph = SimilarityGraph()
        self.merger = ConceptMerger(policy)
        self._lock = threading.Lock()

    def _reset_run_state(self) -> None:
        """Clear per-run state so repeated calls start fresh."""
        self.blocker.reset()
        self.scorer.reset()
        self.merger.reset()
        _LOGGER.debug("Resetting SimilarityGraph for new deduplication run")
        self.graph.reset()

    def _pairwise(self, concepts: Sequence[Concept]) -> Iterable[tuple[Concept, Concept]]:
        return itertools.combinations(concepts, 2)

    def _build_blocks(self, concepts: Sequence[Concept]) -> BlockingOutput:
        output = self.blocker.build_blocks(concepts)
        _LOGGER.debug(
            "Constructed blocks",
            total_blocks=output.metrics.total_blocks,
            max_block_size=output.metrics.max_block_size,
            strategies=output.metrics.strategy_counts,
        )
        return output

    def _compare_block(self, block_id: str, members: Sequence[Concept], stats: Dict[str, object]) -> None:
        comparisons = 0
        skipped_parent = 0
        skipped_threshold = 0
        probe_filtered = 0
        is_phonetic_block = block_id.startswith("phonetic:")
        probe_threshold = self.policy.phonetic_probe_threshold if is_phonetic_block else None
        for concept_a, concept_b in self._pairwise(members):
            if comparisons >= self.policy.max_comparisons_per_block:
                _LOGGER.debug(
                    "Comparison limit reached for block",
                    block=block_id,
                    limit=self.policy.max_comparisons_per_block,
                )
                break
            comparisons += 1
            if not self.scorer.parent_compatible(concept_a, concept_b):
                skipped_parent += 1
                continue
            if probe_threshold is not None and probe_threshold > 0.0:
                probe_score = min(
                    jaro_winkler_similarity(
                        concept_a.canonical_label, concept_b.canonical_label
                    ),
                    1.0,
                )
                if probe_score < probe_threshold:
                    probe_filtered += 1
                    continue
            decision = self.scorer.score_pair(concept_a, concept_b)
            stats["pairs_compared"] = stats.get("pairs_compared", 0) + 1
            if decision.passed:
                self.graph.add_edge(concept_a.id, concept_b.id, decision, block=block_id)
                stats["edges_kept"] = stats.get("edges_kept", 0) + 1
            else:
                skipped_threshold += 1
        stats.setdefault("block_comparisons", {})[block_id] = comparisons
        stats.setdefault("blocked_parent_conflicts", 0)
        stats.setdefault("below_threshold", 0)
        stats.setdefault("phonetic_probe_filtered", 0)
        stats["blocked_parent_conflicts"] += skipped_parent
        stats["below_threshold"] += skipped_threshold
        stats["phonetic_probe_filtered"] += probe_filtered

    def _merge_components(
        self,
        components: List[set[str]],
        concept_lookup: Dict[str, Concept],
        stats: Dict[str, object],
    ) -> tuple[List[Concept], List[MergeOp], List[Dict[str, object]]]:
        surviving: Dict[str, Concept] = {concept.id: concept for concept in concept_lookup.values()}
        merge_ops: List[MergeOp] = []
        samples: List[Dict[str, object]] = []

        # process larger components first for determinism and ease of debugging
        components.sort(key=lambda component: (-len(component), sorted(component)))

        for component in components:
            if len(component) < 2:
                continue
            concepts = [concept_lookup[cid] for cid in sorted(component)]
            try:
                outcome: MergeOutcome = self.merger.merge(concepts, self.graph)
            except ParentCompatibilityError:
                stats.setdefault("merges_skipped_parent_policy", 0)
                stats["merges_skipped_parent_policy"] += 1
                continue
            surviving[outcome.winner.id] = outcome.winner
            for loser in outcome.losers:
                surviving.pop(loser.id, None)
            merge_ops.append(outcome.merge_op)
            if len(samples) < self.policy.sample_merge_count:
                samples.append(
                    {
                        "winner": outcome.winner.id,
                        "losers": [concept.id for concept in outcome.losers],
                        "evidence": outcome.merge_op.evidence,
                    }
                )

        stats["merges"] = len(merge_ops)
        stats["post_merge_concepts"] = len(surviving)
        deduped = sorted(surviving.values(), key=lambda concept: concept.id)
        return deduped, merge_ops, samples

    def process(self, concepts: Iterable[Concept]) -> DeduplicationResult:
        """Run the deduplication pipeline for the provided concepts.

        Duplicate concept IDs are detected before processing. The processor keeps
        the last occurrence to match downstream expectations and logs the
        conflict so the caller can address the source data. Metrics for duplicate
        detection, total pair comparisons, and elapsed time are returned in the
        result stats.
        """

        with self._lock:
            start_time = perf_counter()
            concept_lookup: Dict[str, Concept] = {}
            occurrence_counts: Dict[str, int] = {}
            total_concepts = 0

            for concept in concepts:
                total_concepts += 1
                concept_lookup[concept.id] = concept
                occurrence_counts[concept.id] = occurrence_counts.get(concept.id, 0) + 1

            _LOGGER.info("Deduplication run started", total_concepts=total_concepts)

            self._reset_run_state()
            duplicate_ids = {cid: count for cid, count in occurrence_counts.items() if count > 1}
            duplicates_detected = sum(count - 1 for count in duplicate_ids.values())
            unique_concepts = list(concept_lookup.values())
            unique_count = len(unique_concepts)

            if duplicate_ids:
                sample = list(duplicate_ids.items())[:5]
                _LOGGER.warning(
                    "Duplicate concept ids detected; keeping last occurrence",
                    total_duplicates=duplicates_detected,
                    duplicate_id_count=len(duplicate_ids),
                    sample=sample,
                )

            for concept_id in concept_lookup:
                self.graph.add_node(concept_id)

            blocking_output = self._build_blocks(unique_concepts)
            stats: Dict[str, object] = {
                "input": {
                    "total_concepts": total_concepts,
                    "unique_concepts": unique_count,
                    "duplicate_id_count": len(duplicate_ids),
                    "duplicates_discarded": duplicates_detected,
                },
                "duplicates_detected": duplicates_detected,
                "blocking": {
                    "strategy_counts": blocking_output.metrics.strategy_counts,
                    "total_blocks": blocking_output.metrics.total_blocks,
                    "average_block_size": blocking_output.metrics.average_block_size,
                    "max_block_size": blocking_output.metrics.max_block_size,
                },
            }

            for block_id, members in blocking_output.blocks.items():
                if len(members) < 2:
                    continue
                self._compare_block(block_id, members, stats)

            components = [
                component
                for component in self.graph.connected_components()
                if len(component) > 1
            ]
            stats["graph"] = self.graph.stats()
            stats["components_with_edges"] = len(components)

            deduped_concepts, merge_ops, samples = self._merge_components(
                components,
                concept_lookup,
                stats,
            )

            total_pairs = stats.get("pairs_compared", 0)
            stats["total_pairs_compared"] = total_pairs
            elapsed_seconds = perf_counter() - start_time
            stats["timing"] = {"elapsed_seconds": elapsed_seconds}

            result = DeduplicationResult(
                concepts=deduped_concepts,
                merge_ops=merge_ops,
                stats=stats,
                samples=samples,
            )
            _LOGGER.info(
                "Deduplication run finished",
                total_concepts=total_concepts,
                unique_concepts=unique_count,
                duplicate_id_count=len(duplicate_ids),
                duplicates_discarded=duplicates_detected,
                total_blocks=blocking_output.metrics.total_blocks,
                merges=len(merge_ops),
                remaining=len(deduped_concepts),
                total_pairs_compared=total_pairs,
                elapsed_seconds=elapsed_seconds,
            )
            return result

__all__ = ["DeduplicationProcessor", "DeduplicationResult"]
