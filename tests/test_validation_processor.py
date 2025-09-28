"""Integration-style tests for the validation processor."""

from __future__ import annotations

from datetime import datetime, timezone

from taxonomy.config.policies import ValidationPolicy
from taxonomy.entities.core import Concept, PageSnapshot
from taxonomy.pipeline.validation.processor import ValidationProcessor


def _snapshot(text: str) -> PageSnapshot:
    checksum = PageSnapshot.compute_checksum(text)
    return PageSnapshot(
        institution="Example University",
        url="https://example.edu/programs",
        canonical_url="https://example.edu/programs",
        fetched_at=datetime.now(timezone.utc),
        http_status=200,
        content_type="text/html",
        html=None,
        text=text,
        lang="en",
        checksum=checksum,
    )


def _concept(label: str) -> Concept:
    return Concept(
        id=f"concept-{label.lower().replace(' ', '-')}",
        level=2,
        canonical_label=label,
        parents=["parent"],
    )


def test_processor_updates_concept_metadata() -> None:
    base_policy = ValidationPolicy()
    policy = base_policy.model_copy(update={
        "web": base_policy.web.model_copy(update={"min_snippet_matches": 1}),
        "llm": base_policy.llm.model_copy(update={"entailment_enabled": False}),
    })

    processor = ValidationProcessor(policy, enable_llm=False)
    processor.prepare_evidence([_snapshot("Applied Data Science is a flagship program.")])

    concepts = [_concept("Applied Data Science")]
    outcomes = processor.process(concepts)

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.decision.passed
    assert outcome.evidence
    concept = outcome.concept
    assert concept.validation_passed is True
    assert concept.validation_metadata.get("evidence_count") == len(outcome.evidence)
    assert concept.rationale.passed_gates.get("validation") is True


def test_processor_respects_rule_failures() -> None:
    base_policy = ValidationPolicy()
    policy = base_policy.model_copy(update={
        "rules": base_policy.rules.model_copy(update={"forbidden_patterns": ["neurips"]}),
        "llm": base_policy.llm.model_copy(update={"entailment_enabled": False}),
    })

    processor = ValidationProcessor(policy, enable_llm=False, enable_web=False)
    concepts = [_concept("NeurIPS"), _concept("Quantum Computing")]

    outcomes = processor.process(concepts)
    passed_status = {outcome.concept.canonical_label: outcome.decision.passed for outcome in outcomes}

    assert passed_status["NeurIPS"] is False
    assert passed_status["Quantum Computing"] is True
