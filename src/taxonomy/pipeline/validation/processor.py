"""High-level orchestration for the validation pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

from ...config.policies import ValidationPolicy
from ...entities.core import Concept, ValidationFinding, PageSnapshot
from .aggregator import AggregatedDecision, ValidationAggregator
from .evidence import EvidenceIndexer, EvidenceSnippet
from .llm import LLMValidator, LLMResult
from .rules import RuleValidator, RuleResult
from .web import WebValidator, WebResult


@dataclass
class ValidationOutcome:
    """Outcome for a single concept including aggregated decision."""

    concept: Concept
    decision: AggregatedDecision
    findings: List[ValidationFinding] = field(default_factory=list)
    evidence: List[EvidenceSnippet] = field(default_factory=list)


class ValidationProcessor:
    """Coordinate rule, web, and LLM validators."""

    def __init__(
        self,
        policy: ValidationPolicy,
        *,
        indexer: EvidenceIndexer | None = None,
        enable_web: bool = True,
        enable_llm: bool | None = None,
    ) -> None:
        self._policy = policy
        self._indexer = indexer or EvidenceIndexer(policy)
        self._rule_validator = RuleValidator(policy)
        self._web_validator = WebValidator(policy, self._indexer) if enable_web else None
        llm_enabled = policy.llm.entailment_enabled if enable_llm is None else enable_llm
        self._llm_validator = LLMValidator(policy) if llm_enabled else None
        self._aggregator = ValidationAggregator(policy)
        self._stats = {
            "concepts": 0,
            "checked": 0,
            "rule_passed": 0,
            "rule_failed": 0,
            "web_passed": 0,
            "web_failed": 0,
            "llm_passed": 0,
            "llm_failed": 0,
            "validation_passed": 0,
            "passed_all": 0,
        }

    @property
    def stats(self) -> dict:
        return dict(self._stats)

    def prepare_evidence(self, snapshots: Sequence[PageSnapshot]) -> None:
        self._indexer.build_index(snapshots)

    def process(self, concepts: Iterable[Concept]) -> List[ValidationOutcome]:
        outcomes: List[ValidationOutcome] = []
        for concept in concepts:
            self._stats["concepts"] += 1
            self._stats["checked"] += 1
            rule_result = self._rule_validator.validate_concept(concept)
            if rule_result.passed:
                self._stats["rule_passed"] += 1
            else:
                self._stats["rule_failed"] += 1

            web_result: WebResult | None = None
            evidence_payload: List[EvidenceSnippet] = []
            if self._web_validator is not None:
                web_result = self._web_validator.validate_concept(concept)
                if web_result.passed:
                    self._stats["web_passed"] += 1
                elif not web_result.unknown:
                    self._stats["web_failed"] += 1
                evidence_payload = [snippet for snippet in web_result.evidence]

            llm_result: LLMResult | None = None
            if self._llm_validator is not None:
                llm_result = self._llm_validator.validate_concept(concept, evidence_payload)
                if llm_result.passed:
                    self._stats["llm_passed"] += 1
                else:
                    self._stats["llm_failed"] += 1

            decision = self._aggregator.aggregate(
                concept.id, rule_result, web_result, llm_result
            )
            if decision.passed:
                self._stats["validation_passed"] += 1
                self._stats["passed_all"] += 1

            concept.validation_metadata["evidence_count"] = len(evidence_payload)
            if evidence_payload:
                concept.validation_metadata["top_evidence_url"] = evidence_payload[0].url

            self._apply_to_concept(concept, decision)
            outcomes.append(
                ValidationOutcome(
                    concept=concept,
                    decision=decision,
                    findings=decision.findings,
                    evidence=evidence_payload,
                )
            )
        return outcomes

    def _apply_to_concept(self, concept: Concept, decision: AggregatedDecision) -> None:
        concept.validation_passed = decision.passed
        concept.validation_metadata["scores"] = decision.scores
        concept.validation_metadata["confidence"] = decision.confidence
        concept.rationale.passed_gates["validation"] = decision.passed
        concept.rationale.reasons.append(decision.rationale)
