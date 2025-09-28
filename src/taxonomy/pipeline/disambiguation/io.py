"""I/O helpers for the disambiguation pipeline."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

from ...entities.core import Concept, SourceRecord, SplitOp
from ...utils.helpers import ensure_directory


def load_concepts(
    input_path: str | Path,
    *,
    level_filter: Optional[int] = None,
    skip_ids: Optional[Sequence[str]] = None,
) -> Iterator[Concept]:
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Concept file not found: {path}")

    skip = set(skip_ids or [])
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            concept = Concept.model_validate(payload)
            if level_filter is not None and concept.level != level_filter:
                continue
            if skip and concept.id in skip:
                continue
            yield concept


def write_disambiguated_concepts(
    concepts: Iterable[Concept],
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for concept in concepts:
            handle.write(json.dumps(concept.model_dump(mode="json", exclude_none=True)))
            handle.write("\n")
    return path.resolve()


def write_split_operations(
    split_ops: Iterable[SplitOp],
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for op in split_ops:
            handle.write(json.dumps(op.model_dump(mode="json", exclude_none=True)))
            handle.write("\n")
    return path.resolve()


def load_context_data(context_path: str | Path | None) -> Dict[str, List[SourceRecord]]:
    if context_path is None:
        return {}
    path = Path(context_path)
    if not path.exists():
        raise FileNotFoundError(f"Context data file not found: {path}")

    mapping: Dict[str, List[SourceRecord]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            concept_id = payload.get("concept_id")
            if not concept_id:
                continue
            raw_records: Sequence[Mapping[str, object]] = []
            if "record" in payload:
                raw_records = [payload["record"]]
            elif "records" in payload:
                raw_records = payload["records"] or []
            records: List[SourceRecord] = mapping.setdefault(concept_id, [])
            for record_payload in raw_records:
                if not isinstance(record_payload, Mapping):
                    continue
                record = SourceRecord.model_validate(record_payload)
                records.append(record)
    return mapping


def generate_disambiguation_metadata(
    processing_stats: Mapping[str, int],
    config_used: Mapping[str, object],
    split_decisions: Mapping[str, Sequence[str]],
) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": dict(processing_stats),
        "splits": {key: list(value) for key, value in split_decisions.items()},
        "config": dict(config_used),
    }


__all__ = [
    "load_concepts",
    "write_disambiguated_concepts",
    "write_split_operations",
    "load_context_data",
    "generate_disambiguation_metadata",
]
