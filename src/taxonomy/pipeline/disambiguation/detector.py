"""Ambiguity detection for the disambiguation pipeline."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from typing import Dict, Iterable, List, Mapping, Sequence

from ...config.policies import DisambiguationPolicy
from ...entities.core import Concept
from ...utils import (
    analyze_institution_distribution,
    compute_token_cooccurrence,
    extract_parent_lineage_key,
)
from ...utils.context_features import ContextWindow


@dataclass
class AmbiguityCandidate:
    """Container describing a potential ambiguity collision."""

    label: str
    normalized_label: str
    concepts: List[Concept]
    parent_divergence: float
    context_overlap: float
    context_divergence: float
    institution_divergence: float
    score: float
    evidence: Dict[str, object]


class AmbiguityDetector:
    """Identify ambiguous concepts that should be considered for disambiguation."""

    def __init__(self, policy: DisambiguationPolicy) -> None:
        self._policy = policy
        self.stats: Dict[str, int] = defaultdict(int)

    def detect_collisions(
        self,
        concepts: Sequence[Concept],
        contexts: Mapping[str, Sequence[ContextWindow]] | None = None,
    ) -> List[AmbiguityCandidate]:
        grouped: Dict[str, List[Concept]] = defaultdict(list)
        for concept in concepts:
            normalized = concept.canonical_label.strip().lower()
            grouped[normalized].append(concept)

        candidates: List[AmbiguityCandidate] = []
        for normalized_label, group in grouped.items():
            if len(group) < 2:
                continue
            self.stats["collisions_scanned"] += 1

            if self._policy.require_multiple_parents:
                parent_lineages = {
                    extract_parent_lineage_key(concept) for concept in group
                }
                if len(parent_lineages) < 2:
                    self.stats["skipped_single_parent"] += 1
                    continue

            parent_divergence = self.analyze_parent_divergence(group)
            if parent_divergence < self._policy.min_parent_divergence:
                self.stats["skipped_parent_threshold"] += 1
                continue

            context_overlap = self.compute_context_overlap(group, contexts)
            context_divergence = 1.0 - min(context_overlap, 1.0)
            if context_overlap > self._policy.min_context_overlap_threshold:
                self.stats["skipped_context_overlap"] += 1
                continue

            institution_divergence = self.check_institution_patterns(group)

            score = self.score_ambiguity(
                parent_divergence,
                context_divergence,
                institution_divergence,
            )
            if score <= 0.0:
                self.stats["skipped_low_score"] += 1
                continue

            evidence = {
                "parent_divergence": parent_divergence,
                "context_overlap": context_overlap,
                "context_divergence": context_divergence,
                "institution_divergence": institution_divergence,
                "group_size": len(group),
            }
            candidate = AmbiguityCandidate(
                label=group[0].canonical_label,
                normalized_label=normalized_label,
                concepts=list(group),
                parent_divergence=parent_divergence,
                context_overlap=context_overlap,
                context_divergence=context_divergence,
                institution_divergence=institution_divergence,
                score=score,
                evidence=evidence,
            )
            candidates.append(candidate)
            self.stats["collisions_flagged"] += 1

        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates

    def analyze_parent_divergence(self, concept_group: Sequence[Concept]) -> float:
        if len(concept_group) < 2:
            return 0.0
        similarities: List[float] = []
        for left, right in combinations(concept_group, 2):
            left_parents = set(left.parents)
            right_parents = set(right.parents)
            if not left_parents and not right_parents:
                similarities.append(1.0)
                continue
            union = left_parents | right_parents
            if not union:
                similarities.append(1.0)
                continue
            intersection = left_parents & right_parents
            similarities.append(len(intersection) / len(union))
        if not similarities:
            return 0.0
        avg_similarity = sum(similarities) / len(similarities)
        return max(0.0, min(1.0, 1.0 - avg_similarity))

    def compute_context_overlap(
        self,
        concept_group: Sequence[Concept],
        contexts: Mapping[str, Sequence[ContextWindow]] | None,
    ) -> float:
        if not contexts:
            return 0.0

        token_sets: List[set[str]] = []
        for concept in concept_group:
            concept_contexts = contexts.get(concept.id, [])
            if not concept_contexts:
                continue
            tokens = set(
                compute_token_cooccurrence(concept_contexts, min_frequency=1).keys()
            )
            if tokens:
                token_sets.append(tokens)
        if len(token_sets) < 2:
            return 0.0

        overlap_scores: List[float] = []
        for left, right in combinations(token_sets, 2):
            union = left | right
            if not union:
                overlap_scores.append(1.0)
            else:
                overlap_scores.append(len(left & right) / len(union))
        if not overlap_scores:
            return 0.0
        return sum(overlap_scores) / len(overlap_scores)

    def check_institution_patterns(self, concept_group: Sequence[Concept]) -> float:
        distributions = analyze_institution_distribution(concept_group)
        if not distributions:
            return 0.0

        institution_sets = [set(data.keys()) for data in distributions.values() if data]
        if len(institution_sets) < 2:
            return 0.0

        divergences: List[float] = []
        for left, right in combinations(institution_sets, 2):
            if not left and not right:
                divergences.append(0.0)
                continue
            union = left | right
            if not union:
                divergences.append(0.0)
                continue
            overlap = len(left & right) / len(union)
            divergences.append(1.0 - overlap)
        if not divergences:
            return 0.0
        return max(0.0, min(1.0, sum(divergences) / len(divergences)))

    def score_ambiguity(
        self,
        parent_divergence: float,
        context_divergence: float,
        institution_divergence: float,
    ) -> float:
        score = (
            parent_divergence * 0.4
            + context_divergence * 0.35
            + institution_divergence * 0.25
        )
        return max(0.0, min(1.0, score))


__all__ = [
    "AmbiguityDetector",
    "AmbiguityCandidate",
]
