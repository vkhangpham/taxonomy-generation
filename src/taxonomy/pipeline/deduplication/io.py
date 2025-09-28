"""Input/output helpers for the deduplication pipeline."""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, Sequence, TextIO

from taxonomy.entities.core import Concept, MergeOp
from taxonomy.utils.helpers import ensure_directory

try:  # pragma: no cover - optional dependency for remote filesystems
    import fsspec
except ImportError:  # pragma: no cover
    fsspec = None


def load_concepts(path: str | Path, level_filter: int | None = None) -> Iterator[Concept]:
    """Yield concepts from a JSONL file, optionally filtering by level."""

    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            concept = Concept.model_validate(payload)
            if level_filter is not None and concept.level != level_filter:
                continue
            yield concept


def _is_remote_path(destination: str | Path) -> bool:
    """Return ``True`` when *destination* requires fsspec for IO."""

    dest_str = str(destination)
    if len(dest_str) >= 3 and dest_str[1] == ":" and dest_str[2] in {"/", "\\"}:
        # Windows drive letter paths like C:\foo
        return False
    return "://" in dest_str and not dest_str.startswith("file://")


def is_remote_path(destination: str | Path) -> bool:
    """Public helper to determine whether the destination is remote."""

    return _is_remote_path(destination)


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


def _atomic_write(
    destination: str | Path,
    writer,
    *,
    mode: str = "w",
    encoding: str = "utf-8",
) -> str | Path:
    """Write using a temporary file before atomically replacing the destination."""

    coerced = _coerce_destination(destination)
    if is_remote_path(destination):
        with _open_output(destination, mode, encoding=encoding) as handle:
            writer(handle)
        return coerced

    from tempfile import NamedTemporaryFile  # Imported lazily to avoid unused deps.
    import os

    path = Path(str(destination)).expanduser()
    ensure_directory(path.parent)

    tmp_path: Path | None = None
    tmp_handle = NamedTemporaryFile(
        mode=mode,
        encoding=encoding,
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        tmp_path = Path(tmp_handle.name)
        try:
            writer(tmp_handle)
            tmp_handle.flush()
            os.fsync(tmp_handle.fileno())
        finally:
            tmp_handle.close()
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except FileNotFoundError:  # pragma: no cover - race during cleanup
                pass
        raise

    return coerced

def write_deduplicated_concepts(concepts: Sequence[Concept], destination: str | Path) -> str | Path:
    """Write deduplicated concepts to JSONL."""

    def _writer(handle: TextIO) -> None:
        for concept in concepts:
            payload = json.dumps(concept.model_dump(mode="json"), sort_keys=True)
            handle.write(payload)
            handle.write("\n")

    return _atomic_write(destination, _writer)


def write_merge_operations(merge_ops: Sequence[MergeOp], destination: str | Path) -> str | Path:
    """Persist merge operation logs to JSONL."""

    def _writer(handle: TextIO) -> None:
        for op in merge_ops:
            payload = json.dumps(op.model_dump(mode="json"), sort_keys=True)
            handle.write(payload)
            handle.write("\n")

    return _atomic_write(destination, _writer)


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

    def _writer(handle: TextIO) -> None:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    return _atomic_write(destination, _writer)


__all__ = [
    "load_concepts",
    "write_deduplicated_concepts",
    "write_merge_operations",
    "generate_dedup_metadata",
    "write_metadata",
    "is_remote_path",
]
