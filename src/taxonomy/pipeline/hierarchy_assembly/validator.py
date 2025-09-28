"""Invariant validation helpers for hierarchy assembly."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, List, Sequence

from taxonomy.config.policies import HierarchyAssemblyPolicy
from taxonomy.entities.core import Concept
from taxonomy.utils.logging import get_logger

from .graph import HierarchyGraph

_LOGGER = get_logger(module=__name__)


@dataclass(slots=True)
class ValidationReport:
    """Structured validation output used by manifests and downstream tooling."""

    passed: bool
    violations: List[dict] = field(default_factory=list)
    orphan_summary: dict = field(default_factory=dict)
    graph_stats: dict = field(default_factory=dict)
    proofs: dict = field(default_factory=dict)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "violations": list(self.violations),
            "orphan_summary": dict(self.orphan_summary),
            "graph_stats": dict(self.graph_stats),
            "proofs": dict(self.proofs),
            "generated_at": self.generated_at,
        }


class InvariantChecker:
    """Performs invariant checks that sit above individual concept validation."""

    def __init__(self, policy: HierarchyAssemblyPolicy) -> None:
        self._policy = policy

    @property
    def policy(self) -> HierarchyAssemblyPolicy:
        return self._policy

    def validate_levels(self, concepts: Iterable[Concept]) -> List[dict]:
        violations: List[dict] = []
        for concept in concepts:
            if concept.level < 0 or concept.level > 3:
                violations.append(
                    {
                        "code": "invalid-level",
                        "concept_id": concept.id,
                        "detail": f"level {concept.level} is outside supported range",
                    }
                )
            if concept.level == 0 and concept.parents:
                violations.append(
                    {
                        "code": "root-has-parents",
                        "concept_id": concept.id,
                        "detail": "level 0 concepts must not declare parents",
                    }
                )
            if concept.level > 0 and not concept.parents:
                violations.append(
                    {
                        "code": "missing-parent",
                        "concept_id": concept.id,
                        "detail": "concept above level 0 must reference at least one parent",
                    }
                )
        return violations

    def prove_acyclicity(self, graph: HierarchyGraph) -> dict:
        proof: dict = {}
        try:
            ordering = graph.check_acyclicity()
        except ValueError as exc:  # pragma: no cover - error path exercised via violations
            proof["valid"] = False
            proof["detail"] = str(exc)
            raise
        proof["valid"] = True
        proof["topological_order"] = ordering
        return proof

    def validate_unique_paths(self, graph: HierarchyGraph) -> List[dict]:
        violations: List[dict] = []
        offenders = graph.check_unique_paths()
        for concept_id in offenders:
            violations.append(
                {
                    "code": "non-unique-path",
                    "concept_id": concept_id,
                    "detail": "concept must have exactly one lineage from level 0",
                }
            )
        return violations

    def analyze_orphans(self, graph: HierarchyGraph) -> dict:
        orphans = graph.find_orphans()
        return {
            "total": len(orphans),
            "items": orphans,
        }

    def detect_violations(self, concepts: Sequence[Concept], graph: HierarchyGraph) -> List[dict]:
        collected: List[dict] = []
        collected.extend(self.validate_levels(concepts))
        collected.extend(self.validate_unique_paths(graph))
        return collected

    def suggest_repairs(self, violations: Sequence[dict]) -> List[str]:
        suggestions: List[str] = []
        for violation in violations:
            code = violation.get("code")
            if code == "missing-parent":
                suggestions.append(
                    "Attach placeholder parents or quarantine concepts missing valid parents."
                )
            elif code == "non-unique-path":
                suggestions.append(
                    "Review merge operations that introduced multi-parent relationships."
                )
            elif code == "invalid-level":
                suggestions.append(
                    "Ensure promotion pipeline emits concepts within levels 0-3."
                )
        return suggestions


class GraphValidator:
    """High-level orchestrator combining structural checks into a report."""

    def __init__(self, checker: InvariantChecker) -> None:
        self._checker = checker
        self._logger = get_logger(module=f"{__name__}.GraphValidator")

    def run(self, graph: HierarchyGraph) -> ValidationReport:
        concepts = list(graph.concepts())
        violations = self._checker.detect_violations(concepts, graph)
        orphan_summary = self._checker.analyze_orphans(graph)
        stats = graph.statistics()

        proofs: dict = {}
        try:
            acyclicity_proof = self._checker.prove_acyclicity(graph)
            if self._checker.policy.include_invariant_proofs:
                proofs["acyclicity"] = acyclicity_proof
        except ValueError as exc:
            violations.append(
                {
                    "code": "cycle-detected",
                    "detail": str(exc),
                }
            )
            if self._checker.policy.include_invariant_proofs:
                proofs["acyclicity"] = {"valid": False, "detail": str(exc)}

        if violations:
            proofs["repair_suggestions"] = self._checker.suggest_repairs(violations)

        passed = not violations and orphan_summary.get("total", 0) == 0
        report = ValidationReport(
            passed=passed,
            violations=violations,
            orphan_summary=orphan_summary,
            graph_stats=stats,
            proofs=proofs,
        )
        self._logger.info(
            "Hierarchy validation completed",
            passed=report.passed,
            violations=len(report.violations),
            orphan_total=orphan_summary.get("total", 0),
        )
        return report


__all__ = [
    "GraphValidator",
    "InvariantChecker",
    "ValidationReport",
]
