"""S2 frequency filtering processor orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from taxonomy.utils.logging import get_logger

from .aggregator import (
    CandidateAggregator,
    CandidateEvidence,
    FrequencyAggregationResult,
)


@dataclass
class S2Processor:
    """Coordinate S2 aggregation and threshold evaluation."""

    aggregator: CandidateAggregator

    def __post_init__(self) -> None:
        self._log = get_logger(module=__name__)

    def process(self, items: Iterable[CandidateEvidence]) -> FrequencyAggregationResult:
        """Process an iterable of S1 candidates through frequency filtering."""

        result = self.aggregator.aggregate(items)
        self._log.info(
            "Completed S2 frequency filtering",
            stats=result.stats,
        )
        return result


__all__ = ["S2Processor"]
