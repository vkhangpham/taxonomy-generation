"""Unit tests for the S3 token verification pipeline."""

from __future__ import annotations

from taxonomy.config.policies import LabelPolicy, MinimalCanonicalForm, SingleTokenVerificationPolicy
from taxonomy.entities.core import Candidate, Rationale, SupportStats
from taxonomy.pipeline.s3_token_verification.processor import (
    S3Processor,
    TokenVerificationDecision,
    VerificationInput,
)
from taxonomy.pipeline.s3_token_verification.rules import TokenRuleEngine
from taxonomy.pipeline.s3_token_verification.verifier import LLMTokenVerifier


def _policy(prefer_rule_over_llm: bool = False) -> SingleTokenVerificationPolicy:
    return SingleTokenVerificationPolicy(
        max_tokens_per_level={0: 2, 1: 2, 2: 3, 3: 2},
        forbidden_punctuation=["-", "."],
        allowlist=["artificial intelligence"],
        venue_names_forbidden=True,
        hyphenated_compounds_allowed=False,
        prefer_rule_over_llm=prefer_rule_over_llm,
    )


def _label_policy() -> LabelPolicy:
    return LabelPolicy(minimal_canonical_form=MinimalCanonicalForm())


def _candidate(label: str, normalized: str, level: int, count: int = 1) -> Candidate:
    return Candidate(
        level=level,
        label=label,
        normalized=normalized,
        parents=[],
        aliases=[label],
        support=SupportStats(records=count, institutions=1, count=count),
    )


def test_rule_engine_allowlist_bypass() -> None:
    engine = TokenRuleEngine(policy=_policy(), minimal_form=_label_policy().minimal_canonical_form)
    evaluation = engine.apply_all_rules("artificial intelligence", level=1)
    assert evaluation.passed is True
    assert evaluation.allowlist_hit is True
    assert evaluation.reasons == ["label matched allowlist"]


def test_processor_allows_llm_override_when_permitted() -> None:
    policy = _policy(prefer_rule_over_llm=False)
    engine = TokenRuleEngine(policy=policy, minimal_form=_label_policy().minimal_canonical_form)
    verifier = LLMTokenVerifier(runner=lambda prompt, vars: {"pass": True, "reason": "abbreviation is acceptable"})
    processor = S3Processor(rule_engine=engine, llm_verifier=verifier, policy=policy)

    candidate = _candidate("Computer Science Department", "computer science department", level=1, count=2)
    evidence = VerificationInput(
        candidate=candidate,
        rationale=Rationale(),
        institutions=["MIT"],
        record_fingerprints=["rec-1"],
    )
    result = processor.process([evidence])
    assert result.stats == {"candidates_in": 1, "verified": 1, "failed": 0}
    decision: TokenVerificationDecision = result.verified[0]
    assert decision.passed is True
    assert decision.llm_result is not None and decision.llm_result.passed is True
    assert decision.rule_evaluation.passed is False


def test_processor_respects_rule_priority_when_configured() -> None:
    policy = _policy(prefer_rule_over_llm=True)
    engine = TokenRuleEngine(policy=policy, minimal_form=_label_policy().minimal_canonical_form)
    verifier = LLMTokenVerifier(runner=lambda prompt, vars: {"pass": True, "reason": "domain term"})
    processor = S3Processor(rule_engine=engine, llm_verifier=verifier, policy=policy)

    candidate = _candidate("Quantum-Computing Center", "quantum computing center", level=1, count=2)
    evidence = VerificationInput(
        candidate=candidate,
        rationale=Rationale(),
        institutions=["Stanford"],
        record_fingerprints=["rec-2"],
    )
    result = processor.process([evidence])
    assert result.stats == {"candidates_in": 1, "verified": 0, "failed": 1}
    decision: TokenVerificationDecision = result.failed[0]
    assert decision.passed is False
    assert decision.rule_evaluation.passed is False
    assert decision.llm_result is not None and decision.llm_result.passed is True
