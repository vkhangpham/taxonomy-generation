"""Rule-based validation checks for taxonomy concepts."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Dict, Iterable, List, Sequence

from ...config.policies import RuleValidationSettings, ValidationPolicy
from ...entities.core import Concept, FindingMode, ValidationFinding


@dataclass
class RuleResult:
    """Outcome of deterministic rule validation."""

    passed: bool
    violations: List[str]
    hard_fail: bool
    findings: List[ValidationFinding]
    summary: str


class RuleValidator:
    """Apply deterministic validation rules to concepts."""

    def __init__(self, policy: ValidationPolicy) -> None:
        self._settings = policy.rules
        self._compile_patterns()

    def validate_concept(self, concept: Concept) -> RuleResult:
        violations: List[str] = []

        if self._settings.structural_checks_enabled:
            violations.extend(self._check_structure(concept))

        violations.extend(self._check_forbidden_patterns(concept.canonical_label))
        violations.extend(self._detect_venue_names(concept))

        vocab_violation = self._check_vocabularies(concept)
        if vocab_violation:
            violations.append(vocab_violation)

        passed = not violations
        hard_fail = self._is_hard_failure(violations)
        findings = self._build_findings(concept, violations, passed)
        summary = self._summarize(violations)
        return RuleResult(
            passed=passed,
            violations=violations,
            hard_fail=hard_fail,
            findings=findings,
            summary=summary,
        )

    # -- internals -----------------------------------------------------------------

    def _compile_patterns(self) -> None:
        self._forbidden_compiled: List[re.Pattern[str]] = [
            re.compile(pattern, flags=re.IGNORECASE)
            for pattern in self._settings.forbidden_patterns
        ]
        self._venue_compiled: List[re.Pattern[str]] = [
            re.compile(pattern, flags=re.IGNORECASE)
            for pattern in self._settings.venue_patterns
        ]

    def _check_forbidden_patterns(self, label: str) -> List[str]:
        violations: List[str] = []
        for pattern in self._forbidden_compiled:
            if pattern.search(label):
                violations.append(f"forbidden_pattern:{pattern.pattern}")
        return violations

    def _check_vocabularies(self, concept: Concept) -> str | None:
        required = self._settings.required_vocabularies.get(concept.level)
        if not required:
            return None
        label = concept.canonical_label.lower()
        if any(token in label for token in required):
            return None
        return f"missing_required_vocab:{concept.level}"

    def _check_structure(self, concept: Concept) -> List[str]:
        violations: List[str] = []
        if concept.level == 0 and concept.parents:
            violations.append("root_has_parents")
        if concept.level > 0 and not concept.parents:
            violations.append("missing_parents")
        if concept.level < 0 or concept.level > 3:
            violations.append("invalid_level")
        return violations

    def _detect_venue_names(self, concept: Concept) -> List[str]:
        if not self._venue_compiled or concept.level != 3:
            return []
        label = concept.canonical_label
        matches = [pattern.pattern for pattern in self._venue_compiled if pattern.search(label)]
        return [f"venue_name_detected:{match}" for match in matches]

    def _is_hard_failure(self, violations: Sequence[str]) -> bool:
        if not violations:
            return False
        hard_prefixes = {"forbidden_pattern", "root_has_parents", "missing_parents", "invalid_level"}
        return any(violation.split(":", 1)[0] in hard_prefixes for violation in violations)

    def _build_findings(
        self, concept: Concept, violations: Iterable[str], passed: bool
    ) -> List[ValidationFinding]:
        findings: List[ValidationFinding] = []
        if passed:
            findings.append(
                ValidationFinding(
                    concept_id=concept.id,
                    mode=FindingMode.RULE,
                    passed=True,
                    detail="All deterministic rule checks passed.",
                )
            )
            return findings

        for violation in violations:
            findings.append(
                ValidationFinding(
                    concept_id=concept.id,
                    mode=FindingMode.RULE,
                    passed=False,
                    detail=f"Rule violation: {violation}",
                )
            )
        return findings

    def _summarize(self, violations: Sequence[str]) -> str:
        if not violations:
            return "Rule checks succeeded"
        return ", ".join(violations)
