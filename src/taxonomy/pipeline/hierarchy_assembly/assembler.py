"""Hierarchy assembly orchestrator that coordinates graph construction and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Tuple

from taxonomy.config.policies import HierarchyAssemblyPolicy
from taxonomy.entities.core import Concept
from taxonomy.utils.logging import get_logger

from .graph import HierarchyGraph
from .validator import GraphValidator, InvariantChecker, ValidationReport

_LOGGER = get_logger(module=__name__)


@dataclass(slots=True)
class HierarchyAssemblyResult:
    """Materialised results returned by :class:`HierarchyAssembler`."""

    graph: HierarchyGraph
    validation_report: ValidationReport
    manifest: dict
    orphans: List[dict] = field(default_factory=list)
    placeholders: List[str] = field(default_factory=list)

    def to_manifest(self) -> dict:
        return dict(self.manifest)


class HierarchyAssembler:
    """Main coordinator for hierarchy assembly."""

    def __init__(self, policy: HierarchyAssemblyPolicy) -> None:
        self._policy = policy
        self._graph = HierarchyGraph(policy=policy)
        self._checker = InvariantChecker(policy)
        self._validator = GraphValidator(self._checker)
        self._orphans: List[dict] = []
        self._placeholders: Dict[int, str] = {}

    @property
    def graph(self) -> HierarchyGraph:
        return self._graph

    @property
    def orphans(self) -> List[dict]:
        return list(self._orphans)

    @property
    def placeholders(self) -> List[str]:
        return [placeholder_id for placeholder_id in self._placeholders.values()]

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------
    def run(
        self,
        concepts: Sequence[Concept],
        *,
        config_snapshot: dict | None = None,
    ) -> HierarchyAssemblyResult:
        self.process_concepts(concepts)
        validation_report = self._validator.run(self._graph)
        manifest = self.generate_manifest(validation_report, config_snapshot=config_snapshot)
        return HierarchyAssemblyResult(
            graph=self._graph,
            validation_report=validation_report,
            manifest=manifest,
            orphans=self.orphans,
            placeholders=self.placeholders,
        )

    # ------------------------------------------------------------------
    # Concept ingestion pipeline
    # ------------------------------------------------------------------
    def process_concepts(self, concepts: Sequence[Concept]) -> None:
        ordered = sorted(concepts, key=lambda concept: (concept.level, concept.id))
        for concept in ordered:
            resolved_parents, missing = self.resolve_parents(concept)
            working = concept
            if missing:
                strategy = self._policy.orphan_strategy
                self._record_orphan(concept, missing, strategy)
                if strategy == "drop":
                    _LOGGER.warning(
                        "Dropping concept due to missing parents",
                        concept_id=concept.id,
                        missing=missing,
                    )
                    continue
                if strategy == "quarantine":
                    _LOGGER.info(
                        "Quarantining concept with unresolved parents",
                        concept_id=concept.id,
                        missing=missing,
                    )
                    continue
                if strategy == "attach_placeholder":
                    placeholder_parent = self._ensure_placeholder(concept.level - 1)
                    updated_parents = list(resolved_parents)
                    updated_parents.append(placeholder_parent)
                    working = concept.model_copy(update={"parents": updated_parents})
            elif resolved_parents and len(resolved_parents) != len(set(resolved_parents)):
                working = concept.model_copy(update={"parents": sorted(set(resolved_parents))})

            try:
                self._graph.add_concept(working)
            except ValueError as exc:
                _LOGGER.error(
                    "Failed to insert concept into hierarchy",
                    concept_id=working.id,
                    error=str(exc),
                )
                self._record_orphan(working, list(working.parents), "error")

    def resolve_parents(self, concept: Concept) -> Tuple[List[str], List[str]]:
        resolved: List[str] = []
        missing: List[str] = []
        for parent_id in concept.parents:
            if parent_id in self._graph:
                resolved.append(parent_id)
            else:
                missing.append(parent_id)
        return resolved, missing

    def _record_orphan(
        self,
        concept: Concept,
        missing_parents: Sequence[str],
        strategy: str,
    ) -> None:
        self._orphans.append(
            {
                "concept_id": concept.id,
                "level": concept.level,
                "missing_parents": list(missing_parents),
                "strategy": strategy,
            }
        )

    # ------------------------------------------------------------------
    # Placeholder management
    # ------------------------------------------------------------------
    def _ensure_placeholder(self, level: int) -> str:
        if level < 0:
            raise ValueError("Cannot create placeholder for negative level")
        if level in self._placeholders:
            return self._placeholders[level]

        placeholder_id = f"{self._policy.placeholder_parent_prefix}level{level}"
        if level == 0:
            placeholder_concept = Concept(
                id=placeholder_id,
                level=0,
                canonical_label=f"Placeholder Level {level}",
                parents=[],
            )
        else:
            parent_placeholder = self._ensure_placeholder(level - 1)
            placeholder_concept = Concept(
                id=placeholder_id,
                level=level,
                canonical_label=f"Placeholder Level {level}",
                parents=[parent_placeholder],
            )
        if placeholder_id not in self._graph:
            self._graph.add_concept(placeholder_concept)
            _LOGGER.info(
                "Created placeholder concept",
                placeholder_id=placeholder_id,
                level=level,
            )
        self._placeholders[level] = placeholder_id
        return placeholder_id

    # ------------------------------------------------------------------
    # Manifest generation
    # ------------------------------------------------------------------
    def generate_manifest(
        self,
        validation_report: ValidationReport,
        *,
        config_snapshot: dict | None,
    ) -> dict:
        manifest = {
            "policy": self._policy.model_dump(mode="json"),
            "graph_stats": self._graph.statistics(),
            "validation": validation_report.to_dict(),
            "orphans": self.orphans,
            "placeholders": self.placeholders,
        }
        if config_snapshot:
            manifest["config"] = dict(config_snapshot)
        return manifest


__all__ = [
    "HierarchyAssembler",
    "HierarchyAssemblyResult",
]
