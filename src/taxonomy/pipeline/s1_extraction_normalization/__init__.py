"""Placeholder module for S1 extraction and normalization logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from loguru import logger


class NormalizationStage(Protocol):
    """Interface for normalization sub-stages."""

    name: str

    def run(self) -> None:
        ...


@dataclass
class ExtractionNormalizer:
    """Composite runner for S1 logic (LLM + rule-based normalization)."""

    stages: list[NormalizationStage]

    def execute(self) -> None:
        for stage in self.stages:
            logger.info("Running S1 stage", stage=stage.name)
            stage.run()


__all__ = ["NormalizationStage", "ExtractionNormalizer"]
