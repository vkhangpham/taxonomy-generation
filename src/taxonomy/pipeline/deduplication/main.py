"""Entry points for the deduplication pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path
from taxonomy.config.settings import Settings, get_settings
from taxonomy.utils.logging import get_logger, logging_context

from .io import (
    generate_dedup_metadata,
    is_remote_path,
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

    def _normalize_destination(raw: str | Path) -> str | Path:
        """Expand local paths and ensure their parent directory exists."""

        if is_remote_path(raw):
            return str(raw)
        path = Path(raw).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _swap_suffix(raw: str | Path, new_suffix: str) -> str | Path:
        """Replace the suffix for local paths while preserving remotes."""

        if is_remote_path(raw):
            raw_str = str(raw)
            slash_index = raw_str.rfind("/")
            dot_index = raw_str.rfind(".")
            if dot_index > slash_index:
                return raw_str[:dot_index] + new_suffix
            return raw_str + new_suffix
        return Path(raw).with_suffix(new_suffix)

    concept_stream = load_concepts(concepts_path, level_filter=level_filter)

    with logging_context(stage="dedup", level=level_filter or "all"):
        result = processor.process(concept_stream)

    stats_input = result.stats.get("input", {})
    _LOGGER.info(
        "Loaded concepts",
        count=stats_input.get("total_concepts", 0),
        unique_concepts=stats_input.get("unique_concepts", 0),
        level_filter=level_filter,
    )

    output_destination = _normalize_destination(output_path)
    merge_target = merge_ops_path or _swap_suffix(output_destination, ".merge_ops.jsonl")
    merge_destination_target = _normalize_destination(merge_target)
    metadata_target_raw = metadata_path or _swap_suffix(output_destination, ".metadata.json")
    metadata_target = _normalize_destination(metadata_target_raw)

    destination = write_deduplicated_concepts(result.concepts, output_destination)
    merge_destination = write_merge_operations(result.merge_ops, merge_destination_target)

    config_snapshot = {
        "policy_version": cfg.policies.policy_version,
        "merge_policy": policy.merge_policy,
        "thresholds": policy.thresholds.model_dump(mode="json"),
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
    """Build the argument parser for the deduplication CLI.

    The parser expects positional paths for `concepts` and `output` along with
    optional `--merge-ops`, `--metadata`, and `--level` flags to control run
    destinations and filtering.
    """

    parser = argparse.ArgumentParser(description="Run the concept deduplication pipeline.")
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
