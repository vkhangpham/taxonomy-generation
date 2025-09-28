"""Public entry points and CLI for hierarchy assembly."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Sequence

from taxonomy.config.settings import Settings
from taxonomy.utils.helpers import serialize_json
from taxonomy.utils.logging import get_logger, logging_context

from .assembler import HierarchyAssembler, HierarchyAssemblyResult
from .io import (
    export_graph_structure,
    generate_hierarchy_metadata,
    load_concepts,
    write_hierarchy_manifest,
    write_hierarchy_statistics,
    write_orphan_report,
    write_validation_report,
)

_LOGGER = get_logger(module=__name__)


def assemble_hierarchy(
    concepts_paths: Sequence[str | Path],
    output_path: str | Path,
    *,
    settings: Settings | None = None,
    metadata_path: str | Path | None = None,
    graph_export_path: str | Path | None = None,
    graph_format: str = "json",
    validation_report_path: str | Path | None = None,
    orphan_report_path: str | Path | None = None,
    level_filter: int | None = None,
) -> HierarchyAssemblyResult:
    cfg = settings or Settings()
    if cfg.create_dirs:
        cfg.paths.ensure_exists()

    policy = cfg.policies.hierarchy_assembly
    concepts = load_concepts(concepts_paths, level_filter=level_filter)
    assembler = HierarchyAssembler(policy=policy)
    config_snapshot = {
        "environment": cfg.environment,
        "policy_version": cfg.policies.policy_version,
        "hierarchy_policy": policy.model_dump(mode="json"),
    }

    with logging_context(step="hierarchy-assembly", run_id="N/A"):
        result = assembler.run(concepts, config_snapshot=config_snapshot)

    write_hierarchy_manifest(result.manifest, output_path)
    if metadata_path:
        metadata = generate_hierarchy_metadata(
            result.graph.statistics(),
            config_snapshot,
            result.validation_report,
        )
        serialize_json(metadata, metadata_path)
    if graph_export_path:
        export_graph_structure(
            result.graph,
            graph_export_path,
            format=graph_format,
        )
    if validation_report_path:
        write_validation_report(result.validation_report, validation_report_path)
    if orphan_report_path:
        write_orphan_report(result.orphans, orphan_report_path)
    stats_path = Path(output_path).with_suffix(".stats.json")
    write_hierarchy_statistics(result.graph.statistics(), stats_path)

    _LOGGER.info(
        "Hierarchy assembly completed",
        manifest=str(Path(output_path).resolve()),
        nodes=result.graph.statistics().get("node_count", 0),
    )
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Assemble validated concepts into a production-ready hierarchy",
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Concept JSONL files produced by post-processing stages",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Destination path for the hierarchy manifest JSON",
    )
    parser.add_argument(
        "--metadata",
        help="Optional metadata output capturing processing statistics",
    )
    parser.add_argument(
        "--graph",
        help="Optional path for exporting the assembled graph structure",
    )
    parser.add_argument(
        "--graph-format",
        default="json",
        choices=["json", "adjacency", "dot"],
        help="Format used when exporting the graph structure",
    )
    parser.add_argument(
        "--validation-report",
        help="Optional path for writing the validation report JSON",
    )
    parser.add_argument(
        "--orphans",
        help="Optional path for writing orphan analysis output",
    )
    parser.add_argument(
        "--level-filter",
        type=int,
        choices=[0, 1, 2, 3],
        help="Restrict processing to a single hierarchy level",
    )
    parser.add_argument(
        "--environment",
        choices=["development", "testing", "production"],
        default=None,
        help="Override the runtime environment used to load configuration",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load concepts and validate invariants without writing outputs",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    settings_kwargs = {}
    if args.environment:
        settings_kwargs["environment"] = args.environment
    cfg = Settings(**settings_kwargs)

    result = assemble_hierarchy(
        args.inputs,
        args.output,
        settings=cfg,
        metadata_path=args.metadata,
        graph_export_path=args.graph,
        graph_format=args.graph_format,
        validation_report_path=args.validation_report,
        orphan_report_path=args.orphans,
        level_filter=args.level_filter,
    )

    if args.dry_run:
        _LOGGER.info(
            "Dry run requested - removing generated artefacts",
            manifest=args.output,
        )
        cleanup_candidates = [
            Path(args.output),
            Path(args.output).with_suffix(".stats.json"),
        ]
        if args.metadata:
            cleanup_candidates.append(Path(args.metadata))
        if args.graph:
            cleanup_candidates.append(Path(args.graph))
        if args.validation_report:
            cleanup_candidates.append(Path(args.validation_report))
        if args.orphans:
            cleanup_candidates.append(Path(args.orphans))
        for path in cleanup_candidates:
            path.unlink(missing_ok=True)
    return 0 if result.validation_report.passed else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
