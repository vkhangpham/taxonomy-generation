"""Similarity scoring utilities tailored for concept deduplication."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from taxonomy.config.policies import DeduplicationPolicy
from taxonomy.entities.core import Concept
from taxonomy.utils import (
    abbrev_score,
    jaro_winkler_similarity,
    token_jaccard_similarity,
)
from taxonomy.utils.logging import get_logger


_LOGGER = get_logger(module=__name__)


@dataclass
class SimilarityFeatures:
    """Individual similarity feature scores."""

    jaro_winkler: float
    token_jaccard: float
    abbrev_score: float
    weighted: Dict[str, float]


@dataclass
class SimilarityDecision:
    """Outcome of a similarity evaluation for a concept pair."""

    score: float
    threshold: float
    passed: bool
    features: SimilarityFeatures
    driver: str


class SimilarityScorer:
    """Compute similarity between concept pairs using multiple signals."""

    def __init__(self, policy: DeduplicationPolicy) -> None:
        self.policy = policy

    def _threshold_for_pair(self, concept_a: Concept, concept_b: Concept) -> float:
        max_level = max(concept_a.level, concept_b.level)
        if max_level <= 1:
            return self.policy.thresholds.l0_l1
        return self.policy.thresholds.l2_l3

    def parent_compatible(self, concept_a: Concept, concept_b: Concept) -> bool:
        if not self.policy.parent_context_strict:
            return True
        if concept_a.level == 0 or concept_b.level == 0:
            return True
        parents_a = set(concept_a.parents)
        parents_b = set(concept_b.parents)
        if not parents_a or not parents_b:
            return self.policy.cross_parent_merge_allowed
        overlap = parents_a & parents_b
        if overlap:
            return True
        return self.policy.cross_parent_merge_allowed

    def compute_features(self, concept_a: Concept, concept_b: Concept) -> SimilarityFeatures:
        jw = jaro_winkler_similarity(concept_a.canonical_label, concept_b.canonical_label)
        token = token_jaccard_similarity(concept_a.canonical_label, concept_b.canonical_label)
        acronym = abbrev_score(concept_a.canonical_label, concept_b.canonical_label)

        weighted = {
            "jaro_winkler": jw * self.policy.jaro_winkler_weight,
            "token_jaccard": token * self.policy.jaccard_weight,
            "abbrev_score": acronym * self.policy.abbrev_score_weight,
        }

        return SimilarityFeatures(
            jaro_winkler=jw,
            token_jaccard=token,
            abbrev_score=acronym,
            weighted=weighted,
        )

    def combined_score(self, features: SimilarityFeatures) -> Tuple[float, str]:
        best_key = max(features.weighted, key=features.weighted.__getitem__)
        return features.weighted[best_key], best_key

    def score_pair(self, concept_a: Concept, concept_b: Concept) -> SimilarityDecision:
        features = self.compute_features(concept_a, concept_b)
        combined, driver = self.combined_score(features)
        threshold = max(self._threshold_for_pair(concept_a, concept_b), self.policy.min_similarity_threshold)
        passed = combined >= threshold
        _LOGGER.debug(
            "Evaluated similarity",
            concept_a=concept_a.id,
            concept_b=concept_b.id,
            combined=combined,
            threshold=threshold,
            driver=driver,
            features=features.weighted,
        )
        return SimilarityDecision(
            score=combined,
            threshold=threshold,
            passed=passed,
            features=features,
            driver=driver,
        )


__all__ = ["SimilarityScorer", "SimilarityDecision", "SimilarityFeatures"]
