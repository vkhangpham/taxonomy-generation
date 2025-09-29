"""Coordinated audit execution of the level 0 taxonomy pipeline in audit mode.

This script orchestrates S0–S3 for level 0 using production settings while
forcing audit-mode sampling. It records stage timing, persists observability
snapshots, and verifies that each stage honours the configured audit limit.
"""

from __future__ import annotations

import argparse
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent
from time import perf_counter
from typing import Any, Iterable, Sequence

import yaml

from taxonomy.config.settings import Settings
from taxonomy.observability import ObservabilityContext
from taxonomy.pipeline.s0_raw_extraction import generate_source_records
from taxonomy.pipeline.s0_raw_extraction.main import extract_from_snapshots
from taxonomy.pipeline.s0_raw_extraction.writer import RecordWriter
from taxonomy.pipeline.s1_extraction_normalization.main import extract_candidates
from taxonomy.pipeline.s2_frequency_filtering.main import filter_by_frequency
from taxonomy.pipeline.s3_token_verification.main import verify_tokens
from taxonomy.utils.helpers import ensure_directory, serialize_json


DEFAULT_CONFIG_PATH = Path("audit_config.yaml")
DEFAULT_REQUIRED_ENV_VARS = ("OPENAI_API_KEY", "FIRECRAWL_API_KEY")
DEFAULT_AUDIT_LIMIT = 10


@dataclass
class StageResult:
    name: str
    duration_seconds: float
    outputs: dict[str, str] = field(default_factory=dict)
    metadata_path: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    audit_items: int = 0
    audit_limit: int = DEFAULT_AUDIT_LIMIT
    mode: str = "pipeline"
    started_at: str | None = None
    completed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        return {key: value for key, value in payload.items() if value is not None}


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute level 0 taxonomy stages (S0–S3) in audit mode.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to the YAML configuration overrides for audit runs.",
    )
    parser.add_argument(
        "--run-id",
        help="Optional run identifier; defaults to UTC timestamp.",
    )
    parser.add_argument(
        "--s0-mode",
        choices=("excel", "snapshots", "reuse"),
        default="excel",
        help="Source for S0 inputs: Excel bootstrap, raw snapshots, or an existing JSONL output.",
    )
    parser.add_argument(
        "--snapshots-path",
        type=Path,
        help="Path to snapshots JSONL or directory when --s0-mode=snapshots.",
    )
    parser.add_argument(
        "--existing-s0-path",
        type=Path,
        help="Path to pre-generated S0 source_records.jsonl when --s0-mode=reuse.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_AUDIT_LIMIT,
        help="Maximum number of items permitted per stage in audit mode.",
    )
    parser.add_argument(
        "--require-env",
        nargs="*",
        default=list(DEFAULT_REQUIRED_ENV_VARS),
        help="Environment variables that must be defined for production credentials.",
    )
    parser.add_argument(
        "--s0-batch-size",
        type=int,
        default=512,
        help="Batch size used when S0 writes batched outputs.",
    )
    parser.add_argument(
        "--s1-batch-size",
        type=int,
        default=32,
        help="Batch size for S1 extraction batches.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (e.g. INFO, DEBUG).",
    )
    return parser.parse_args(argv)


def _load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Audit configuration not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(
            f"Audit configuration '{path}' must contain a mapping at the top level"
        )
    return loaded


def _initialise_settings(config_path: Path) -> Settings:
    overrides = _load_config(config_path)
    overrides.setdefault("create_dirs", True)
    audit_overrides = overrides.setdefault("audit_mode", {})
    audit_overrides["enabled"] = True
    overrides.setdefault("environment", "production")
    settings = Settings(**overrides)
    if not settings.audit_mode.enabled:
        settings.audit_mode.enabled = True
    return settings


def _configure_logging(log_dir: Path, run_id: str, level: str) -> Path:
    ensure_directory(log_dir)
    log_path = (Path(log_dir) / f"audit_run_{run_id}.log").resolve()
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    root_logger.addHandler(handler)
    root_logger.addHandler(stream_handler)
    return log_path


def _ensure_env_vars(required: Iterable[str]) -> None:
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        message = "\n".join(f"  - {item}" for item in missing)
        raise RuntimeError(
            dedent(
                f"""Missing required environment variables for production execution:\n{message}\n"""
            )
        )


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for _ in handle if _.strip())


def _verify_limit(stage: str, count: int, limit: int) -> None:
    if count > limit:
        raise RuntimeError(
            f"Stage {stage} exceeded the audit limit: {count} items observed (limit {limit})."
        )


def _run_s0_excel(
    *,
    settings: Settings,
    output_path: Path,
    limit: int,
) -> StageResult:
    logger = logging.getLogger("audit.s0.excel")
    stage_start = _timestamp()
    start = perf_counter()
    records = generate_source_records(settings=settings)
    truncated = records[:limit]
    writer = RecordWriter()
    record_path = writer.write_jsonl(truncated, output_path)
    metadata_payload = {
        "source": "excel_bootstrap",
        "workbook": str(settings.level0_excel_file.resolve()),
        "total_generated": len(records),
        "written": len(truncated),
        "audit_limit": limit,
        "audit_mode": True,
    }
    metadata_path = writer.write_metadata(
        metadata_payload,
        Path(f"{record_path}.stats.json"),
    )
    duration = perf_counter() - start
    stage_end = _timestamp()
    record_count = len(truncated)
    _verify_limit("S0", record_count, limit)
    logger.info(
        "S0 Excel bootstrap completed",
        extra={"records": record_count, "duration_seconds": duration},
    )
    return StageResult(
        name="S0",
        duration_seconds=duration,
        outputs={"records": str(record_path)},
        metadata_path=str(metadata_path),
        stats={
            "records_total": len(records),
            "records_written": record_count,
        },
        audit_items=record_count,
        audit_limit=limit,
        mode="excel_bootstrap",
        started_at=stage_start,
        completed_at=stage_end,
    )


def _run_s0_snapshots(
    *,
    settings: Settings,
    snapshots_path: Path,
    output_path: Path,
    limit: int,
    batch_size: int,
) -> StageResult:
    logger = logging.getLogger("audit.s0.snapshots")
    stage_start = _timestamp()
    start = perf_counter()
    result = extract_from_snapshots(
        snapshots_path,
        output_path,
        settings=settings,
        batch_size=batch_size,
        audit_mode=True,
    )
    duration = perf_counter() - start
    stage_end = _timestamp()
    record_paths = [str(Path(path)) for path in result.get("records", [])]
    metadata_path = result.get("metadata")
    record_count = 0
    if record_paths:
        record_count = _count_lines(Path(record_paths[0]))
    _verify_limit("S0", record_count, limit)
    logger.info(
        "S0 snapshot extraction completed",
        extra={"records": record_count, "duration_seconds": duration},
    )
    outputs: dict[str, str] = {}
    if record_paths:
        outputs["records"] = record_paths[0]
    return StageResult(
        name="S0",
        duration_seconds=duration,
        outputs=outputs,
        metadata_path=str(metadata_path) if metadata_path else None,
        stats=result.get("metrics", {}),
        audit_items=record_count,
        audit_limit=limit,
        mode="snapshots",
        started_at=stage_start,
        completed_at=stage_end,
    )


def _reuse_s0(existing_path: Path, limit: int) -> StageResult:
    logger = logging.getLogger("audit.s0.reuse")
    count = _count_lines(existing_path)
    _verify_limit("S0", count, limit)
    logger.info("Reusing existing S0 output", extra={"records": count})
    outputs: dict[str, str] = {"records": str(existing_path)}
    timestamp = _timestamp()
    return StageResult(
        name="S0",
        duration_seconds=0.0,
        outputs=outputs,
        metadata_path=None,
        stats={"records_written": count, "reused": True},
        audit_items=count,
        audit_limit=limit,
        mode="reuse",
        started_at=timestamp,
        completed_at=timestamp,
    )


def _run_s1(
    *,
    settings: Settings,
    observability: ObservabilityContext,
    source_records: Path,
    output_path: Path,
    metadata_path: Path,
    batch_size: int,
    limit: int,
) -> StageResult:
    logger = logging.getLogger("audit.s1")
    stage_start = _timestamp()
    start = perf_counter()
    candidates = extract_candidates(
        source_records,
        level=0,
        output_path=output_path,
        metadata_path=metadata_path,
        batch_size=batch_size,
        settings=settings,
        observability=observability,
        audit_mode=True,
    )
    duration = perf_counter() - start
    stage_end = _timestamp()
    candidate_count = len(candidates)
    _verify_limit("S1", candidate_count, limit)
    counters = observability.export().get("counters", {}).get("S1", {})
    logger.info(
        "S1 extraction completed",
        extra={"candidates": candidate_count, "duration_seconds": duration},
    )
    return StageResult(
        name="S1",
        duration_seconds=duration,
        outputs={"candidates": str(output_path)},
        metadata_path=str(metadata_path),
        stats={
            "candidates_emitted": candidate_count,
            "observability_counters": counters,
        },
        audit_items=candidate_count,
        audit_limit=limit,
        started_at=stage_start,
        completed_at=stage_end,
    )


def _run_s2(
    *,
    settings: Settings,
    observability: ObservabilityContext,
    candidates_path: Path,
    output_path: Path,
    dropped_path: Path,
    metadata_path: Path,
    limit: int,
) -> StageResult:
    logger = logging.getLogger("audit.s2")
    stage_start = _timestamp()
    start = perf_counter()
    result = filter_by_frequency(
        candidates_path,
        level=0,
        output_path=output_path,
        dropped_output_path=dropped_path,
        metadata_path=metadata_path,
        settings=settings,
        observability=observability,
        audit_mode=True,
    )
    duration = perf_counter() - start
    stage_end = _timestamp()
    kept_count = len(result.kept)
    _verify_limit("S2", kept_count, limit)
    counters = observability.export().get("counters", {}).get("S2", {})
    logger.info(
        "S2 frequency filtering completed",
        extra={"kept": kept_count, "duration_seconds": duration},
    )
    return StageResult(
        name="S2",
        duration_seconds=duration,
        outputs={
            "kept": str(output_path),
            "dropped": str(dropped_path),
        },
        metadata_path=str(metadata_path),
        stats={
            "kept": kept_count,
            "dropped": len(result.dropped),
            "aggregate_stats": result.stats,
            "observability_counters": counters,
        },
        audit_items=kept_count,
        audit_limit=limit,
        started_at=stage_start,
        completed_at=stage_end,
    )


def _run_s3(
    *,
    settings: Settings,
    candidates_path: Path,
    output_path: Path,
    failed_path: Path,
    metadata_path: Path,
    limit: int,
) -> StageResult:
    logger = logging.getLogger("audit.s3")
    stage_start = _timestamp()
    start = perf_counter()
    result = verify_tokens(
        candidates_path,
        level=0,
        output_path=output_path,
        failed_output_path=failed_path,
        metadata_path=metadata_path,
        settings=settings,
        audit_mode=True,
    )
    duration = perf_counter() - start
    stage_end = _timestamp()
    verified_count = len(result.verified)
    _verify_limit("S3", verified_count, limit)
    logger.info(
        "S3 token verification completed",
        extra={"verified": verified_count, "duration_seconds": duration},
    )
    return StageResult(
        name="S3",
        duration_seconds=duration,
        outputs={
            "verified": str(output_path),
            "failed": str(failed_path),
        },
        metadata_path=str(metadata_path),
        stats=result.stats,
        audit_items=verified_count,
        audit_limit=limit,
        started_at=stage_start,
        completed_at=stage_end,
    )


def _build_summary(
    *,
    run_id: str,
    config_path: Path,
    settings: Settings,
    stage_results: list[StageResult],
    observability_path: Path | None,
    log_path: Path,
    started_at: str,
    completed_at: str,
    required_env: Sequence[str],
    status: str,
    failure: dict[str, Any] | None,
) -> dict[str, Any]:
    summary = {
        "run_id": run_id,
        "config": str(config_path.resolve()),
        "started_at": started_at,
        "completed_at": completed_at,
        "environment": settings.environment,
        "audit_mode": settings.audit_mode.enabled,
        "audit_limit": (
            stage_results[0].audit_limit if stage_results else DEFAULT_AUDIT_LIMIT
        ),
        "output_dir": str(Path(settings.paths.output_dir).resolve()),
        "log_file": str(log_path),
        "observability_snapshot": (
            str(observability_path) if observability_path else None
        ),
        "policy_version": settings.policies.policy_version,
        "required_env": list(required_env),
        "stages": [stage.to_dict() for stage in stage_results],
        "status": status,
    }
    if failure:
        summary["failure"] = failure
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    settings = _initialise_settings(args.config)
    run_id = args.run_id or datetime.now(timezone.utc).strftime("audit-%Y%m%d-%H%M%S")
    log_path = _configure_logging(settings.paths.logs_dir, run_id, args.log_level)
    _ensure_env_vars(args.require_env)

    run_root = ensure_directory(Path(settings.paths.output_dir) / run_id)
    stage_dirs = {
        phase: ensure_directory(run_root / phase) for phase in ("S0", "S1", "S2", "S3")
    }

    logger = logging.getLogger("audit")
    started_at = _timestamp()
    stage_results: list[StageResult] = []
    observability: ObservabilityContext | None = None
    observability_snapshot: dict[str, Any] | None = None
    observability_path: Path | None = None
    current_stage: str | None = None
    failure: dict[str, Any] | None = None
    exit_code = 0

    try:
        current_stage = "S0"
        if args.s0_mode == "excel":
            s0_output = stage_dirs["S0"] / "source_records.jsonl"
            stage_results.append(
                _run_s0_excel(
                    settings=settings,
                    output_path=s0_output,
                    limit=args.limit,
                )
            )
            s0_records_path = s0_output
        elif args.s0_mode == "snapshots":
            if not args.snapshots_path:
                raise ValueError(
                    "--snapshots-path is required when --s0-mode=snapshots"
                )
            s0_output = stage_dirs["S0"] / "source_records.jsonl"
            stage_results.append(
                _run_s0_snapshots(
                    settings=settings,
                    snapshots_path=args.snapshots_path,
                    output_path=s0_output,
                    limit=args.limit,
                    batch_size=args.s0_batch_size,
                )
            )
            s0_records_path = s0_output
        else:
            if not args.existing_s0_path:
                raise ValueError("--existing-s0-path is required when --s0-mode=reuse")
            stage_results.append(_reuse_s0(args.existing_s0_path, args.limit))
            s0_records_path = args.existing_s0_path

        observability = ObservabilityContext(
            run_id=run_id,
            policy=settings.policies.observability,
        )

        current_stage = "S1"
        s1_output = stage_dirs["S1"] / "level0_candidates.jsonl"
        s1_metadata = stage_dirs["S1"] / "level0_candidates.metadata.json"
        stage_results.append(
            _run_s1(
                settings=settings,
                observability=observability,
                source_records=s0_records_path,
                output_path=s1_output,
                metadata_path=s1_metadata,
                batch_size=args.s1_batch_size,
                limit=args.limit,
            )
        )

        current_stage = "S2"
        s2_output = stage_dirs["S2"] / "level0_kept.jsonl"
        s2_dropped = stage_dirs["S2"] / "level0_dropped.jsonl"
        s2_metadata = stage_dirs["S2"] / "level0.metadata.json"
        stage_results.append(
            _run_s2(
                settings=settings,
                observability=observability,
                candidates_path=s1_output,
                output_path=s2_output,
                dropped_path=s2_dropped,
                metadata_path=s2_metadata,
                limit=args.limit,
            )
        )

        current_stage = "S3"
        s3_output = stage_dirs["S3"] / "level0_verified.jsonl"
        s3_failed = stage_dirs["S3"] / "level0_failed.jsonl"
        s3_metadata = stage_dirs["S3"] / "level0.metadata.json"
        stage_results.append(
            _run_s3(
                settings=settings,
                candidates_path=s2_output,
                output_path=s3_output,
                failed_path=s3_failed,
                metadata_path=s3_metadata,
                limit=args.limit,
            )
        )

        if observability:
            observability_snapshot = observability.export()
    except Exception as exc:  # noqa: BLE001
        exit_code = 1
        failure = {
            "stage": current_stage,
            "message": str(exc),
            "exception_type": exc.__class__.__name__,
        }
        logger.exception(
            "Audit run failed during %s", current_stage or "initialisation"
        )
    finally:
        if observability_snapshot is None:
            if observability is not None:
                try:
                    observability_snapshot = observability.export()
                except Exception as obs_exc:  # noqa: BLE001
                    logger.exception("Failed to export observability snapshot")
                    observability_snapshot = {
                        "error": "observability_export_failed",
                        "message": str(obs_exc),
                    }
            else:
                observability_snapshot = {"error": "observability_not_available"}

        observability_path = serialize_json(
            observability_snapshot,
            run_root / "observability_snapshot.json",
        )
        completed_at = _timestamp()
        summary = _build_summary(
            run_id=run_id,
            config_path=args.config,
            settings=settings,
            stage_results=stage_results,
            observability_path=observability_path,
            log_path=log_path,
            started_at=started_at,
            completed_at=completed_at,
            required_env=args.require_env,
            status="failed" if failure else "success",
            failure=failure,
        )
        serialize_json(summary, run_root / "audit_run_summary.json")

    if failure:
        logger.error(
            "Audit run failed",
            extra={"run_id": run_id, "stage": failure.get("stage")},
        )
        return exit_code

    logger.info("Audit run complete", extra={"run_id": run_id})
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
