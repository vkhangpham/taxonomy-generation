"""Pipeline orchestration primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Protocol

from loguru import logger


class PipelineStep(Protocol):
    """Minimal interface required for pipeline steps."""

    name: str

    def run(self) -> None:
        ...


@dataclass
class Pipeline:
    """Simple orchestrator for sequential taxonomy stages."""

    steps: List[PipelineStep]

    def execute(self) -> None:
        for step in self.steps:
            logger.info("Executing pipeline step", step=step.name)
            step.run()


__all__ = ["Pipeline", "PipelineStep"]
