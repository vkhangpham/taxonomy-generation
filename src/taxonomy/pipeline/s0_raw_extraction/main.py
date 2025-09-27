"""Entry points for running the S0 raw extraction pipeline."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Iterator, Sequence

try:  # pragma: no cover - optional dependency
    from tqdm import tqdm
except ImportError:  # pragma: no cover
    tqdm = None  # type: ignore

from ...config.settings import Settings, get_settings
from ...entities.core import PageSnapshot, SourceRecord
from ...utils import ensure_directory, get_logger
from .loader import SnapshotLoader, SnapshotRecord
from .processor import RawExtractionProcessor
from .segmenter import ContentSegmenter
from .writer import RecordWriter


def extract_from_snapshots(
    snapshot_source: str | Path | Iterable[PageSnapshot | SnapshotRecord],
    output_path: str | Path,
    settings: Settings | None = None,
    *,
    batch_size: int = 1000,
    compress: bool | None = None,
) -> dict:
    """Run the raw extraction pipeline end-to-end and persist SourceRecords."""

    settings = settings or get_settings()
    logger = get_logger(module=__name__)

    if settings.create_dirs:
        settings.paths.ensure_exists()

    loader = SnapshotLoader(settings=settings)
    segmenter = ContentSegmenter(settings.policies.raw_extraction)
    processor = RawExtractionProcessor(
        settings.policies.raw_extraction,
        segmenter,
        quarantine_path=loader.quarantine_file,
    )
    writer = RecordWriter()

    snapshot_iter = _resolve_snapshot_iter(snapshot_source, loader)

    iterable: Iterable[SnapshotRecord] = snapshot_iter
    if tqdm is not None:
        iterable = tqdm(iterable, desc="Snapshots", unit="page")

    records_iter = processor.process_many(iterable)

    produced_records = False

    def record_stream() -> Iterable[SourceRecord]:
        nonlocal produced_records
        for record in records_iter:
            produced_records = True
            yield record

    output_path = Path(output_path)
    ensure_directory(output_path.parent if output_path.suffix else output_path)

    if output_path.suffix:
        records_location = writer.write_jsonl(record_stream(), output_path, compress=compress)
    else:
        records_location = writer.write_batch(record_stream(), output_path, batch_size=batch_size)

    if not produced_records:
        logger.warning("No SourceRecords generated", output=str(output_path))

    stats_path = output_path if isinstance(records_location, Path) else Path(output_path)
    if isinstance(records_location, list):
        stats_target = stats_path / "extraction.stats.json"
    else:
        stats_target = stats_path.with_suffix(stats_path.suffix + ".stats.json")

    metadata = {
        "processor": processor.metrics.as_dict(),
        "loader": loader.metrics.as_dict(),
        "settings_version": settings.policy_version,
    }
    writer.write_metadata(metadata, stats_target)

    result = {
        "records": records_location,
        "metadata": stats_target,
        "metrics": metadata,
    }
    logger.info(
        "Completed raw extraction",
        records=str(records_location),
        meta=str(stats_target),
        pages=processor.metrics.pages_seen,
        emitted=processor.metrics.pages_emitted,
    )
    return result


def _resolve_snapshot_iter(
    snapshot_source: str | Path | Iterable[PageSnapshot | SnapshotRecord],
    loader: SnapshotLoader,
) -> Iterator[SnapshotRecord]:
    if isinstance(snapshot_source, (str, Path)):
        path = Path(snapshot_source)
        if path.is_dir():
            return loader.filter_snapshots(loader.load_from_directory(path))
        return loader.filter_snapshots(loader.load_from_jsonl(path))

    def iterator() -> Iterator[SnapshotRecord]:
        for entry in snapshot_source:
            if isinstance(entry, SnapshotRecord):
                yield entry
            elif isinstance(entry, PageSnapshot):
                yield SnapshotRecord(snapshot=entry)
            else:
                raise TypeError(f"Unsupported snapshot source entry: {type(entry)!r}")

    return loader.validate_snapshots(iterator())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run S0 raw extraction over snapshots")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to a JSONL snapshot file or directory",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Destination JSONL file or directory for SourceRecords",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch size when writing to a directory output",
    )
    parser.add_argument(
        "--compress",
        action="store_true",
        help="Compress JSONL output using gzip",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> dict:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return extract_from_snapshots(
        args.input,
        args.output,
        batch_size=args.batch_size,
        compress=args.compress,
    )


if __name__ == "__main__":  # pragma: no cover - CLI invocation
    main()
