"""Frequency filtering public API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loguru import logger

from .aggregator import (
    CandidateAggregator,
    CandidateEvidence,
    FrequencyAggregationResult,
    FrequencyDecision,
)
from .institution_resolver import InstitutionResolver
from .io import (
    generate_s2_metadata,
    load_candidates,
    write_dropped_candidates,
    write_kept_candidates,
)
from .main import filter_by_frequency
from .processor import S2Processor


class FrequencyFilter(Protocol):
    """Common interface for legacy S2 filters."""

    name: str

    def apply(self) -> None:
        ...


@dataclass
class FrequencyFilteringPipeline:
    """Coordinator for S2 filter execution."""

    filters: list[FrequencyFilter]

    def execute(self) -> None:
        for filter_ in self.filters:
            logger.info("Applying frequency filter", filter=filter_.name)
            filter_.apply()


__all__ = [
    "CandidateAggregator",
    "CandidateEvidence",
    "FrequencyAggregationResult",
    "FrequencyDecision",
    "InstitutionResolver",
    "load_candidates",
    "write_kept_candidates",
    "write_dropped_candidates",
    "generate_s2_metadata",
    "filter_by_frequency",
    "S2Processor",
    "FrequencyFilter",
    "FrequencyFilteringPipeline",
]
