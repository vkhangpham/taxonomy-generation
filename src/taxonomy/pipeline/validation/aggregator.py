"""Aggregation of validation signals into a single decision."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from ...config.policies import ValidationAggregationSettings, ValidationPolicy
from ...entities.core import ValidationFinding
from .rules import RuleResult
from .web import WebResult
from .llm import LLMResult


@dataclass
class AggregatedDecision:
    """Final aggregated decision emitted by the validation stage."""

    passed: bool
    rationale: str
    findings: List[ValidationFinding]
    confidence: float
    scores: Dict[str, float]


class ValidationAggregator:
    """Combine rule, web, and LLM signals following the configured policy."""

    def __init__(self, policy: ValidationPolicy) -> None:
        self._policy = policy
        self._validate_weights(policy.aggregation)

    def aggregate(
        self,
        concept_id: str,
        rule_result: RuleResult,
        web_result: Optional[WebResult] = None,
        llm_result: Optional[LLMResult] = None,
    ) -> AggregatedDecision:
        weights = self._policy.aggregation
        if weights.hard_rule_failure_blocks and rule_result.hard_fail:
            rationale = self._format_rationale("Hard rule failure", [rule_result])
            findings = list(self._chain_findings(rule_result, web_result, llm_result))
            return AggregatedDecision(
                passed=False,
                rationale=rationale,
                findings=findings,
                confidence=0.0,
                scores={"rule": 0.0, "web": 0.0, "llm": 0.0},
            )

        scores: Dict[str, float] = {}
        total_weight = 0.0
        vote_weight = 0.0

        total_weight += weights.rule_weight
        scores["rule"] = weights.rule_weight if rule_result.passed else 0.0
        if rule_result.passed:
            vote_weight += weights.rule_weight

        if web_result is not None:
            web_unknown = bool(getattr(web_result, "unknown", False))
            if not web_unknown:
                total_weight += weights.web_weight
                scores["web"] = weights.web_weight if web_result.passed else 0.0
                if web_result.passed:
                    vote_weight += weights.web_weight
            else:
                scores["web"] = 0.0
        else:
            scores["web"] = 0.0

        if llm_result is not None:
            llm_unknown = bool(getattr(llm_result, "unknown", False))
            if not llm_unknown:
                total_weight += weights.llm_weight
                scores["llm"] = weights.llm_weight if llm_result.passed else 0.0
                if llm_result.passed:
                    vote_weight += weights.llm_weight
            else:
                scores["llm"] = 0.0
        else:
            scores["llm"] = 0.0

        passed, is_tie = self._compare_vote_to_threshold(vote_weight, total_weight)
        if is_tie:
            if not weights.tie_break_conservative:
                passed = True
            else:
                evidence_strength = self._evidence_strength(web_result, llm_result)
                min_strength = weights.tie_break_min_strength
                if min_strength is None:
                    min_strength = self._policy.llm.confidence_threshold
                if evidence_strength >= min_strength:
                    passed = True
                else:
                    passed = False
        confidence = 0.0 if total_weight == 0 else vote_weight / total_weight
        rationale = self._format_rationale("Weighted aggregation", [rule_result, web_result, llm_result])
        findings = list(self._chain_findings(rule_result, web_result, llm_result))
        return AggregatedDecision(
            passed=passed,
            rationale=rationale,
            findings=findings,
            confidence=confidence,
            scores=scores,
        )

    def _format_rationale(self, operation: str, fragments: Iterable[object | None]) -> str:
        parts: List[str] = [operation]
        for fragment in fragments:
            if fragment is None:
                continue
            summary = getattr(fragment, "summary", None)
            if summary:
                parts.append(summary)
        return "; ".join(parts)

    def _chain_findings(
        self,
        rule_result: RuleResult,
        web_result: Optional[WebResult],
        llm_result: Optional[LLMResult],
    ) -> Iterable[ValidationFinding]:
        yield from rule_result.findings
        if web_result is not None:
            yield from web_result.findings
        if llm_result is not None:
            yield from llm_result.findings

    def _evidence_strength(
        self, web_result: Optional[WebResult], llm_result: Optional[LLMResult]
    ) -> float:
        web_strength = 0.0
        if (
            web_result is not None
            and not bool(getattr(web_result, "unknown", False))
            and web_result.evidence
        ):
            scores = [snippet.score for snippet in web_result.evidence]
            if scores:
                web_strength = sum(scores) / len(scores)

        if llm_result is not None and not bool(getattr(llm_result, "unknown", False)):
            llm_strength = llm_result.confidence
        else:
            llm_strength = 0.0
        return max(web_strength, llm_strength)

    @staticmethod
    def _compare_vote_to_threshold(
        vote_weight: float, total_weight: float
    ) -> Tuple[bool, bool]:
        if total_weight <= 0.0:
            return False, False
        threshold = total_weight / 2.0
        is_tie = math.isclose(vote_weight, threshold, rel_tol=1e-9, abs_tol=1e-9)
        if vote_weight > threshold and not is_tie:
            return True, False
        if is_tie:
            return False, True
        return False, False

    @staticmethod
    def _validate_weights(weights: ValidationAggregationSettings) -> None:
        values = {
            "rule_weight": weights.rule_weight,
            "web_weight": weights.web_weight,
            "llm_weight": weights.llm_weight,
        }
        for name, value in values.items():
            if value < 0 or not math.isfinite(value):
                raise ValueError(f"{name} must be non-negative and finite")

        min_strength = weights.tie_break_min_strength
        if min_strength is not None and (min_strength < 0 or not math.isfinite(min_strength)):
            raise ValueError("tie_break_min_strength must be non-negative and finite when provided")
