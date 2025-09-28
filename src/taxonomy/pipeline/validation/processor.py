"""High-level orchestration for the validation pipeline."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

from ...config.policies import ValidationPolicy
from ...entities.core import Concept, Rationale, ValidationFinding, PageSnapshot
from .aggregator import AggregatedDecision, ValidationAggregator
from .evidence import EvidenceIndexer, EvidenceSnippet
from .llm import LLMValidator, LLMResult
from .rules import RuleValidator, RuleResult
from .web import WebValidator, WebResult

VALIDATION_GATE = "validation"
META_SCORES = "scores"
META_CONFIDENCE = "confidence"
"""Validation metadata schema.

- ``concept.validation_metadata[META_SCORES]`` stores per-validator float scores.
- ``concept.validation_metadata[META_CONFIDENCE]`` stores the aggregated confidence as a float or ``None``.
- ``concept.rationale.passed_gates[VALIDATION_GATE]`` records the boolean aggregated validation outcome.
"""


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
            metadata, _ = self._ensure_validation_structures(concept)
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

            metadata["evidence_count"] = len(evidence_payload)
            if evidence_payload:
                metadata["top_evidence_url"] = evidence_payload[0].url

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
        concept.set_validation_passed(decision.passed, gate=VALIDATION_GATE)
        metadata, rationale = self._ensure_validation_structures(concept)

        metadata[META_SCORES] = deepcopy(decision.scores)

        confidence = decision.confidence
        if confidence is not None:
            if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
                raise TypeError(
                    "AggregatedDecision.confidence must be a numeric type when provided."
                )
            metadata[META_CONFIDENCE] = float(confidence)
        else:
            metadata[META_CONFIDENCE] = None

        rationale.reasons.append(decision.rationale)

    @staticmethod
    def _ensure_validation_structures(concept: Concept) -> tuple[dict, Rationale]:
        metadata = concept.validation_metadata
        if metadata is None:
            metadata = {}
        elif not isinstance(metadata, dict):
            metadata = dict(metadata)
        concept.validation_metadata = metadata

        rationale = concept.rationale
        if rationale is None:
            rationale = Rationale()
        if rationale.passed_gates is None:
            rationale.passed_gates = {}
        if rationale.reasons is None:
            rationale.reasons = []
        concept.rationale = rationale

        return metadata, rationale
