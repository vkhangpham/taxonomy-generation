"""Persistence utilities for S0 raw extraction outputs."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Iterable, List, Sequence

from ...entities.core import SourceRecord
from ...utils import chunked, ensure_directory, get_logger, serialize_json


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
        ensure_directory(path.parent)

        if compress is None:
            compress = path.suffix.endswith(".gz")

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
        records_list = list(records)
        if not records_list:
            return []
        batches = list(chunked(records_list, batch_size))
        written_paths: List[Path] = []
        for idx, batch in enumerate(batches, start=1):
            file_path = path / f"{prefix}_{idx:05d}.jsonl"
            written_paths.append(self.write_jsonl(batch, file_path))
        self._logger.info(
            "Wrote batched SourceRecords",
            directory=str(path),
            batches=len(written_paths),
            total=len(records_list),
        )
        return written_paths

    def write_metadata(self, stats: dict, output_path: Path | str) -> Path:
        path = Path(output_path)
        ensure_directory(path.parent)
        result = serialize_json(stats, path)
        self._logger.info("Wrote processing metadata", path=str(result))
        return result


__all__ = ["RecordWriter"]
