"""Disambiguation pipeline integrating ambiguity detection, LLM checks, and splitting."""

from __future__ import annotations

from .detector import AmbiguityCandidate, AmbiguityDetector
from .llm import LLMDisambiguationResult, LLMDisambiguator, LLMSenseDefinition
from .main import disambiguate_concepts
from .processor import ContextAnalyzer, DisambiguationOutcome, DisambiguationProcessor
from .splitter import ConceptSplitter, SplitDecision

__all__ = [
    "disambiguate_concepts",
    "DisambiguationProcessor",
    "ContextAnalyzer",
    "AmbiguityDetector",
    "AmbiguityCandidate",
    "LLMDisambiguator",
    "LLMDisambiguationResult",
    "LLMSenseDefinition",
    "ConceptSplitter",
    "SplitDecision",
]
