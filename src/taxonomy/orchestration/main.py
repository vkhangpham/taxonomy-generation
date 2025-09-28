"""High-level orchestration entry points for taxonomy generation."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Callable

from taxonomy.config.settings import Settings
from taxonomy.pipeline.hierarchy_assembly import HierarchyAssembler
from taxonomy.entities.core import Concept
from taxonomy.utils.helpers import ensure_directory, serialize_json
from taxonomy.utils.logging import get_logger, logging_context

from .checkpoints import CheckpointManager
from .manifest import RunManifest
from .phases import PhaseManager, PhaseContext

_LOGGER = get_logger(module=__name__)


@dataclass(slots=True)
class RunResult:
    manifest: Dict[str, Any]
    phase_results: Dict[str, Any]
    manifest_path: Path


class TaxonomyOrchestrator:
    """Coordinates the full taxonomy pipeline lifecycle."""

    def __init__(
        self,
        *,
        settings: Settings,
        checkpoint_manager: CheckpointManager,
        manifest: RunManifest,
        phase_manager: PhaseManager,
        run_directory: Path,
    ) -> None:
        self._settings = settings
        self._checkpoint_manager = checkpoint_manager
        self._manifest = manifest
        self._phase_manager = phase_manager
        self._run_directory = run_directory

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        run_id: Optional[str] = None,
        adapters: Optional[Dict[str, Any]] = None,
    ) -> "TaxonomyOrchestrator":
        run_id = run_id or datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        run_root = ensure_directory(Path(settings.paths.output_dir) / "runs")
        run_directory = ensure_directory(run_root / run_id)

        checkpoint_manager = CheckpointManager(run_id, run_directory)
        manifest = RunManifest(run_id)
        manifest.collect_versions(settings=settings)
        manifest.capture_configuration(settings=settings)

        adapters = adapters or {}
        level_generators = adapters.get("level_generators", _default_level_generators())
        consolidator = adapters.get("consolidator", _default_consolidator)
        post_processors = adapters.get("post_processors", _default_post_processors())
        finalizer = adapters.get("finalizer", _build_default_finalizer(settings))
        resume_handler = adapters.get("resume_handler")

        phase_manager = PhaseManager(
            settings=settings,
            checkpoint_manager=checkpoint_manager,
            manifest=manifest,
            level_generators=level_generators,
            consolidator=consolidator,
            post_processors=post_processors,
            finalizer=finalizer,
            resume_handler=resume_handler,
        )

        return cls(
            settings=settings,
            checkpoint_manager=checkpoint_manager,
            manifest=manifest,
            phase_manager=phase_manager,
            run_directory=run_directory,
        )

    @property
    def run_directory(self) -> Path:
        return self._run_directory

    @property
    def manifest(self) -> RunManifest:
        return self._manifest

    def run(self, *, resume_phase: Optional[str] = None) -> RunResult:
        order = self._phase_manager.phase_order()
        if resume_phase is None:
            last_completed = self._checkpoint_manager.determine_resume_point(order)
            if last_completed:
                idx = order.index(last_completed)
                resume_phase = order[idx + 1] if idx + 1 < len(order) else last_completed

        with logging_context(run_id=self._checkpoint_manager.run_id, step="orchestration"):
            phase_results = self._phase_manager.execute_all(resume_from=resume_phase)

        for artifact in self._checkpoint_manager.iter_artifacts():
            self._manifest.add_artifact(artifact["path"], kind=artifact.get("kind", "unknown"))

        manifest_dict = self._manifest.finalize()
        manifest_path = serialize_json(manifest_dict, self._run_directory / "run_manifest.json")
        self._checkpoint_manager.record_artifact(manifest_path, kind="run-manifest")

        return RunResult(
            manifest=manifest_dict,
            phase_results=phase_results,
            manifest_path=Path(manifest_path),
        )


def _default_level_generators() -> Mapping[int, Any]:
    def generator(context: PhaseContext, level: int) -> Dict[str, Any]:
        parent_key = f"phase1_level{level - 1}"
        parent_payload = context.get(parent_key, {})
        parent_candidates = parent_payload.get("candidates", [])
        candidates = [f"L{level}-concept-{idx}" for idx, _ in enumerate(parent_candidates or [None])]
        stats = {"candidates": len(candidates)}
        return {"level": level, "candidates": candidates, "stats": stats}

    return {level: generator for level in range(4)}


def _default_consolidator(context: PhaseContext) -> Dict[str, Any]:
    aggregated: Dict[str, Any] = {"concepts": []}
    for level_phase in PhaseManager.LEVEL_PHASES:
        payload = context.get(level_phase, {})
        aggregated["concepts"].extend(payload.get("candidates", []))
    stats = {"concepts": len(aggregated["concepts"]) }
    aggregated["stats"] = stats
    return aggregated


def _default_post_processors() -> Sequence[Any]:
    def validator(context: PhaseContext) -> Dict[str, Any]:
        concepts = context.get(PhaseManager.CONSOLIDATION_PHASE, {}).get("concepts", [])
        return {"stage": "validation", "changed": False, "concepts": concepts}

    def deduplicator(context: PhaseContext) -> Dict[str, Any]:
        concepts = context.get(PhaseManager.CONSOLIDATION_PHASE, {}).get("concepts", [])
        return {"stage": "deduplication", "changed": False, "concepts": concepts}

    return [validator, deduplicator]


def _build_default_finalizer(settings: Settings) -> Callable[[PhaseContext], Dict[str, Any]]:
    policy = settings.policies.hierarchy_assembly

    def finalizer(context: PhaseContext) -> Dict[str, Any]:
        assembler = HierarchyAssembler(policy)
        history = context.get(PhaseManager.POST_PROCESSING_PHASE, {}).get("history", [])
        flattened: list[Concept] = []
        for iteration in history:
            for result in iteration.get("results", []):
                for item in result.get("concepts", []):
                    if isinstance(item, Concept):
                        flattened.append(item)
        if not flattened:
            _LOGGER.debug(
                "No concepts supplied from post-processing; assembling empty hierarchy",
                run_id=context.run_id,
            )
        hierarchy_result = assembler.run(flattened)
        stats = hierarchy_result.graph.statistics()
        validation = hierarchy_result.validation_report.to_dict()
        context_state = {
            "stats": stats,
            "validation": validation,
            "placeholders": hierarchy_result.placeholders,
        }
        return context_state

    return finalizer


def run_taxonomy_pipeline(
    *,
    config_overrides: Optional[Dict[str, Any]] = None,
    resume_from: Optional[str] = None,
    settings: Optional[Settings] = None,
    adapters: Optional[Dict[str, Any]] = None,
) -> RunResult:
    config_overrides = config_overrides or {}
    cfg = settings or Settings(**config_overrides)
    orchestrator = TaxonomyOrchestrator.from_settings(cfg, adapters=adapters)
    result = orchestrator.run(resume_phase=resume_from)
    return result


def _build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the taxonomy orchestration pipeline")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Start a new taxonomy run")
    run_parser.add_argument("--environment", choices=["development", "testing", "production"], default=None)
    run_parser.add_argument("--resume-phase", default=None)

    resume_parser = subparsers.add_parser("resume", help="Resume an existing run")
    resume_parser.add_argument("run_id")
    resume_parser.add_argument("--phase", default=None)

    status_parser = subparsers.add_parser("status", help="List checkpoints for a run")
    status_parser.add_argument("run_id")

    subparsers.add_parser("validate", help="Validate configuration and exit")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_cli()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "validate":
        Settings()
        _LOGGER.info("Configuration loaded successfully")
        return 0

    if args.command == "status":
        settings = Settings()
        run_root = Path(settings.paths.output_dir) / "runs"
        run_directory = run_root / args.run_id
        if not run_directory.exists():
            _LOGGER.info("No checkpoints found", run_id=args.run_id)
            return 0
        checkpoint_manager = CheckpointManager(args.run_id, run_directory)
        checkpoint_paths = sorted(checkpoint_manager.base_directory.glob("*.checkpoint.json"))
        if not checkpoint_paths:
            _LOGGER.info("No checkpoints found", run_id=args.run_id)
            return 0
        for path in checkpoint_paths:
            _LOGGER.info("Checkpoint", path=str(path))
        return 0

    if args.command == "resume":
        settings = Settings()
        orchestrator = TaxonomyOrchestrator.from_settings(settings, run_id=args.run_id)
        orchestrator.run(resume_phase=args.phase)
        return 0

    if args.command == "run":
        settings_kwargs = {}
        if args.environment:
            settings_kwargs["environment"] = args.environment
        settings = Settings(**settings_kwargs)
        orchestrator = TaxonomyOrchestrator.from_settings(settings)
        orchestrator.run(resume_phase=args.resume_phase)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
