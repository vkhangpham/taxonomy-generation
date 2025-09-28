"""Phase orchestration for the end-to-end taxonomy pipeline."""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from taxonomy.config.settings import Settings
from taxonomy.observability import ObservabilityContext
from taxonomy.utils.logging import get_logger

from .checkpoints import CheckpointManager
from .manifest import RunManifest

_LOGGER = get_logger(module=__name__)

PhaseCallable = Callable[["PhaseContext"], Dict[str, Any]]
LevelCallable = Callable[["PhaseContext", int], Dict[str, Any]]


@dataclass(slots=True)
class PhaseContext:
    """Shared context object passed to phase callables."""

    settings: Settings
    run_id: str
    observability: ObservabilityContext
    state: Dict[str, Any] = field(default_factory=dict)

    def record(self, phase: str, payload: Dict[str, Any]) -> None:
        self.state[phase] = payload

    def get(self, phase: str, default: Any = None) -> Any:
        return self.state.get(phase, default)

    def phase(self, name: str):
        return self.observability.phase(name)

    def log_operation(
        self,
        phase: str,
        *,
        operation: str,
        outcome: str = "success",
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        self.observability.record_operation(
            phase=phase,
            operation=operation,
            outcome=outcome,
            payload=payload,
        )


class PhaseManager:
    """Coordinates the five pipeline phases with checkpointing support."""

    LEVEL_PHASES = ["phase1_level0", "phase1_level1", "phase1_level2", "phase1_level3"]
    CONSOLIDATION_PHASE = "phase2_consolidation"
    POST_PROCESSING_PHASE = "phase3_post_processing"
    RESUME_PHASE = "phase4_resume"
    FINALIZATION_PHASE = "phase5_finalization"

    def __init__(
        self,
        *,
        settings: Settings,
        checkpoint_manager: CheckpointManager,
        manifest: RunManifest,
        level_generators: Mapping[int, LevelCallable],
        consolidator: PhaseCallable,
        post_processors: Sequence[PhaseCallable],
        finalizer: PhaseCallable,
        resume_handler: PhaseCallable | None = None,
        max_post_processing_iterations: int = 5,
    ) -> None:
        self._settings = settings
        self._checkpoint_manager = checkpoint_manager
        self._manifest = manifest
        self._level_generators = dict(level_generators)
        self._consolidator = consolidator
        self._post_processors = list(post_processors)
        self._resume_handler = resume_handler
        self._finalizer = finalizer
        self._observability = ObservabilityContext(
            run_id=checkpoint_manager.run_id,
            policy=settings.policies.observability,
        )
        manifest.attach_observability(self._observability)
        self._context = PhaseContext(
            settings=settings,
            run_id=checkpoint_manager.run_id,
            observability=self._observability,
        )
        self._max_iterations = max_post_processing_iterations

    def _run_with_observability(
        self,
        phase_name: str,
        runner: Callable[[], Dict[str, Any]],
        *,
        metrics_builder: Callable[[Dict[str, Any]], Mapping[str, Any]] | None = None,
        observability_phase: str | None = None,
    ) -> Dict[str, Any]:
        """Execute *runner* inside the observability phase context."""

        metrics: Dict[str, Any] = {}
        target_phase = observability_phase or phase_name
        try:
            self._observability.registry.ensure_phase(target_phase)
        except KeyError:
            phase_cm = nullcontext()
        else:
            phase_cm = self._observability.phase(target_phase)
        with phase_cm as phase_handle:
            if phase_handle is not None and hasattr(phase_handle, "log_operation"):
                phase_handle.log_operation(operation="start")
            start = perf_counter()
            try:
                payload = runner()
            except Exception as exc:
                elapsed = perf_counter() - start
                if phase_handle is not None and hasattr(phase_handle, "performance"):
                    phase_handle.performance({"elapsed_seconds": elapsed, "outcome": "error"})
                    if hasattr(phase_handle, "log_operation"):
                        phase_handle.log_operation(
                            operation="failure",
                            outcome="error",
                            payload={"error": str(exc)},
                        )
                raise
            elapsed = perf_counter() - start
            metrics.update({"elapsed_seconds": elapsed})
            if metrics_builder is not None:
                extras = dict(metrics_builder(payload))
                metrics.update(extras)
            if phase_handle is not None and hasattr(phase_handle, "performance"):
                phase_handle.performance(metrics)
                if hasattr(phase_handle, "log_operation"):
                    phase_handle.log_operation(operation="complete", payload=dict(metrics))
        self._manifest.collect_performance_data(phase_name, metrics)
        return payload

    # ------------------------------------------------------------------
    # Phase execution helpers
    # ------------------------------------------------------------------
    def run_level_generation(self, level: int) -> Dict[str, Any]:
        phase_name = self.LEVEL_PHASES[level]
        generator = self._level_generators.get(level)
        if generator is None:
            raise KeyError(f"No level generator registered for level {level}")
        _LOGGER.info("Running level generation", level=level)

        def _runner() -> Dict[str, Any]:
            return generator(self._context, level)

        payload = self._run_with_observability(
            phase_name,
            _runner,
            metrics_builder=lambda result: {
                "level": level,
                "records": result.get("stats", {}).get("records_in", 0),
                "candidates": result.get("stats", {}).get("candidates_out", 0),
            },
            observability_phase="S1",
        )
        self._context.record(phase_name, payload)
        self._manifest.aggregate_statistics(phase_name, payload.get("stats", {}))
        self._checkpoint_manager.save_phase_checkpoint(phase_name, payload)
        return payload

    def consolidate_raw_universe(self) -> Dict[str, Any]:
        _LOGGER.info("Starting consolidation phase")

        def _runner() -> Dict[str, Any]:
            return self._consolidator(self._context)

        payload = self._run_with_observability(
            self.CONSOLIDATION_PHASE,
            _runner,
            metrics_builder=lambda result: {
                "records": result.get("stats", {}).get("records_in", 0),
                "level": "consolidation",
            },
            observability_phase="S2",
        )
        self._context.record(self.CONSOLIDATION_PHASE, payload)
        self._manifest.aggregate_statistics(
            self.CONSOLIDATION_PHASE, payload.get("stats", {})
        )
        self._checkpoint_manager.save_phase_checkpoint(self.CONSOLIDATION_PHASE, payload)
        return payload

    def run_post_processing(self) -> Dict[str, Any]:
        _LOGGER.info("Running post-processing pipeline")

        def _runner() -> Dict[str, Any]:
            iterations = 0
            history: List[Dict[str, Any]] = []
            changed = True
            while changed and iterations < self._max_iterations:
                iterations += 1
                changed = False
                iteration_payload: Dict[str, Any] = {"iteration": iterations, "results": []}
                for processor in self._post_processors:
                    result = processor(self._context)
                    iteration_payload["results"].append(result)
                    changed = changed or bool(result.get("changed"))
                history.append(iteration_payload)
                if not changed:
                    break
            return {
                "iterations": iterations,
                "history": history,
                "converged": not changed,
            }

        payload = self._run_with_observability(
            self.POST_PROCESSING_PHASE,
            _runner,
            metrics_builder=lambda result: {
                "iterations": result.get("iterations", 0),
                "converged": result.get("converged", True),
            },
            observability_phase="S3",
        )
        self._context.record(self.POST_PROCESSING_PHASE, payload)
        self._manifest.aggregate_statistics(
            self.POST_PROCESSING_PHASE,
            {"iterations": payload.get("iterations", 0), "converged": payload.get("converged", True)},
        )
        self._checkpoint_manager.save_phase_checkpoint(self.POST_PROCESSING_PHASE, payload)
        return payload

    def resume_management(self) -> Dict[str, Any]:
        handler = self._resume_handler
        _LOGGER.info("Executing resume management phase", supported=bool(handler))

        def _runner() -> Dict[str, Any]:
            if handler is None:
                return {"supported": False}
            return handler(self._context)

        payload = self._run_with_observability(
            self.RESUME_PHASE,
            _runner,
            metrics_builder=lambda result: {"supported": bool(result.get("supported", False))},
        )
        self._context.record(self.RESUME_PHASE, payload)
        self._checkpoint_manager.save_phase_checkpoint(self.RESUME_PHASE, payload)
        return payload

    def finalize_taxonomy(self) -> Dict[str, Any]:
        _LOGGER.info("Finalising taxonomy")

        def _runner() -> Dict[str, Any]:
            return self._finalizer(self._context)

        payload = self._run_with_observability(
            self.FINALIZATION_PHASE,
            _runner,
            metrics_builder=lambda result: {
                "validation_nodes": len(result.get("validation", {}).get("nodes", []))
                if isinstance(result.get("validation"), dict)
                else 0,
            },
            observability_phase="Hierarchy",
        )
        self._context.record(self.FINALIZATION_PHASE, payload)
        self._manifest.aggregate_statistics(
            self.FINALIZATION_PHASE, payload.get("stats", {})
        )
        if "stats" in payload and "validation" in payload:
            self._manifest.summarize_hierarchy(
                stats=payload.get("stats", {}),
                validation=payload.get("validation", {}),
            )
        self._checkpoint_manager.save_phase_checkpoint(self.FINALIZATION_PHASE, payload)
        return payload

    # ------------------------------------------------------------------
    # Composite execution
    # ------------------------------------------------------------------
    def phase_order(self) -> List[str]:
        return [
            *self.LEVEL_PHASES,
            self.CONSOLIDATION_PHASE,
            self.POST_PROCESSING_PHASE,
            self.RESUME_PHASE,
            self.FINALIZATION_PHASE,
        ]

    def execute_all(self, *, resume_from: Optional[str] = None) -> Dict[str, Any]:
        results: Dict[str, Any] = {}
        order = self.phase_order()
        if resume_from is not None and resume_from not in order:
            raise ValueError(
                f"Unknown resume phase '{resume_from}'. Valid phases: {', '.join(order)}"
            )
        skipping = resume_from is not None
        for phase_name in order:
            if skipping:
                if phase_name == resume_from:
                    skipping = False
                else:
                    _LOGGER.info("Skipping phase due to resume", phase=phase_name)
                    self._observability.record_operation(
                        phase=phase_name,
                        operation="resume_skip",
                        payload={"resume_from": resume_from},
                    )
                    continue
            if phase_name.startswith("phase1_level"):
                level = int(phase_name[-1])
                results[phase_name] = self.run_level_generation(level)
            elif phase_name == self.CONSOLIDATION_PHASE:
                results[phase_name] = self.consolidate_raw_universe()
            elif phase_name == self.POST_PROCESSING_PHASE:
                results[phase_name] = self.run_post_processing()
            elif phase_name == self.RESUME_PHASE:
                results[phase_name] = self.resume_management()
            elif phase_name == self.FINALIZATION_PHASE:
                results[phase_name] = self.finalize_taxonomy()
        return results

    @property
    def context(self) -> PhaseContext:
        return self._context

    @property
    def observability(self) -> ObservabilityContext:
        return self._observability
