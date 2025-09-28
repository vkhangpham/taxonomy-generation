"""Entry points for the deduplication pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path
from taxonomy.config.settings import Settings, get_settings
from taxonomy.utils.logging import get_logger, logging_context

from .io import (
    generate_dedup_metadata,
    load_concepts,
    write_deduplicated_concepts,
    write_merge_operations,
    write_metadata,
)
from .processor import DeduplicationProcessor


_LOGGER = get_logger(module=__name__)


def deduplicate_concepts(
    concepts_path: str | Path,
    output_path: str | Path,
    *,
    merge_ops_path: str | Path | None = None,
    metadata_path: str | Path | None = None,
    level_filter: int | None = None,
    settings: Settings | None = None,
) -> None:
    """Run the deduplication pipeline end-to-end."""

    cfg = settings or get_settings()
    policy = cfg.policies.deduplication
    processor = DeduplicationProcessor(policy)

    concepts = load_concepts(concepts_path, level_filter=level_filter)
    _LOGGER.info(
        "Loaded concepts",
        count=len(concepts),
        level_filter=level_filter,
    )

    with logging_context(stage="dedup", level=level_filter or "all"):
        result = processor.process(concepts)

    destination = write_deduplicated_concepts(result.concepts, output_path)
    merge_destination = write_merge_operations(
        result.merge_ops,
        merge_ops_path or Path(output_path).with_suffix(".merge_ops.jsonl"),
    )

    metadata_target = metadata_path or Path(output_path).with_suffix(".metadata.json")
    config_snapshot = {
        "policy_version": cfg.policies.policy_version,
        "merge_policy": policy.merge_policy,
        "thresholds": policy.thresholds.model_dump(),
        "weights": {
            "jaro_winkler_weight": policy.jaro_winkler_weight,
            "jaccard_weight": policy.jaccard_weight,
            "abbrev_score_weight": policy.abbrev_score_weight,
        },
        "blocking": {
            "prefix_length": policy.prefix_length,
            "phonetic_enabled": policy.phonetic_enabled,
            "acronym_blocking_enabled": policy.acronym_blocking_enabled,
        },
    }
    metadata_payload = generate_dedup_metadata(
        result.stats,
        config_snapshot,
        result.samples,
    )
    metadata_destination = write_metadata(metadata_payload, metadata_target)

    _LOGGER.info(
        "Deduplication outputs written",
        concepts_path=str(destination),
        merge_ops_path=str(merge_destination),
        metadata_path=str(metadata_destination),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the concept deduplication pipeline")
    parser.add_argument("concepts", help="Path to input concepts JSONL (S3 output)")
    parser.add_argument("output", help="Destination JSONL for deduplicated concepts")
    parser.add_argument("--merge-ops", dest="merge_ops", help="Optional path for merge operations JSONL")
    parser.add_argument("--metadata", dest="metadata", help="Optional metadata JSON file")
    parser.add_argument("--level", dest="level", type=int, help="Optional level filter (0-3)")
    return parser


def main(argv: list[str] | None = None) -> None:  # pragma: no cover - CLI adaptor
    parser = _build_parser()
    args = parser.parse_args(argv)
    deduplicate_concepts(
        args.concepts,
        args.output,
        merge_ops_path=args.merge_ops,
        metadata_path=args.metadata,
        level_filter=args.level,
    )


__all__ = ["deduplicate_concepts", "main"]
