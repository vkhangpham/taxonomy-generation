"""Pipeline orchestration for taxonomy disambiguation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, MutableMapping, Sequence

from ...config.policies import DisambiguationPolicy
from ...entities.core import Concept, Rationale, SplitOp, SourceRecord
from ...utils.context_features import ContextWindow, extract_context_windows
from .detector import AmbiguityCandidate, AmbiguityDetector
from .llm import LLMDisambiguationResult, LLMSenseDefinition, LLMDisambiguator
from .splitter import ConceptSplitter, SplitDecision


ContextSource = Sequence[SourceRecord] | Sequence[ContextWindow]
ContextIndex = Mapping[str, ContextSource]
CachedContexts = MutableMapping[str, List[ContextWindow]]


@dataclass
class DisambiguationOutcome:
    """Aggregate result of processing a batch of concepts."""

    concepts: List[Concept]
    split_ops: List[SplitOp]
    deferred: List[str]
    stats: Dict[str, int]


class ContextAnalyzer:
    """Generate and cache context windows used during disambiguation."""

    def __init__(self, policy: DisambiguationPolicy) -> None:
        self._policy = policy
        self._cache: CachedContexts = {}

    def obtain_contexts(
        self,
        concept: Concept,
        sources: ContextSource | None,
    ) -> List[ContextWindow]:
        if concept.id in self._cache:
            return self._limit(self._cache[concept.id])

        contexts: List[ContextWindow] = []
        if sources:
            first = next(iter(sources), None)
            if isinstance(first, ContextWindow):
                contexts = list(sources)  # type: ignore[arg-type]
            else:
                contexts = extract_context_windows(
                    concept,
                    sources,  # type: ignore[arg-type]
                    window_size=self._policy.context_window_size,
                )
        self._cache[concept.id] = self._limit(contexts)
        return self._cache[concept.id]

    def group_contexts(
        self,
        concept_group: Sequence[Concept],
        context_index: ContextIndex | None,
    ) -> Dict[str, List[ContextWindow]]:
        grouped: Dict[str, List[ContextWindow]] = {}
        for concept in concept_group:
            sources = context_index.get(concept.id) if context_index else None
            grouped[concept.id] = self.obtain_contexts(concept, sources)
        return grouped

    def _limit(self, contexts: Sequence[ContextWindow]) -> List[ContextWindow]:
        if not contexts:
            return []
        limit = self._policy.max_contexts_per_parent
        if limit <= 0:
            return list(contexts)
        return list(contexts[:limit])

    def reset(self) -> None:
        self._cache.clear()


class DisambiguationProcessor:
    """Coordinate ambiguity detection, LLM decisions, and concept splitting."""

    def __init__(
        self,
        policy: DisambiguationPolicy,
        detector: AmbiguityDetector | None = None,
        context_analyzer: ContextAnalyzer | None = None,
        disambiguator: LLMDisambiguator | None = None,
        splitter: ConceptSplitter | None = None,
    ) -> None:
        # The policy requires defer_ambiguous_threshold <= min_evidence_strength to keep decision boundaries consistent.
        if policy.defer_ambiguous_threshold > policy.min_evidence_strength:
            raise ValueError(
                "DisambiguationPolicy.defer_ambiguous_threshold"
                f" ({policy.defer_ambiguous_threshold:.2f}) must be <= "
                "DisambiguationPolicy.min_evidence_strength"
                f" ({policy.min_evidence_strength:.2f}) to maintain consistent decision boundaries."
            )
        self._policy = policy
        self._detector = detector or AmbiguityDetector(policy)
        self._context_analyzer = context_analyzer or ContextAnalyzer(policy)
        self._disambiguator = disambiguator or LLMDisambiguator(policy)
        self._splitter = splitter or ConceptSplitter(policy)
        self.stats: Dict[str, int] = defaultdict(int)

    def process(
        self,
        concepts: Iterable[Concept],
        context_index: ContextIndex | None = None,
    ) -> DisambiguationOutcome:
        self._context_analyzer.reset()
        concept_copies = [concept.model_copy(deep=True) for concept in concepts]
        context_indexed_sources = {
            concept.id: self._context_analyzer.obtain_contexts(
                concept,
                context_index.get(concept.id) if context_index else None,
            )
            for concept in concept_copies
        }

        candidates = self._detector.detect_collisions(
            concept_copies, context_indexed_sources
        )
        self.stats.update(self._detector.stats)

        concept_map: Dict[str, Concept] = {concept.id: concept for concept in concept_copies}
        ordered_ids: List[str] = [concept.id for concept in concept_copies]
        split_ops: List[SplitOp] = []
        deferred: List[str] = []

        for candidate in candidates:
            deferred_ids = self._process_candidate(
                candidate,
                concept_map,
                ordered_ids,
                split_ops,
                context_index,
            )
            deferred.extend(deferred_ids)

        rehydrated = [concept_map[concept_id] for concept_id in ordered_ids]
        return DisambiguationOutcome(rehydrated, split_ops, deferred, dict(self.stats))

    def _process_candidate(
        self,
        candidate: AmbiguityCandidate,
        concept_map: Dict[str, Concept],
        ordered_ids: List[str],
        split_ops: List[SplitOp],
        context_index: ContextIndex | None,
    ) -> List[str]:
        candidate_deferred: List[str] = []
        self.stats["collisions_processed"] += 1
        group_contexts = self._context_analyzer.group_contexts(
            candidate.concepts, context_index
        )

        llm_result = self._disambiguator.check_separability(
            candidate.label,
            candidate.concepts[0].level,
            candidate.concepts,
            group_contexts,
        )
        split_confidence = self._disambiguator.assess_split_confidence(
            llm_result.confidence,
            candidate.context_divergence,
        )

        should_split, failure_reason = self._should_split(
            candidate, llm_result, split_confidence
        )
        if not should_split:
            self._mark_deferred_for_concepts(
                failure_reason or llm_result.reason,
                candidate.concepts,
                concept_map,
                candidate_deferred,
            )
            if candidate_deferred:
                self.stats["deferred"] += 1
            return candidate_deferred

        parent_mappings = self._disambiguator.map_senses_to_parents(
            llm_result.senses, candidate.concepts
        )
        if not self._policy.allow_multi_parent_exceptions:
            seen_lineages: dict[frozenset[str], str] = {}
            conflict_labels: tuple[str, str] | None = None
            conflict_parents: frozenset[str] | None = None
            for sense in llm_result.senses:
                parents = parent_mappings.get(sense.label, [])
                lineage_key = frozenset(parents)
                existing_label = seen_lineages.get(lineage_key)
                if existing_label is not None:
                    conflict_labels = (existing_label, sense.label)
                    conflict_parents = lineage_key
                    break
                seen_lineages[lineage_key] = sense.label
            if conflict_labels is not None:
                parent_list = sorted(conflict_parents) if conflict_parents else []
                parents_display = ", ".join(parent_list) if parent_list else "<root>"
                reason = (
                    "Deferred split: multiple senses share parent lineage "
                    f"{parents_display} and policy forbids multi-parent "
                    f"exceptions ({conflict_labels[0]} vs {conflict_labels[1]})."
                )
                self._mark_deferred_for_concepts(
                    reason, candidate.concepts, concept_map, candidate_deferred
                )
                if candidate_deferred:
                    self.stats["deferred"] += 1
                return candidate_deferred

        evidence_mapping = {
            sense.label: sense.evidence_indices for sense in llm_result.senses
        }
        split_decision = self._splitter.split(
            candidate.concepts[0],
            candidate.concepts,
            llm_result.senses,
            parent_mappings,
            evidence_mapping,
            split_confidence,
            group_contexts,
        )

        removed_ids = {concept.id for concept in candidate.concepts}
        for concept_id in removed_ids:
            concept_map.pop(concept_id, None)
        ordered_ids[:] = [cid for cid in ordered_ids if cid not in removed_ids]

        for new_concept in split_decision.new_concepts:
            concept_map[new_concept.id] = new_concept
            ordered_ids.append(new_concept.id)

        split_ops.append(split_decision.split_op)
        self.stats["splits_made"] += 1
        return candidate_deferred

    def _should_split(
        self,
        candidate: AmbiguityCandidate,
        llm_result: LLMDisambiguationResult,
        confidence: float,
    ) -> tuple[bool, str]:
        senses = llm_result.senses
        if not llm_result.separable or len(senses) < 2:
            self.stats["llm_nonseparable"] += 1
            return False, "LLM did not produce distinct senses"
        if confidence <= self._policy.defer_ambiguous_threshold:
            self.stats["confidence_below_defer"] += 1
            reason = (
                f"Confidence {confidence:.2f} below defer threshold "
                f"{self._policy.defer_ambiguous_threshold:.2f}"
            )
            return False, reason
        if confidence < self._policy.min_evidence_strength:
            self.stats["confidence_below_split"] += 1
            reason = (
                f"Confidence {confidence:.2f} below split threshold "
                f"{self._policy.min_evidence_strength:.2f}"
            )
            return False, reason
        return True, ""

    def _mark_deferred_for_concepts(
        self,
        reason: str,
        concepts: Sequence[Concept],
        concept_map: Dict[str, Concept],
        deferred: List[str],
    ) -> None:
        for concept in concepts:
            tracked_concept = concept_map.get(concept.id)
            if tracked_concept is None:
                continue
            self._mark_deferred(tracked_concept, reason)
            deferred.append(concept.id)

    def _mark_deferred(self, concept: Concept, reason: str) -> None:
        rationale = concept.rationale
        if not isinstance(rationale, Rationale):
            return
        rationale.passed_gates["disambiguation"] = False
        if reason:
            rationale.reasons.append(reason)


def build_processor(policy: DisambiguationPolicy) -> DisambiguationProcessor:
    return DisambiguationProcessor(policy)


__all__ = [
    "DisambiguationProcessor",
    "ContextAnalyzer",
    "DisambiguationOutcome",
    "build_processor",
]
