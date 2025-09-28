"""Unit tests for rule-based validation logic."""

from __future__ import annotations

from taxonomy.config.policies import ValidationPolicy
from taxonomy.entities.core import Concept
from taxonomy.pipeline.validation.rules import RuleValidator


def _concept(label: str, *, level: int = 1, parents: list[str] | None = None) -> Concept:
    return Concept(
        id="concept-1",
        level=level,
        canonical_label=label,
        parents=parents if parents is not None else (["root"] if level > 0 else []),
    )


def test_rule_validator_flags_forbidden_pattern() -> None:
    policy = ValidationPolicy()
    policy = policy.model_copy(update={
        "rules": policy.rules.model_copy(update={"forbidden_patterns": ["neurips"]})
    })
    validator = RuleValidator(policy)

    result = validator.validate_concept(_concept("NeurIPS"))

    assert not result.passed
    assert result.hard_fail
    assert any("forbidden_pattern" in violation for violation in result.violations)


def test_rule_validator_detects_structural_issues() -> None:
    policy = ValidationPolicy()
    validator = RuleValidator(policy)

    concept = _concept("Robotics", level=2, parents=[])
    result = validator.validate_concept(concept)

    assert not result.passed
    assert "missing_parents" in result.violations


def test_rule_validator_vocab_requirement() -> None:
    policy = ValidationPolicy()
    policy = policy.model_copy(update={
        "rules": policy.rules.model_copy(update={"required_vocabularies": {1: ["data"]}})
    })
    validator = RuleValidator(policy)

    result = validator.validate_concept(_concept("Applied Data Science"))
    assert result.passed

    failed = validator.validate_concept(_concept("Applied Physics"))
    assert not failed.passed
    assert "missing_required_vocab:1" in failed.violations
