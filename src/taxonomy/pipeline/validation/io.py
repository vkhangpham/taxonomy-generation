"""I/O utilities for the validation pipeline."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, List, Optional, Sequence

from ...entities.core import Concept, PageSnapshot, ValidationFinding
from ...utils.helpers import ensure_directory


def load_concepts(
    input_path: str | Path,
    *,
    level_filter: Optional[int] = None,
) -> Iterator[Concept]:
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Concept file not found: {path}")

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            concept = Concept.model_validate(payload)
            if level_filter is not None and concept.level != level_filter:
                continue
            yield concept


def load_snapshots(
    snapshot_paths: Sequence[str | Path],
    *,
    institution_filter: Optional[str] = None,
) -> List[PageSnapshot]:
    snapshots: List[PageSnapshot] = []
    for item in snapshot_paths:
        path = Path(item)
        if not path.exists():
            raise FileNotFoundError(f"Snapshot file not found: {path}")
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                snapshot = PageSnapshot.model_validate(payload)
                if institution_filter and snapshot.institution != institution_filter:
                    continue
                snapshots.append(snapshot)
    return snapshots


def write_validated_concepts(
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


def write_validation_findings(
    findings: Iterable[ValidationFinding],
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        for finding in findings:
            handle.write(json.dumps(finding.model_dump(mode="json", exclude_none=True)))
            handle.write("\n")
    return path.resolve()


def export_evidence_samples(
    evidence_data: Sequence[dict],
    output_path: str | Path,
) -> Path:
    path = Path(output_path)
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(evidence_data, handle, indent=2)
    return path.resolve()


def generate_validation_metadata(
    processing_stats: dict,
    config_used: dict,
    validation_decisions: dict,
) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": dict(processing_stats),
        "validation": dict(validation_decisions),
        "config": dict(config_used),
    }


__all__ = [
    "load_concepts",
    "load_snapshots",
    "write_validated_concepts",
    "write_validation_findings",
    "export_evidence_samples",
    "generate_validation_metadata",
]
