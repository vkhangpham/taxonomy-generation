"""Streaming I/O helpers for the S1 extraction pipeline."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, List

from taxonomy.entities.core import Candidate, SourceRecord
from taxonomy.utils.helpers import ensure_directory


def load_source_records(
    input_path: str | Path,
    *,
    level_filter: int | None = None,
) -> Iterator[SourceRecord]:
    """Yield :class:`SourceRecord` instances from a JSONL file."""

    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Source records not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            record = SourceRecord.model_validate(payload)
            if level_filter is not None:
                hint_level = (
                    record.meta.hints.get("level")
                    or record.meta.hints.get("target_level")
                )
                if hint_level is not None and int(hint_level) != level_filter:
                    continue
            yield record


def write_candidates(candidates: Iterable[Candidate], output_path: str | Path) -> Path:
    """Write candidates to *output_path* in JSONL format."""

    path = Path(output_path)
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for candidate in candidates:
            handle.write(json.dumps(candidate.model_dump(), sort_keys=True))
            handle.write("\n")
    return path.resolve()


def generate_metadata(processing_stats: dict, config_used: dict) -> dict:
    """Return a metadata document describing the processing run."""

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": dict(processing_stats),
        "config": dict(config_used),
    }


__all__ = [
    "load_source_records",
    "write_candidates",
    "generate_metadata",
]
