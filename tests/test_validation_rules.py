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


def test_venue_detection_is_soft_by_default() -> None:
    policy = ValidationPolicy()
    policy = policy.model_copy(update={
        "rules": policy.rules.model_copy(
            update={
                "venue_patterns": ["neurips"],
                "forbidden_patterns": [],
            }
        )
    })
    validator = RuleValidator(policy)

    result = validator.validate_concept(_concept("NeurIPS", level=3))

    assert result.passed
    assert "venue_name_detected:neurips" in result.soft_violations
    assert not result.hard_violations


def test_venue_detection_toggle_escalates() -> None:
    policy = ValidationPolicy()
    policy = policy.model_copy(update={
        "rules": policy.rules.model_copy(
            update={
                "venue_patterns": ["neurips"],
                "venue_detection_hard": True,
            }
        )
    })
    validator = RuleValidator(policy)

    result = validator.validate_concept(_concept("NeurIPS", level=3))

    assert not result.passed
    assert result.hard_fail
    assert "venue_name_detected:neurips" in result.hard_violations


def test_venue_detection_hardens_when_forbidden_matches() -> None:
    policy = ValidationPolicy()
    policy = policy.model_copy(update={
        "rules": policy.rules.model_copy(
            update={
                "venue_patterns": ["neurips"],
                "forbidden_patterns": ["neurips"],
            }
        )
    })
    validator = RuleValidator(policy)

    result = validator.validate_concept(_concept("NeurIPS", level=3))

    assert not result.passed
    assert result.hard_fail
    assert "forbidden_pattern:neurips" in result.hard_violations
    assert "venue_name_detected:neurips" in result.hard_violations
