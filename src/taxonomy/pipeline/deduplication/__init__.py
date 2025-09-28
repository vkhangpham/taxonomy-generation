"""Deduplication pipeline entry points and public interfaces."""

from .main import deduplicate_concepts
from .processor import DeduplicationProcessor, DeduplicationResult
from .blocking import (
    BlockingStrategy,
    PrefixBlocker,
    PhoneticBlocker,
    AcronymBlocker,
    CompositeBlocker,
)
from .graph import SimilarityGraph, UnionFind
from .similarity import SimilarityScorer
from .merger import ConceptMerger

__all__ = [
    "deduplicate_concepts",
    "DeduplicationProcessor",
    "DeduplicationResult",
    "BlockingStrategy",
    "PrefixBlocker",
    "PhoneticBlocker",
    "AcronymBlocker",
    "CompositeBlocker",
    "SimilarityGraph",
    "UnionFind",
    "SimilarityScorer",
    "ConceptMerger",
]
