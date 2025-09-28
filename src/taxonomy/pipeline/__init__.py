"""Pipeline orchestration primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, TYPE_CHECKING

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
    _steps_by_name: Dict[str, PipelineStep] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self._ensure_steps_index()

    def execute(self, *, resume_from: str | None = None) -> None:
        self._ensure_steps_index()
        step_names = list(self._steps_by_name.keys())
        if resume_from is not None and resume_from not in self._steps_by_name:
            raise ValueError(
                f"Unknown resume_from step '{resume_from}'. Valid steps: {step_names}"
            )
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
                self.checkpoint_manager.save_phase_checkpoint(
                    f"pipeline::{step.name}", {"status": "completed"}
                )

    def add_step(self, step: PipelineStep) -> None:
        self._ensure_steps_index()
        if step.name in self._steps_by_name:
            raise ValueError(f"Duplicate pipeline step name '{step.name}'")
        self.steps.append(step)
        self._steps_by_name[step.name] = step

    def status(self) -> dict:
        remaining = [step.name for step in self.steps if step.name not in self.completed_steps]
        return {
            "name": self.name,
            "completed": list(self.completed_steps),
            "pending": remaining,
        }

    def _ensure_steps_index(self) -> None:
        if len(self._steps_by_name) == len(self.steps):
            return
        self._steps_by_name.clear()
        for step in self.steps:
            if step.name in self._steps_by_name:
                raise ValueError(
                    f"Duplicate pipeline step name '{step.name}' detected while refreshing step index."
                )
            self._steps_by_name[step.name] = step


__all__ = ["Pipeline", "PipelineStep"]
