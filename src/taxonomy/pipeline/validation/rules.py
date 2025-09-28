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
    hard_violations: List[str]
    soft_violations: List[str]


class RuleValidator:
    """Apply deterministic validation rules to concepts."""

    def __init__(self, policy: ValidationPolicy) -> None:
        self._settings = policy.rules
        self._compile_patterns()

    def validate_concept(self, concept: Concept) -> RuleResult:
        """Run deterministic rule checks and translate them into findings."""
        violations: List[str] = []

        if self._settings.structural_checks_enabled:
            violations.extend(self._check_structure(concept))

        violations.extend(self._check_forbidden_patterns(concept.canonical_label))
        violations.extend(self._detect_venue_names(concept))

        vocab_violation = self._check_vocabularies(concept)
        if vocab_violation:
            violations.append(vocab_violation)

        hard_violations, soft_violations = self._partition_violations(violations)
        hard_fail = bool(hard_violations)
        passed = not hard_fail
        findings = self._build_findings(concept, hard_violations, soft_violations)
        summary = self._summarize(hard_violations, soft_violations)
        return RuleResult(
            passed=passed,
            violations=violations,
            hard_fail=hard_fail,
            findings=findings,
            summary=summary,
            hard_violations=hard_violations,
            soft_violations=soft_violations,
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
        if all(token in label for token in required):
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

    def _has_hard_violations(self, violations: Sequence[str]) -> bool:
        """Return True when hard violations should block the concept.

        Hard violations are deterministic rule breaches that require rejection.
        Policy-driven thresholds should be implemented at the policy layer rather
        than in this helper.
        """
        return bool(violations)

    def _build_findings(
        self,
        concept: Concept,
        hard_violations: Iterable[str],
        soft_violations: Iterable[str],
    ) -> List[ValidationFinding]:
        hard_list = list(hard_violations)
        soft_list = list(soft_violations)
        if not hard_list and not soft_list:
            return [
                ValidationFinding(
                    concept_id=concept.id,
                    mode=FindingMode.RULE,
                    passed=True,
                    detail="All deterministic rule checks passed.",
                )
            ]

        findings: List[ValidationFinding] = []
        for violation in hard_list:
            findings.append(
                ValidationFinding(
                    concept_id=concept.id,
                    mode=FindingMode.RULE,
                    passed=False,
                    detail=f"Rule violation: {violation}",
                )
            )
        for violation in soft_list:
            findings.append(
                ValidationFinding(
                    concept_id=concept.id,
                    mode=FindingMode.RULE,
                    passed=False,
                    detail=f"Rule warning: {violation}",
                )
            )
        return findings

    def _summarize(
        self,
        hard_violations: Sequence[str],
        soft_violations: Sequence[str],
    ) -> str:
        """Generate a compact summary for logging and reports."""
        has_hard = self._has_hard_violations(hard_violations)
        if not has_hard and not soft_violations:
            return "Rule checks succeeded"

        counts = []
        if has_hard:
            counts.append(f"{len(hard_violations)} hard")
        if soft_violations:
            counts.append(f"{len(soft_violations)} soft")
        headline = ", ".join(counts)
        primary_issue = hard_violations[0] if has_hard else soft_violations[0]
        return f"{headline} violations; most significant: {primary_issue}"

    def _venue_violation_is_hard(
        self, detail: str, forbidden_details: set[str]
    ) -> bool:
        """Decide whether a venue-name detection should be treated as hard.

        Venue hits escalate when policy toggles `venue_detection_hard` or when the
        detected venue already matches a forbidden pattern. More complex rules
        (e.g., thresholds) should be introduced via the policy layer.
        """
        if self._settings.venue_detection_hard:
            return True
        if not detail:
            return False
        return detail in forbidden_details

    def _partition_violations(
        self, violations: Sequence[str]
    ) -> tuple[List[str], List[str]]:
        """Separate violations into hard and soft buckets."""
        if not violations:
            return [], []

        hard_prefixes = {
            "forbidden_pattern",
            "root_has_parents",
            "missing_parents",
            "invalid_level",
            "missing_required_vocab",
        }
        forbidden_details = {
            violation.split(":", 1)[1]
            for violation in violations
            if violation.startswith("forbidden_pattern:")
        }

        hard_violations: List[str] = []
        soft_violations: List[str] = []
        for violation in violations:
            prefix, _, detail = violation.partition(":")
            if prefix == "venue_name_detected":
                is_hard = self._venue_violation_is_hard(detail, forbidden_details)
            else:
                is_hard = prefix in hard_prefixes

            if is_hard:
                hard_violations.append(violation)
            else:
                soft_violations.append(violation)
        return hard_violations, soft_violations
