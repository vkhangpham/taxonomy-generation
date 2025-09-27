"""Persistence utilities for S0 raw extraction outputs."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Iterable, List, Sequence

from ...entities.core import SourceRecord
from ...utils import ensure_directory, get_logger, serialize_json


class RecordWriter:
    """Helper responsible for writing SourceRecords and metadata."""

    def __init__(self) -> None:
        self._logger = get_logger(module=__name__)

    def write_jsonl(
        self,
        records: Iterable[SourceRecord],
        output_path: Path | str,
        *,
        compress: bool | None = None,
    ) -> Path:
        path = Path(output_path)

        if compress is None:
            compress = path.suffix.endswith(".gz")

        if compress and not str(path).endswith(".gz"):
            adjusted_path = Path(f"{path}.gz")
            self._logger.debug(
                "Adjusting compressed output path to .gz suffix",
                original=str(path),
                adjusted=str(adjusted_path),
            )
            path = adjusted_path

        ensure_directory(path.parent)

        temp_path = path.with_suffix(path.suffix + ".tmp")
        writer = gzip.open if compress else open
        mode = "wt"

        with writer(temp_path, mode, encoding="utf-8") as handle:
            count = 0
            for record in records:
                payload = json.dumps(record.model_dump(mode="json"), ensure_ascii=False)
                handle.write(payload)
                handle.write("\n")
                count += 1

        temp_path.replace(path)
        self._logger.info("Wrote SourceRecords", path=str(path), count=count, compress=compress)
        return path

    def write_batch(
        self,
        records: Sequence[SourceRecord] | Iterable[SourceRecord],
        output_dir: Path | str,
        *,
        batch_size: int = 1000,
        prefix: str = "records",
    ) -> List[Path]:
        path = Path(output_dir)
        ensure_directory(path)
        batch: List[SourceRecord] = []
        written_paths: List[Path] = []
        total_count = 0

        def flush(current_batch: List[SourceRecord]) -> None:
            nonlocal total_count
            if not current_batch:
                return
            current_size = len(current_batch)
            file_index = len(written_paths) + 1
            file_path = path / f"{prefix}_{file_index:05d}.jsonl"
            written_paths.append(self.write_jsonl(current_batch, file_path))
            total_count += current_size
            current_batch.clear()

        for record in records:
            batch.append(record)
            if len(batch) >= batch_size:
                current = batch
                batch = []
                flush(current)

        if batch:
            flush(batch)

        self._logger.info(
            "Wrote batched SourceRecords",
            directory=str(path),
            batches=len(written_paths),
            total=total_count,
        )
        return written_paths

    def write_metadata(self, stats: dict, output_path: Path | str) -> Path:
        path = Path(output_path)
        ensure_directory(path.parent)
        result = serialize_json(stats, path)
        self._logger.info("Wrote processing metadata", path=str(result))
        return result


__all__ = ["RecordWriter"]
