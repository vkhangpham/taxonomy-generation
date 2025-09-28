"""Top-level CLI entry point for the taxonomy pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, Iterable

from taxonomy.config.settings import Settings
from taxonomy.orchestration import TaxonomyOrchestrator, run_taxonomy_pipeline
from taxonomy.orchestration.checkpoints import CheckpointManager
from taxonomy.utils.logging import get_logger

_LOGGER = get_logger(module=__name__)


def _parse_override(argument: str) -> Dict[str, Any]:
    if "=" not in argument:
        raise argparse.ArgumentTypeError("Overrides must use key=value syntax")
    key, value = argument.split("=", 1)
    target: Dict[str, Any] = {}
    cursor = target
    segments = key.split(".")
    for segment in segments[:-1]:
        cursor = cursor.setdefault(segment, {})
    cursor[segments[-1]] = value
    return target


def _merge_overrides(overrides: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for override in overrides:
        stack = [(result, override)]
        while stack:
            dest, src = stack.pop()
            for key, value in src.items():
                if isinstance(value, dict):
                    if not isinstance(dest.get(key), dict):
                        dest[key] = {}
                    stack.append((dest[key], value))
                else:
                    dest[key] = value
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Taxonomy pipeline CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the full taxonomy pipeline")
    run_parser.add_argument("--environment", choices=["development", "testing", "production"], default=None)
    run_parser.add_argument("--resume-phase", default=None)
    run_parser.add_argument("--override", action="append", default=[], help="Configuration override expressed as dotted.key=value")

    resume_parser = subparsers.add_parser("resume", help="Resume a run from checkpoints")
    resume_parser.add_argument("run_id")
    resume_parser.add_argument("--phase", default=None)
    resume_parser.add_argument("--environment", choices=["development", "testing", "production"], default=None)

    status_parser = subparsers.add_parser("status", help="Show checkpoint status for a run")
    status_parser.add_argument("run_id")
    status_parser.add_argument("--environment", choices=["development", "testing", "production"], default=None)

    validate_parser = subparsers.add_parser("validate", help="Validate configuration and exit")
    validate_parser.add_argument("--environment", choices=["development", "testing", "production"], default=None)
    validate_parser.add_argument("--override", action="append", default=[])

    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "run":
        overrides = _merge_overrides(_parse_override(item) for item in args.override)
        if args.environment:
            overrides["environment"] = args.environment
        result = run_taxonomy_pipeline(config_overrides=overrides, resume_from=args.resume_phase)
        _LOGGER.info(
            "Run complete",
            manifest=str(result.manifest_path),
            phases=len(result.phase_results),
        )
        return 0

    if args.command == "resume":
        settings_kwargs = {}
        if args.environment:
            settings_kwargs["environment"] = args.environment
        settings = Settings(**settings_kwargs)
        orchestrator = TaxonomyOrchestrator.from_settings(settings, run_id=args.run_id)
        orchestrator.run(resume_phase=args.phase)
        return 0

    if args.command == "status":
        settings_kwargs = {}
        if args.environment:
            settings_kwargs["environment"] = args.environment
        settings = Settings(**settings_kwargs)
        run_root = Path(settings.paths.output_dir) / "runs"
        checkpoint_dir = run_root / args.run_id
        if not checkpoint_dir.exists():
            _LOGGER.info("No checkpoints found", run_id=args.run_id)
            return 0
        manager = CheckpointManager(args.run_id, run_root)
        for phase in sorted(manager.base_directory.glob("*.checkpoint.json")):
            _LOGGER.info("Checkpoint", phase=phase.name)
        return 0

    if args.command == "validate":
        overrides = _merge_overrides(_parse_override(item) for item in args.override)
        if args.environment:
            overrides["environment"] = args.environment
        Settings(**overrides)
        _LOGGER.info("Configuration validated successfully")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
