"""Blocking strategies used for concept deduplication."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence

from taxonomy.config.policies import DeduplicationPolicy
from taxonomy.entities.core import Concept
from taxonomy.utils import (
    chunked,
    detect_acronym,
    preprocess_for_similarity,
)
from taxonomy.utils.phonetic import phonetic_bucket_keys


_ACRONYM_ALIAS_LIMIT = 3


@dataclass
class BlockingMetrics:
    """Aggregate statistics describing block creation."""

    strategy_counts: Dict[str, int] = field(default_factory=dict)
    total_blocks: int = 0
    max_block_size: int = 0
    average_block_size: float = 0.0
    block_size_distribution: Dict[int, int] = field(default_factory=dict)


@dataclass
class BlockingOutput:
    """Return value for blocking strategies."""

    blocks: Dict[str, List[Concept]]
    metrics: BlockingMetrics


class BlockingStrategy:
    """Base class for blocking strategies."""

    def __init__(self, policy: DeduplicationPolicy, name: str) -> None:
        self.policy = policy
        self.name = name

    def reset(self) -> None:
        """Clear any cached state before a new run."""
        # Default no-op so strategies can override when they maintain state
        pass

    def build_blocks(self, concepts: Sequence[Concept]) -> Dict[str, List[Concept]]:
        raise NotImplementedError

    def _limit_block(self, key: str, members: Iterable[Concept]) -> Dict[str, List[Concept]]:
        """Apply block size limits by splitting oversized blocks."""

        sorted_members = sorted(members, key=lambda concept: concept.id)
        if len(sorted_members) <= self.policy.max_block_size:
            return {key: sorted_members}

        limited: Dict[str, List[Concept]] = {}
        for idx, chunk in enumerate(chunked(sorted_members, self.policy.max_block_size)):
            limited[f"{key}|{idx:04d}"] = chunk
        return limited

    def _finalize_blocks(self, raw_blocks: Dict[str, List[Concept]]) -> Dict[str, List[Concept]]:
        """Normalize block IDs, enforce limits, and drop singletons."""

        finalized: Dict[str, List[Concept]] = {}
        for key, members in raw_blocks.items():
            # Collapse duplicates by concept ID before filtering or limiting
            unique_members = list({member.id: member for member in members}.values())
            if len(unique_members) < 2:
                continue
            limited = self._limit_block(key, unique_members)
            for limited_key, chunk in limited.items():
                block_id = f"{self.name}:{limited_key}"
                finalized[block_id] = chunk
        return dict(sorted(finalized.items()))


class PrefixBlocker(BlockingStrategy):
    """Groups concepts by the leading characters of the canonical label."""

    def __init__(self, policy: DeduplicationPolicy) -> None:
        super().__init__(policy, name="prefix")

    def build_blocks(self, concepts: Sequence[Concept]) -> Dict[str, List[Concept]]:
        prefix_length = self.policy.prefix_length
        buckets: Dict[str, List[Concept]] = defaultdict(list)
        for concept in concepts:
            normalized = preprocess_for_similarity(concept.canonical_label)
            key = normalized[:prefix_length]
            if not key:
                continue
            buckets[key].append(concept)
        return self._finalize_blocks(buckets)


class PhoneticBlocker(BlockingStrategy):
    """Groups concepts using Double Metaphone phonetic encoding."""

    def __init__(self, policy: DeduplicationPolicy) -> None:
        super().__init__(policy, name="phonetic")

    def build_blocks(self, concepts: Sequence[Concept]) -> Dict[str, List[Concept]]:
        buckets: Dict[str, List[Concept]] = defaultdict(list)
        for concept in concepts:
            for code in phonetic_bucket_keys(concept.canonical_label):
                if not code:
                    continue
                buckets[code].append(concept)
        return self._finalize_blocks(buckets)


class AcronymBlocker(BlockingStrategy):
    """Groups acronyms with their potential expansions."""

    def __init__(self, policy: DeduplicationPolicy) -> None:
        super().__init__(policy, name="acronym")

    @staticmethod
    def _expansion_key(label: str) -> str | None:
        normalized = preprocess_for_similarity(label)
        tokens = [token for token in normalized.split() if token]
        if len(tokens) < 2:
            return None
        letters = [token[0].upper() for token in tokens if token[0].isalpha()]
        key = "".join(letters)
        return key if len(key) >= 2 else None

    def build_blocks(self, concepts: Sequence[Concept]) -> Dict[str, List[Concept]]:
        buckets: Dict[str, List[Concept]] = defaultdict(list)
        for concept in concepts:
            alias_candidates: List[str] = []
            seen_aliases: set[str] = set()
            for alias in concept.aliases:
                normalized = alias.strip().lower()
                if not normalized or normalized in seen_aliases:
                    continue
                seen_aliases.add(normalized)
                alias_candidates.append(alias)
                if len(alias_candidates) >= _ACRONYM_ALIAS_LIMIT:
                    break
            candidates = [concept.canonical_label, *alias_candidates]
            for candidate in candidates:
                acronym = detect_acronym(candidate)
                if acronym:
                    buckets[acronym].append(concept)
                    continue
                key = self._expansion_key(candidate)
                if key:
                    buckets[key].append(concept)
        return self._finalize_blocks(buckets)


class CompositeBlocker:
    """Combines multiple blocking strategies and tracks metrics."""

    def __init__(self, strategies: Sequence[BlockingStrategy], policy: DeduplicationPolicy) -> None:
        self.strategies = list(strategies)
        self.policy = policy

    def reset(self) -> None:
        """Reset all blocking strategies so no cached state leaks between runs."""
        for strategy in self.strategies:
            strategy.reset()

    def build_blocks(self, concepts: Sequence[Concept]) -> BlockingOutput:
        merged: Dict[str, List[Concept]] = {}
        metrics = BlockingMetrics(strategy_counts={})
        block_sizes: List[int] = []

        for strategy in self.strategies:
            blocks = strategy.build_blocks(concepts)
            metrics.strategy_counts[strategy.name] = len(blocks)
            for key, members in blocks.items():
                merged[key] = members
                block_sizes.append(len(members))

        merged = dict(sorted(merged.items()))

        metrics.total_blocks = len(merged)
        if block_sizes:
            metrics.max_block_size = max(block_sizes)
            metrics.average_block_size = sum(block_sizes) / len(block_sizes)
            distribution: Dict[int, int] = defaultdict(int)
            for size in block_sizes:
                distribution[size] += 1
            metrics.block_size_distribution = dict(sorted(distribution.items()))
        else:
            metrics.max_block_size = 0
            metrics.average_block_size = 0.0
            metrics.block_size_distribution = {}

        return BlockingOutput(blocks=merged, metrics=metrics)


__all__ = [
    "BlockingStrategy",
    "PrefixBlocker",
    "PhoneticBlocker",
    "AcronymBlocker",
    "CompositeBlocker",
    "BlockingOutput",
    "BlockingMetrics",
]
