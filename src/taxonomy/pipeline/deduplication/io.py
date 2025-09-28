"""Input/output helpers for the deduplication pipeline."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Sequence

from taxonomy.entities.core import Concept, MergeOp
from taxonomy.utils.helpers import ensure_directory


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


def write_deduplicated_concepts(concepts: Sequence[Concept], destination: str | Path) -> Path:
    """Write deduplicated concepts to JSONL."""

    dest = Path(destination)
    ensure_directory(dest.parent)
    with dest.open("w", encoding="utf-8") as handle:
        for concept in concepts:
            handle.write(json.dumps(concept.model_dump(mode="json"), sort_keys=True) + "\n")
    return dest


def write_merge_operations(merge_ops: Sequence[MergeOp], destination: str | Path) -> Path:
    """Persist merge operation logs to JSONL."""

    dest = Path(destination)
    ensure_directory(dest.parent)
    with dest.open("w", encoding="utf-8") as handle:
        for op in merge_ops:
            handle.write(json.dumps(op.model_dump(mode="json"), sort_keys=True) + "\n")
    return dest


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


__all__ = [
    "load_concepts",
    "write_deduplicated_concepts",
    "write_merge_operations",
    "generate_dedup_metadata",
]
