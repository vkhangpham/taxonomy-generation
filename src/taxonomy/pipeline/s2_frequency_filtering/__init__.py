"""Frequency filtering utilities for S2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loguru import logger


class FrequencyFilter(Protocol):
    """Common interface for S2 filters."""

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


__all__ = ["FrequencyFilter", "FrequencyFilteringPipeline"]
