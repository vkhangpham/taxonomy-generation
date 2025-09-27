"""S1 extraction & normalization pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from taxonomy.entities.core import Candidate, Concept, SourceRecord

from .extractor import ExtractionMetrics, ExtractionProcessor, RawExtractionCandidate
from .io import generate_metadata, load_source_records, write_candidates
from .main import extract_candidates
from .normalizer import CandidateNormalizer, NormalizedCandidate
from .parent_index import ParentIndex
from .processor import S1Processor


class NormalizationStage(Protocol):
    """Legacy protocol retained for backwards compatibility."""

    name: str

    def run(self) -> None:
        ...


@dataclass
class ExtractionNormalizer:
    """Compatibility wrapper that sequentially executes provided stages."""

    stages: Sequence[NormalizationStage]

    def execute(self) -> None:
        for stage in self.stages:
            stage.run()


__all__ = [
    "extract_candidates",
    "ExtractionProcessor",
    "CandidateNormalizer",
    "ParentIndex",
    "S1Processor",
    "ExtractionMetrics",
    "RawExtractionCandidate",
    "NormalizedCandidate",
    "generate_metadata",
    "load_source_records",
    "write_candidates",
    "NormalizationStage",
    "ExtractionNormalizer",
]
