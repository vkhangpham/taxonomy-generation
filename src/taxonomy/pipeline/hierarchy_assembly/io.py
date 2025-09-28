"""I/O utilities for hierarchy assembly."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence

from taxonomy.entities.core import Concept
from taxonomy.utils.helpers import ensure_directory, serialize_json
from taxonomy.utils.logging import get_logger

from .graph import HierarchyGraph
from .validator import ValidationReport

_LOGGER = get_logger(module=__name__)


def load_concepts(
    input_paths: Sequence[str | Path],
    *,
    level_filter: int | None = None,
) -> List[Concept]:
    concepts: List[Concept] = []
    for path_like in input_paths:
        path = Path(path_like)
        if not path.exists():
            raise FileNotFoundError(f"concept file not found: {path}")
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                concept = Concept.model_validate(payload)
                if level_filter is not None and concept.level != level_filter:
                    continue
                concepts.append(concept)
    _LOGGER.info(
        "Loaded concepts for hierarchy assembly",
        total=len(concepts),
        files=[str(Path(p)) for p in input_paths],
    )
    return concepts


def write_hierarchy_manifest(manifest: dict, output_path: str | Path) -> Path:
    path = Path(output_path)
    ensure_directory(path.parent)
    serialize_json(manifest, path)
    _LOGGER.info("Wrote hierarchy manifest", path=str(path))
    return path.resolve()


def export_graph_structure(
    graph: HierarchyGraph,
    output_path: str | Path,
    *,
    format: str = "json",
) -> Path:
    path = Path(output_path)
    ensure_directory(path.parent)
    format = format.lower()
    if format == "json":
        payload = {
            "nodes": [concept.id for concept in graph.concepts()],
            "edges": [
                {"parent": parent, "child": child}
                for parent, children in graph.adjacency().items()
                for child in children
            ],
        }
        serialize_json(payload, path)
    elif format == "adjacency":
        serialize_json(graph.adjacency(), path)
    elif format == "dot":
        lines = ["digraph hierarchy {"]
        for concept in graph.concepts():
            label = concept.canonical_label.replace("\"", "\\\"")
            lines.append(f'  "{concept.id}" [label="{label}"];')
        for parent, children in graph.adjacency().items():
            for child in children:
                lines.append(f'  "{parent}" -> "{child}";')
        lines.append("}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        raise ValueError(f"unsupported graph export format: {format}")
    _LOGGER.info(
        "Exported hierarchy graph",
        path=str(path),
        format=format,
    )
    return path.resolve()


def write_hierarchy_statistics(stats: dict, output_path: str | Path) -> Path:
    path = Path(output_path)
    ensure_directory(path.parent)
    serialize_json(stats, path)
    return path.resolve()


def write_validation_report(report: ValidationReport, output_path: str | Path) -> Path:
    return write_hierarchy_statistics(report.to_dict(), output_path)


def write_orphan_report(orphans: Iterable[dict], output_path: str | Path) -> Path:
    path = Path(output_path)
    ensure_directory(path.parent)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "orphans": list(orphans),
    }
    serialize_json(payload, path)
    return path.resolve()


def generate_hierarchy_metadata(
    assembly_stats: dict,
    config_used: dict,
    validation_report: ValidationReport,
) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": dict(assembly_stats),
        "config": dict(config_used),
        "validation": validation_report.to_dict(),
    }


__all__ = [
    "load_concepts",
    "write_hierarchy_manifest",
    "export_graph_structure",
    "write_hierarchy_statistics",
    "write_validation_report",
    "write_orphan_report",
    "generate_hierarchy_metadata",
]
