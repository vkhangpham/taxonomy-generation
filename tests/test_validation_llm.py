"""Tests for the LLM-based validation component."""

from __future__ import annotations

from dataclasses import dataclass

from taxonomy.config.policies import ValidationPolicy
from taxonomy.entities.core import Concept
from taxonomy.pipeline.validation.evidence import EvidenceSnippet
from taxonomy.pipeline.validation.llm import LLMValidator


@dataclass
class DummyResponse:
    ok: bool
    content: dict
    error: str | None = None


def _concept() -> Concept:
    return Concept(
        id="c-llm",
        level=2,
        canonical_label="Applied Data Science",
        parents=["parent"],
    )


def test_llm_validator_success() -> None:
    policy = ValidationPolicy()
    validator = LLMValidator(
        policy,
        runner=lambda prompt_key, variables: DummyResponse(
            ok=True,
            content={"validated": True, "reason": "Evidence strongly supports", "confidence": 0.9},
        ),
    )

    evidence = [
        EvidenceSnippet(
            text="Applied data science is taught at Example University.",
            url="https://example.edu/programs",
            institution="Example University",
            score=1.2,
        )
    ]

    result = validator.validate_concept(_concept(), evidence)
    assert result.passed
    assert result.confidence > 0.0
    assert "passed" in result.summary


def test_llm_validator_handles_failure() -> None:
    policy = ValidationPolicy()
    validator = LLMValidator(
        policy,
        runner=lambda prompt_key, variables: DummyResponse(ok=False, content={}, error="timeout"),
    )

    evidence = [
        EvidenceSnippet(
            text="Evidence text",
            url="https://example.edu",
            institution="Example",
            score=0.6,
        )
    ]

    result = validator.validate_concept(_concept(), evidence)
    assert not result.passed
    assert "failed" in result.summary.lower()


def test_prepare_evidence_respects_token_limit() -> None:
    base_policy = ValidationPolicy()
    policy = base_policy.model_copy(update={
        "llm": base_policy.llm.model_copy(update={"max_evidence_tokens": 10})
    })
    validator = LLMValidator(policy)

    evidence = [
        EvidenceSnippet(
            text="This is a fairly long snippet about applied data science and its curriculum." * 5,
            url="https://example.edu",
            institution="Example",
            score=0.8,
        ),
        EvidenceSnippet(
            text="Second snippet",
            url="https://example.edu/second",
            institution="Example",
            score=0.7,
        ),
    ]

    payload = validator.prepare_evidence(evidence)
    assert payload
    assert len(payload) == 1  # token limit should truncate after first snippet
