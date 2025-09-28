"""Pipeline orchestration primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol, TYPE_CHECKING

from loguru import logger


if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from taxonomy.orchestration.checkpoints import CheckpointManager


class PipelineStep(Protocol):
    """Minimal interface required for pipeline steps."""

    name: str

    def run(self) -> None:
        ...


@dataclass(slots=True)
class Pipeline:
    """Simple orchestrator for sequential taxonomy stages."""

    name: str = "taxonomy-pipeline"
    steps: List[PipelineStep] = field(default_factory=list)
    checkpoint_manager: Optional["CheckpointManager"] = None
    raise_on_error: bool = True
    completed_steps: List[str] = field(default_factory=list)

    def execute(self, *, resume_from: str | None = None) -> None:
        # Fail-fast if the given resume point doesn’t exist
        if resume_from is not None and resume_from not in {step.name for step in self.steps}:
            raise ValueError(f"Unknown resume_from step '{resume_from}'")
        skipping = resume_from is not None

        for step in self.steps:
            if skipping:
                if step.name == resume_from:
                    skipping = False
                else:
                    logger.debug(
                        "Skipping step due to resume",
                        pipeline=self.name,
                        step=step.name,
                    )
                    continue

            logger.info("Executing pipeline step", pipeline=self.name, step=step.name)
            try:
                step.run()
            except Exception as exc:  # pragma: no cover - propagation path
                logger.exception("Pipeline step failed", step=step.name)
                if self.raise_on_error:
                    raise
                continue

            self.completed_steps.append(step.name)
            if self.checkpoint_manager:
                …
                self.checkpoint_manager.save_phase_checkpoint(
                    f"pipeline::{step.name}", {"status": "completed"}
                )

    def add_step(self, step: PipelineStep) -> None:
        self.steps.append(step)

    def status(self) -> dict:
        remaining = [step.name for step in self.steps if step.name not in self.completed_steps]
        return {
            "name": self.name,
            "completed": list(self.completed_steps),
            "pending": remaining,
        }


__all__ = ["Pipeline", "PipelineStep"]
