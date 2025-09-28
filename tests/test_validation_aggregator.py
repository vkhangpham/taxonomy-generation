import math

import pytest

from taxonomy.config.policies import ValidationAggregationSettings, ValidationPolicy
from taxonomy.entities.core import FindingMode, ValidationFinding
from taxonomy.pipeline.validation.aggregator import ValidationAggregator
from taxonomy.pipeline.validation.evidence import EvidenceSnippet
from taxonomy.pipeline.validation.llm import LLMResult
from taxonomy.pipeline.validation.rules import RuleResult
from taxonomy.pipeline.validation.web import WebResult


CONCEPT_ID = "concept-001"


def _finding(mode: FindingMode, passed: bool, detail: str) -> ValidationFinding:
    return ValidationFinding(
        concept_id=CONCEPT_ID,
        mode=mode,
        passed=passed,
        detail=detail,
    )


def make_rule_result(passed: bool = True) -> RuleResult:
    return RuleResult(
        passed=passed,
        violations=[],
        hard_fail=not passed,
        findings=[_finding(FindingMode.RULE, passed, "rule evaluation")],
        summary="Rule summary",
        hard_violations=[],
        soft_violations=[],
    )


def make_web_result(
    passed: bool = True,
    *,
    unknown: bool = False,
    evidence_scores: tuple[float, ...] | None = None,
) -> WebResult:
    evidence_scores = evidence_scores or tuple()
    evidence = [
        EvidenceSnippet(
            text=f"snippet-{idx}",
            url=f"https://example.com/{idx}",
            institution="ExampleU",
            score=score,
        )
        for idx, score in enumerate(evidence_scores)
    ]
    return WebResult(
        passed=passed,
        findings=[_finding(FindingMode.WEB, passed, "web evaluation")],
        summary="Web summary",
        evidence=evidence,
        unknown=unknown,
    )


def make_llm_result(passed: bool = True, confidence: float = 0.8) -> LLMResult:
    return LLMResult(
        passed=passed,
        confidence=confidence,
        findings=[_finding(FindingMode.LLM, passed, "llm evaluation")],
        summary="LLM summary",
    )


def test_weighted_aggregation_detects_tie_with_tolerance():
    policy = ValidationPolicy(
        aggregation=ValidationAggregationSettings(
            rule_weight=0.3,
            web_weight=0.2,
            llm_weight=0.500000000001,
            tie_break_conservative=False,
        )
    )
    aggregator = ValidationAggregator(policy)

    decision = aggregator.aggregate(
        CONCEPT_ID,
        make_rule_result(True),
        make_web_result(True, evidence_scores=(0.9, 0.8)),
        make_llm_result(False, confidence=0.4),
    )

    assert decision.passed is True
    assert decision.scores["llm"] == 0.0
    expected_confidence = (0.3 + 0.2) / (0.3 + 0.2 + 0.500000000001)
    assert decision.confidence == pytest.approx(expected_confidence, rel=1e-12)


def test_weighted_aggregation_near_threshold_is_not_tie():
    policy = ValidationPolicy(
        aggregation=ValidationAggregationSettings(
            rule_weight=0.3,
            web_weight=0.2,
            llm_weight=0.5001,
            tie_break_conservative=False,
        )
    )
    aggregator = ValidationAggregator(policy)

    decision = aggregator.aggregate(
        CONCEPT_ID,
        make_rule_result(True),
        make_web_result(True, evidence_scores=(0.9,)),
        make_llm_result(False, confidence=0.4),
    )

    assert decision.passed is False


def test_weighted_aggregation_handles_zero_total_weight():
    policy = ValidationPolicy(
        aggregation=ValidationAggregationSettings(
            rule_weight=0.0,
            web_weight=0.0,
            llm_weight=0.0,
        )
    )
    aggregator = ValidationAggregator(policy)

    decision = aggregator.aggregate(CONCEPT_ID, make_rule_result(True), None, None)

    assert decision.passed is False
    assert decision.confidence == 0.0
    assert decision.scores == {"rule": 0.0, "web": 0.0, "llm": 0.0}


def test_weighted_aggregation_handles_very_small_weights():
    tiny = 1e-12
    policy = ValidationPolicy(
        aggregation=ValidationAggregationSettings(
            rule_weight=tiny,
            web_weight=tiny,
            llm_weight=0.0,
            tie_break_conservative=True,
            tie_break_min_strength=0.0,
        )
    )
    aggregator = ValidationAggregator(policy)

    decision = aggregator.aggregate(
        CONCEPT_ID,
        make_rule_result(True),
        make_web_result(True, evidence_scores=(0.5,)),
        None,
    )

    assert decision.passed is True
    assert decision.confidence == pytest.approx(1.0, rel=1e-9)


def test_unknown_results_excluded_from_weights_and_strength():
    policy = ValidationPolicy(
        aggregation=ValidationAggregationSettings(
            rule_weight=0.4,
            web_weight=0.3,
            llm_weight=0.3,
            tie_break_conservative=True,
            tie_break_min_strength=0.5,
        )
    )
    aggregator = ValidationAggregator(policy)

    web_result = make_web_result(True, unknown=True, evidence_scores=(0.9,))
    llm_result = make_llm_result(True, confidence=0.95)
    llm_result.unknown = True

    decision = aggregator.aggregate(
        CONCEPT_ID,
        make_rule_result(True),
        web_result,
        llm_result,
    )

    assert decision.passed is True
    assert decision.scores["web"] == 0.0
    assert decision.scores["llm"] == 0.0
    assert decision.confidence == pytest.approx(1.0, rel=1e-9)


def test_conservative_tie_requires_min_strength():
    policy = ValidationPolicy(
        aggregation=ValidationAggregationSettings(
            rule_weight=0.3,
            web_weight=0.2,
            llm_weight=0.5,
            tie_break_conservative=True,
            tie_break_min_strength=0.6,
        )
    )
    aggregator = ValidationAggregator(policy)

    strong_web = make_web_result(True, evidence_scores=(0.9, 0.8))
    weak_web = make_web_result(True, evidence_scores=(0.2,))

    strong_decision = aggregator.aggregate(
        CONCEPT_ID,
        make_rule_result(True),
        strong_web,
        make_llm_result(False, confidence=0.4),
    )
    weak_decision = aggregator.aggregate(
        CONCEPT_ID,
        make_rule_result(True),
        weak_web,
        make_llm_result(False, confidence=0.4),
    )

    assert strong_decision.passed is True
    assert weak_decision.passed is False


@pytest.mark.parametrize(
    "field, value",
    [
        ("rule_weight", -0.1),
        ("web_weight", math.inf),
        ("llm_weight", math.nan),
    ],
)
def test_invalid_policy_weights_raise(field: str, value: float) -> None:
    policy = ValidationPolicy()
    setattr(policy.aggregation, field, value)

    with pytest.raises(ValueError):
        ValidationAggregator(policy)


def test_invalid_tie_break_strength_raises() -> None:
    policy = ValidationPolicy()
    policy.aggregation.tie_break_min_strength = math.inf

    with pytest.raises(ValueError):
        ValidationAggregator(policy)
