"""Input/output helpers for the deduplication pipeline."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence, TextIO

from taxonomy.entities.core import Concept, MergeOp
from taxonomy.utils.helpers import ensure_directory

try:  # pragma: no cover - optional dependency for remote filesystems
    import fsspec
except ImportError:  # pragma: no cover
    fsspec = None


def load_concepts(path: str | Path, level_filter: int | None = None) -> List[Concept]:
    """Load concepts from a JSONL file, optionally filtering by level."""

    concepts: List[Concept] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            concept = Concept.model_validate(payload)
            if level_filter is not None and concept.level != level_filter:
                continue
            concepts.append(concept)
    return concepts


def _is_remote_path(destination: str) -> bool:
    """Return ``True`` when *destination* requires fsspec for IO."""

    if len(destination) >= 3 and destination[1] == ":" and destination[2] in {"/", "\\"}:
        # Windows drive letter paths like C:\foo
        return False
    return "://" in destination and not destination.startswith("file://")


@contextmanager
def _open_output(destination: str | Path, mode: str = "w", *, encoding: str = "utf-8") -> Iterator[TextIO]:
    """Context manager that writes to local or remote destinations."""

    dest_str = str(destination)

    if _is_remote_path(dest_str):
        if fsspec is None:  # pragma: no cover - exercised only without optional deps
            raise RuntimeError(
                "fsspec is required to write to remote destinations",
            )
        with fsspec.open(dest_str, mode=mode, encoding=encoding, auto_mkdir=True) as handle:
            yield handle
        return

    path = Path(dest_str)
    ensure_directory(path.parent)
    with path.open(mode, encoding=encoding) as handle:
        yield handle


def _coerce_destination(destination: str | Path) -> str | Path:
    """Preserve caller-provided object type when practical."""

    if isinstance(destination, Path):
        return destination
    dest_str = str(destination)
    if _is_remote_path(dest_str):
        return dest_str
    return Path(dest_str)


def write_deduplicated_concepts(concepts: Sequence[Concept], destination: str | Path) -> str | Path:
    """Write deduplicated concepts to JSONL."""

    coerced = _coerce_destination(destination)
    with _open_output(destination, "w") as handle:
        for concept in concepts:
            payload = json.dumps(concept.model_dump(mode="json"), sort_keys=True)
            handle.write(payload)
            handle.write("\n")
    return coerced


def write_merge_operations(merge_ops: Sequence[MergeOp], destination: str | Path) -> str | Path:
    """Persist merge operation logs to JSONL."""

    coerced = _coerce_destination(destination)
    with _open_output(destination, "w") as handle:
        for op in merge_ops:
            payload = json.dumps(op.model_dump(mode="json"), sort_keys=True)
            handle.write(payload)
            handle.write("\n")
    return coerced


def generate_dedup_metadata(
    processing_stats: dict,
    config_used: dict,
    merge_samples: Iterable[dict],
) -> dict:
    """Create metadata payload describing the deduplication run."""

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": processing_stats,
        "config": config_used,
        "samples": list(merge_samples),
    }


def write_metadata(payload: dict, destination: str | Path) -> str | Path:
    """Write metadata payload to JSON using remote-aware IO."""

    coerced = _coerce_destination(destination)
    with _open_output(destination, "w") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return coerced


__all__ = [
    "load_concepts",
    "write_deduplicated_concepts",
    "write_merge_operations",
    "generate_dedup_metadata",
    "write_metadata",
]
