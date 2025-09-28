"""Coordinator for rule-based and LLM token verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Set

from taxonomy.config.policies import SingleTokenVerificationPolicy
from taxonomy.entities.core import Candidate, Rationale
from taxonomy.utils.helpers import normalize_whitespace
from taxonomy.utils.logging import get_logger

from .rules import RuleEvaluation, TokenRuleEngine
from .verifier import LLMTokenVerifier, LLMVerificationResult


@dataclass
class VerificationInput:
    """Candidate plus contextual metadata for verification."""

    candidate: Candidate
    rationale: Rationale
    institutions: List[str]
    record_fingerprints: List[str]
    metadata: dict | None = None


@dataclass
class TokenVerificationDecision:
    """Decision produced after S3 verification."""

    candidate: Candidate
    rationale: Rationale
    rule_evaluation: RuleEvaluation
    llm_result: Optional[LLMVerificationResult]
    passed: bool
    institutions: List[str]
    record_fingerprints: List[str]


@dataclass
class TokenVerificationResult:
    """Collection of verification decisions and summary statistics."""

    verified: List[TokenVerificationDecision]
    failed: List[TokenVerificationDecision]
    stats: dict


class S3Processor:
    """Apply rule-based and LLM token verification in sequence."""

    def __init__(
        self,
        *,
        rule_engine: TokenRuleEngine,
        llm_verifier: LLMTokenVerifier,
        policy: SingleTokenVerificationPolicy,
    ) -> None:
        self._rule_engine = rule_engine
        self._llm_verifier = llm_verifier
        self._policy = policy
        self._log = get_logger(module=__name__)

    def process(self, items: Iterable[VerificationInput]) -> TokenVerificationResult:
        verified: List[TokenVerificationDecision] = []
        failed: List[TokenVerificationDecision] = []
        total = 0
        passed_rule = 0
        failed_rule = 0
        allowlist_hits = 0
        llm_called = 0
        passed_llm = 0
        failed_llm = 0
        for entry in items:
            total += 1
            decision = self._evaluate(entry)
            if decision.passed:
                verified.append(decision)
            else:
                failed.append(decision)
            if decision.rule_evaluation.passed:
                passed_rule += 1
            else:
                failed_rule += 1
            if decision.rule_evaluation.allowlist_hit:
                allowlist_hits += 1
            if decision.llm_result is not None:
                llm_called += 1
                if decision.llm_result.passed:
                    passed_llm += 1
                else:
                    failed_llm += 1
        stats = {
            "candidates_in": total,
            "verified": len(verified),
            "failed": len(failed),
            "checked": total,
            "passed_rule": passed_rule,
            "failed_rule": failed_rule,
            "allowlist_hits": allowlist_hits,
            "llm_called": llm_called,
            "passed_llm": passed_llm,
            "failed_llm": failed_llm,
        }
        self._log.info(
            "S3 token verification complete",
            stats=stats,
        )
        return TokenVerificationResult(verified=verified, failed=failed, stats=stats)

    def _evaluate(self, entry: VerificationInput) -> TokenVerificationDecision:
        candidate = entry.candidate
        rationale = entry.rationale.model_copy(deep=True)

        rule_evaluation = self._rule_engine.apply_all_rules(candidate.normalized, candidate.level)
        rationale.passed_gates["token_rule"] = rule_evaluation.passed
        if rule_evaluation.reasons:
            rationale.reasons.extend(f"rule:{reason}" for reason in rule_evaluation.reasons)
        if rule_evaluation.suggestions:
            rationale.reasons.extend(f"suggestion:{suggestion}" for suggestion in rule_evaluation.suggestions)
        rationale.thresholds["token_limit"] = self._policy.max_tokens_per_level.get(
            candidate.level,
            max(self._policy.max_tokens_per_level.values()),
        )

        llm_result: Optional[LLMVerificationResult] = None
        if not rule_evaluation.allowlist_hit:
            needs_llm = not rule_evaluation.passed
            if needs_llm:
                llm_result = self._llm_verifier.verify(candidate.normalized, candidate.level)
                rationale.passed_gates["token_llm"] = llm_result.passed
                if llm_result.reason:
                    rationale.reasons.append(f"llm:{llm_result.reason}")
                if llm_result.error:
                    rationale.reasons.append(f"llm_error:{llm_result.error}")
            else:
                rationale.passed_gates["token_llm"] = None
        else:
            rationale.passed_gates["token_llm"] = None

        final_pass = self._final_decision(rule_evaluation, llm_result)
        rationale.passed_gates["token_verification"] = final_pass

        if final_pass and rule_evaluation.suggestions:
            normalized_existing: Set[str] = set()
            for alias in candidate.aliases:
                cleaned_alias = normalize_whitespace(alias).strip()
                if cleaned_alias:
                    normalized_existing.add(cleaned_alias)
            label_alias = normalize_whitespace(candidate.label).strip()
            if label_alias:
                normalized_existing.add(label_alias)
            for suggestion in rule_evaluation.suggestions:
                cleaned = normalize_whitespace(suggestion).strip()
                if cleaned:
                    normalized_existing.add(cleaned)
            candidate.aliases = sorted(normalized_existing)

        decision = TokenVerificationDecision(
            candidate=candidate,
            rationale=rationale,
            rule_evaluation=rule_evaluation,
            llm_result=llm_result,
            passed=final_pass,
            institutions=entry.institutions,
            record_fingerprints=entry.record_fingerprints,
        )
        self._log.debug(
            "Evaluated token verification candidate",
            normalized=candidate.normalized,
            level=candidate.level,
            rule_passed=rule_evaluation.passed,
            llm_passed=None if llm_result is None else llm_result.passed,
            final_pass=final_pass,
        )
        return decision

    def _final_decision(
        self,
        rule_evaluation: RuleEvaluation,
        llm_result: Optional[LLMVerificationResult],
    ) -> bool:
        if rule_evaluation.allowlist_hit:
            return True
        if self._policy.prefer_rule_over_llm:
            if not rule_evaluation.passed:
                return False
            if llm_result is None:
                return True
            return llm_result.passed
        if llm_result is not None:
            return llm_result.passed
        return rule_evaluation.passed


__all__ = [
    "S3Processor",
    "VerificationInput",
    "TokenVerificationDecision",
    "TokenVerificationResult",
]
