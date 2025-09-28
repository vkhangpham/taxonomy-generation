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

    def _normalize_input_path(raw: str | Path | None) -> str | Path | None:
        """Coerce ``raw`` into a ``Path`` when it represents a local location."""

        if raw is None:
            return None
        if isinstance(raw, Path):
            return raw
        if is_remote_path(raw):
            return raw
        return Path(raw)

    def _canonicalize_output(raw: str | Path) -> str | Path:
        """Expand user paths and resolve local outputs to absolute ``Path`` objects."""

        if is_remote_path(raw):
            return str(raw)
        path = raw if isinstance(raw, Path) else Path(raw)
        path = path.expanduser()
        return path.resolve()

    def _swap_suffix(raw: str | Path, new_suffix: str) -> str | Path:
        """Replace the suffix for local paths while preserving remotes."""

        if is_remote_path(raw):
            raw_str = str(raw)
            slash_index = raw_str.rfind("/")
            dot_index = raw_str.rfind(".")
            if dot_index > slash_index:
                return raw_str[:dot_index] + new_suffix
            return raw_str + new_suffix
        path = raw if isinstance(raw, Path) else Path(raw)
        return path.with_suffix(new_suffix)

    def _ensure_local_directory(target: str | Path, label: str) -> None:
        """Ensure the parent directory for *target* exists when it is local."""

        if not isinstance(target, Path):
            return
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _LOGGER.exception(
                "Failed to create output directory",
                target=label,
                destination=str(target),
                error=str(exc),
            )
            raise

    def _cleanup_outputs(paths: list[tuple[str | Path, str]]) -> None:
        """Remove partially written outputs when a downstream step fails."""

        for output_path, label in paths:
            if is_remote_path(output_path):
                continue
            try:
                Path(output_path).unlink()
            except FileNotFoundError:
                continue
            except OSError as cleanup_err:
                _LOGGER.warning(
                    "Failed to clean up output after error",
                    target=label,
                    destination=str(output_path),
                    error=str(cleanup_err),
                )

    concepts_path = _normalize_input_path(concepts_path)
    output_path = _normalize_input_path(output_path)
    merge_ops_path = _normalize_input_path(merge_ops_path)
    metadata_path = _normalize_input_path(metadata_path)

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

    output_destination = _canonicalize_output(output_path)
    merge_target = merge_ops_path or _swap_suffix(output_destination, ".merge_ops.jsonl")
    merge_destination_target = _canonicalize_output(merge_target)
    metadata_target_raw = metadata_path or _swap_suffix(output_destination, ".metadata.json")
    metadata_target = _canonicalize_output(metadata_target_raw)

    try:
        _ensure_local_directory(output_destination, "deduplicated concepts")
        _ensure_local_directory(merge_destination_target, "merge operations")
        _ensure_local_directory(metadata_target, "metadata")
    except OSError:
        return

    written_outputs: list[tuple[str | Path, str]] = []

    try:
        destination = write_deduplicated_concepts(result.concepts, output_destination)
        written_outputs.append((destination, "deduplicated concepts"))
    except OSError as exc:
        _LOGGER.exception(
            "Failed to write deduplicated concepts",
            destination=str(output_destination),
            error=str(exc),
        )
        return

    try:
        merge_destination = write_merge_operations(result.merge_ops, merge_destination_target)
        written_outputs.append((merge_destination, "merge operations"))
    except OSError as exc:
        _LOGGER.exception(
            "Failed to write merge operations",
            destination=str(merge_destination_target),
            error=str(exc),
        )
        _cleanup_outputs(written_outputs)
        return

    policy_snapshot = policy.model_dump(mode="json")
    config_snapshot = {
        "policy_version": str(cfg.policies.policy_version),
        "merge_policy": policy_snapshot.get("merge_policy"),
        "thresholds": policy_snapshot.get("thresholds", {}),
        "weights": {
            "jaro_winkler_weight": policy_snapshot.get("jaro_winkler_weight"),
            "jaccard_weight": policy_snapshot.get("jaccard_weight"),
            "abbrev_score_weight": policy_snapshot.get("abbrev_score_weight"),
        },
        "blocking": {
            "prefix_length": policy_snapshot.get("prefix_length"),
            "phonetic_enabled": policy_snapshot.get("phonetic_enabled"),
            "acronym_blocking_enabled": policy_snapshot.get("acronym_blocking_enabled"),
        },
    }

    metadata_payload = generate_dedup_metadata(
        result.stats,
        config_snapshot,
        result.samples,
    )

    try:
        metadata_destination = write_metadata(metadata_payload, metadata_target)
        written_outputs.append((metadata_destination, "metadata"))
    except OSError as exc:
        _LOGGER.exception(
            "Failed to write metadata",
            destination=str(metadata_target),
            error=str(exc),
        )
        _cleanup_outputs(written_outputs)
        return

    _LOGGER.info(
        "Deduplication outputs written",
        concepts_path=str(destination),
        merge_ops_path=str(merge_destination),
        metadata_path=str(metadata_destination),
    )


def _build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser for the deduplication CLI.

    The parser accepts positional paths for the input concepts JSONL and the
    deduplicated output, alongside optional flags that configure the merge
    operations file, metadata destination, and level filter (0-3).
    """

    parser = argparse.ArgumentParser(description="Run the concept deduplication pipeline.")
    parser.add_argument("concepts", help="Path to input concepts JSONL (S3 output)")
    parser.add_argument("output", help="Destination JSONL for deduplicated concepts")
    parser.add_argument("--merge-ops", dest="merge_ops", help="Optional path for merge operations JSONL")
    parser.add_argument("--metadata", dest="metadata", help="Optional metadata JSON file")
    parser.add_argument(
        "--level",
        dest="level",
        type=int,
        choices=[0, 1, 2, 3],
        default=None,
        help="Optional level filter (must be 0, 1, 2, or 3)",
    )
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
