"""Public entry points for S2 frequency filtering."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from taxonomy.config.settings import Settings, get_settings
from taxonomy.utils.helpers import ensure_directory
from taxonomy.utils.logging import get_logger, logging_context

from .aggregator import CandidateAggregator, FrequencyAggregationResult
from .institution_resolver import InstitutionResolver
from .io import (
    CandidateEvidence,
    generate_s2_metadata,
    load_candidates,
    write_dropped_candidates,
    write_kept_candidates,
)
from .processor import S2Processor


def filter_by_frequency(
    candidates_path: str | Path,
    *,
    level: int,
    output_path: str | Path,
    dropped_output_path: str | Path | None = None,
    metadata_path: str | Path | None = None,
    settings: Settings | None = None,
) -> FrequencyAggregationResult:
    """Run S2 frequency filtering end-to-end and write streaming outputs."""

    cfg = settings or get_settings()
    log = get_logger(module=__name__)

    resolver = InstitutionResolver(policy=cfg.policies.institution_policy)
    aggregator = CandidateAggregator(
        thresholds=cfg.policies.level_thresholds,
        resolver=resolver,
    )
    processor = S2Processor(aggregator=aggregator)

    evidence_stream: Iterable[CandidateEvidence] = load_candidates(
        candidates_path,
        level_filter=level,
    )

    with logging_context(stage="s2", level=level):
        result = processor.process(evidence_stream)

    kept_path = write_kept_candidates(result.kept, output_path)
    dropped_path = dropped_output_path or Path(output_path).with_suffix(".dropped.jsonl")
    dropped_path = write_dropped_candidates(result.dropped, dropped_path)

    metadata_destination = metadata_path or Path(output_path).with_suffix(".metadata.json")
    threshold_decisions = _threshold_metadata(cfg)
    config_used = {
        "policy_version": cfg.policies.policy_version,
        "level": level,
    }
    metadata = generate_s2_metadata(result.stats, config_used, threshold_decisions)
    ensure_directory(Path(metadata_destination).parent)
    Path(metadata_destination).write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    log.info(
        "S2 frequency filtering complete",
        kept=result.stats.get("kept", 0),
        dropped=result.stats.get("dropped", 0),
        kept_path=str(kept_path),
        dropped_path=str(dropped_path),
    )
    return result


def _threshold_metadata(settings: Settings) -> dict:
    thresholds = settings.policies.level_thresholds
    return {
        "level_0": {
            "min_institutions": thresholds.level_0.min_institutions,
            "min_src_count": thresholds.level_0.min_src_count,
            "weight_formula": thresholds.level_0.weight_formula,
        },
        "level_1": {
            "min_institutions": thresholds.level_1.min_institutions,
            "min_src_count": thresholds.level_1.min_src_count,
            "weight_formula": thresholds.level_1.weight_formula,
        },
        "level_2": {
            "min_institutions": thresholds.level_2.min_institutions,
            "min_src_count": thresholds.level_2.min_src_count,
            "weight_formula": thresholds.level_2.weight_formula,
        },
        "level_3": {
            "min_institutions": thresholds.level_3.min_institutions,
            "min_src_count": thresholds.level_3.min_src_count,
            "weight_formula": thresholds.level_3.weight_formula,
        },
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run S2 frequency filtering")
    parser.add_argument("candidates", help="Path to S1 candidates JSONL")
    parser.add_argument("output", help="Destination JSONL for kept candidates")
    parser.add_argument("--level", type=int, required=True, help="Hierarchy level (0-3)")
    parser.add_argument(
        "--dropped-output",
        dest="dropped_output",
        help="Optional JSONL path for dropped candidates",
    )
    parser.add_argument(
        "--metadata",
        dest="metadata",
        help="Optional metadata output path",
    )
    return parser


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - CLI glue
    parser = _build_parser()
    args = parser.parse_args(argv)
    filter_by_frequency(
        args.candidates,
        level=args.level,
        output_path=args.output,
        dropped_output_path=args.dropped_output,
        metadata_path=args.metadata,
    )


__all__ = ["filter_by_frequency", "main"]
