"""Similarity scoring utilities tailored for concept deduplication."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

from taxonomy.config.policies import DeduplicationPolicy
from taxonomy.entities.core import Concept
from taxonomy.utils import (
    abbrev_score,
    jaro_winkler_similarity,
    token_jaccard_similarity,
)
from taxonomy.utils.logging import get_logger


_LOGGER = get_logger(module=__name__)
_ALIAS_PROBE_LIMIT = 3


def _tokenize(label: str) -> list[str]:
    """Return lowercase alphanumeric tokens for the heuristic helpers."""

    return [token for token in re.split(r"[^0-9a-z]+", label.lower()) if token]


def suffix_prefix_hint(label_a: str, label_b: str, suffix_terms: Iterable[str]) -> float:
    """Detect near matches that only differ by configured suffix/prefix tokens."""

    suffix_token_lists = [tuple(_tokenize(term)) for term in suffix_terms]
    suffix_token_lists = [tokens for tokens in suffix_token_lists if tokens]
    if not suffix_token_lists:
        return 0.0

    tokens_a = _tokenize(label_a)
    tokens_b = _tokenize(label_b)
    if not tokens_a or not tokens_b:
        return 0.0

    for suffix_tokens in suffix_token_lists:
        size = len(suffix_tokens)
        suffix_list = list(suffix_tokens)
        if size >= len(tokens_a) and size >= len(tokens_b):
            continue
        if len(tokens_a) > size and tokens_a[:-size] == tokens_b and tokens_a[-size:] == suffix_list:
            return 1.0
        if len(tokens_b) > size and tokens_b[:-size] == tokens_a and tokens_b[-size:] == suffix_list:
            return 1.0
        if len(tokens_a) > size and tokens_a[size:] == tokens_b and tokens_a[:size] == suffix_list:
            return 1.0
        if len(tokens_b) > size and tokens_b[size:] == tokens_a and tokens_b[:size] == suffix_list:
            return 1.0
    return 0.0


@dataclass
class SimilarityFeatures:
    """Individual similarity feature scores."""

    raw: Dict[str, float]
    weighted: Dict[str, float]
    suffix_prefix_hint: float

    @property
    def jaro_winkler(self) -> float:
        return self.raw.get("jaro_winkler", 0.0)

    @property
    def token_jaccard(self) -> float:
        return self.raw.get("token_jaccard", 0.0)

    @property
    def abbrev_score(self) -> float:
        return self.raw.get("abbrev_score", 0.0)


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

    def reset(self) -> None:
        """Reset scorer state between runs."""
        # No internal caches yet, but keep hook for future optimisations
        pass

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

    def _abbrev_score_with_aliases(self, concept_a: Concept, concept_b: Concept) -> float:
        best = min(
            abbrev_score(concept_a.canonical_label, concept_b.canonical_label),
            1.0,
        )
        if best >= 1.0:
            return 1.0

        aliases_a = concept_a.aliases[:_ALIAS_PROBE_LIMIT]
        aliases_b = concept_b.aliases[:_ALIAS_PROBE_LIMIT]
        if not aliases_a and not aliases_b:
            return best

        labels_a = [concept_a.canonical_label, *aliases_a]
        labels_b = [concept_b.canonical_label, *aliases_b]
        seen: set[Tuple[str, str]] = set()
        for label_a in labels_a:
            for label_b in labels_b:
                pair = (label_a, label_b)
                if pair in seen:
                    continue
                seen.add(pair)
                if label_a == concept_a.canonical_label and label_b == concept_b.canonical_label:
                    continue
                score = min(abbrev_score(label_a, label_b), 1.0)
                if score > best:
                    best = score
                    if best >= 1.0:
                        return 1.0
        return min(best, 1.0)

    def compute_features(self, concept_a: Concept, concept_b: Concept) -> SimilarityFeatures:
        hint = suffix_prefix_hint(
            concept_a.canonical_label,
            concept_b.canonical_label,
            self.policy.heuristic_suffixes,
        )

        raw: Dict[str, float] = {}
        weighted: Dict[str, float] = {}

        abbrev = self._abbrev_score_with_aliases(concept_a, concept_b)
        raw["abbrev_score"] = abbrev
        weighted["abbrev_score"] = abbrev * self.policy.abbrev_score_weight

        jw = min(
            jaro_winkler_similarity(concept_a.canonical_label, concept_b.canonical_label),
            1.0,
        )
        raw["jaro_winkler"] = jw
        weighted["jaro_winkler"] = jw * self.policy.jaro_winkler_weight

        token = min(
            token_jaccard_similarity(concept_a.canonical_label, concept_b.canonical_label),
            1.0,
        )
        raw["token_jaccard"] = token
        weighted["token_jaccard"] = token * self.policy.jaccard_weight

        if hint > 0.0:
            raw["suffix_prefix_hint"] = hint
            weighted["suffix_prefix_hint"] = hint * max(
                1.0, self.policy.abbrev_score_weight
            )
        return SimilarityFeatures(raw=raw, weighted=weighted, suffix_prefix_hint=hint)

    def combined_score(self, features: SimilarityFeatures) -> Tuple[float, str]:
        driver = ""
        if features.weighted:
            driver = max(features.weighted, key=features.weighted.__getitem__)
        raw_max = max(features.raw.values()) if features.raw else 0.0
        return min(raw_max, 1.0), driver

    def _finalise(
        self,
        concept_a: Concept,
        concept_b: Concept,
        threshold: float,
        raw: Dict[str, float],
        weighted: Dict[str, float],
        hint: float,
    ) -> SimilarityDecision:
        features = SimilarityFeatures(raw=dict(raw), weighted=dict(weighted), suffix_prefix_hint=hint)
        combined, driver = self.combined_score(features)
        passed = combined >= threshold
        _LOGGER.debug(
            "Evaluated similarity",
            concept_a=concept_a.id,
            concept_b=concept_b.id,
            combined=combined,
            threshold=threshold,
            driver=driver,
            raw_features=features.raw,
            weighted_features=features.weighted,
            suffix_prefix_hint=hint,
        )
        return SimilarityDecision(
            score=combined,
            threshold=threshold,
            passed=passed,
            features=features,
            driver=driver,
        )

    def score_pair(self, concept_a: Concept, concept_b: Concept) -> SimilarityDecision:
        threshold = max(
            self._threshold_for_pair(concept_a, concept_b),
            self.policy.min_similarity_threshold,
        )

        hint = suffix_prefix_hint(
            concept_a.canonical_label,
            concept_b.canonical_label,
            self.policy.heuristic_suffixes,
        )
        raw: Dict[str, float] = {}
        weighted: Dict[str, float] = {}
        if hint > 0.0:
            weighted["suffix_prefix_hint"] = hint * max(1.0, self.policy.abbrev_score_weight)

        abbrev = self._abbrev_score_with_aliases(concept_a, concept_b)
        raw["abbrev_score"] = abbrev
        weighted["abbrev_score"] = abbrev * self.policy.abbrev_score_weight

        if self.policy.enable_early_stopping and abbrev >= 1.0:
            return self._finalise(concept_a, concept_b, threshold, raw, weighted, hint)

        jw = min(
            jaro_winkler_similarity(concept_a.canonical_label, concept_b.canonical_label),
            1.0,
        )
        raw["jaro_winkler"] = jw
        weighted["jaro_winkler"] = jw * self.policy.jaro_winkler_weight

        if self.policy.enable_early_stopping and jw >= threshold:
            return self._finalise(concept_a, concept_b, threshold, raw, weighted, hint)

        if not self.policy.enable_early_stopping or jw < threshold:
            token = min(
                token_jaccard_similarity(concept_a.canonical_label, concept_b.canonical_label),
                1.0,
            )
            raw["token_jaccard"] = token
            weighted["token_jaccard"] = token * self.policy.jaccard_weight

        return self._finalise(concept_a, concept_b, threshold, raw, weighted, hint)


__all__ = ["SimilarityScorer", "SimilarityDecision", "SimilarityFeatures", "suffix_prefix_hint"]
