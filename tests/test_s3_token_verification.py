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
        max_tokens_per_level={0: 5, 1: 5, 2: 5, 3: 5},
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


def test_processor_llm_override_when_permitted() -> None:
    policy = _policy(prefer_rule_over_llm=False)
    engine = TokenRuleEngine(policy=policy, minimal_form=_label_policy().minimal_canonical_form)
    verifier = LLMTokenVerifier(runner=lambda prompt, vars: {"pass": True, "reason": "abbreviation is acceptable"})
    processor = S3Processor(rule_engine=engine, llm_verifier=verifier, policy=policy)

    candidate = _candidate(
        "Interdisciplinary Computer Science and Engineering Program",
        "interdisciplinary computer science and engineering program",
        level=1,
        count=2,
    )
    evidence = VerificationInput(
        candidate=candidate,
        rationale=Rationale(),
        institutions=["MIT"],
        record_fingerprints=["rec-1"],
    )
    result = processor.process([evidence])
    assert result.stats["verified"] == 1
    assert result.stats["passed_rule"] == 1
    assert result.stats["failed_rule"] == 0
    assert result.stats["llm_called"] == 0
    decision: TokenVerificationDecision = result.verified[0]
    assert decision.passed is True
    assert decision.llm_result is None
    assert decision.rule_evaluation.passed is True
    assert "bypass:multi_token" in decision.rationale.reasons


def test_processor_respects_rule_priority_when_configured() -> None:
    policy = _policy(prefer_rule_over_llm=True)
    engine = TokenRuleEngine(policy=policy, minimal_form=_label_policy().minimal_canonical_form)
    verifier = LLMTokenVerifier(runner=lambda prompt, vars: {"pass": True, "reason": "domain term"})
    processor = S3Processor(rule_engine=engine, llm_verifier=verifier, policy=policy)

    candidate = _candidate(
        "Extended Quantum Computing and Information Science Program",
        "extended quantum computing and information science program",
        level=1,
        count=2,
    )
    evidence = VerificationInput(
        candidate=candidate,
        rationale=Rationale(),
        institutions=["Stanford"],
        record_fingerprints=["rec-2"],
    )
    result = processor.process([evidence])
    assert result.stats["verified"] == 1
    assert result.stats["failed"] == 0
    assert result.stats["passed_rule"] == 1
    assert result.stats["llm_called"] == 0
    decision: TokenVerificationDecision = result.verified[0]
    assert decision.passed is True
    assert decision.rule_evaluation.passed is True
    assert decision.llm_result is None
    assert "bypass:multi_token" in decision.rationale.reasons


def test_processor_skips_llm_when_rules_pass() -> None:
    policy = _policy(prefer_rule_over_llm=False)
    engine = TokenRuleEngine(policy=policy, minimal_form=_label_policy().minimal_canonical_form)
    calls: list[str] = []

    def _runner(prompt: str, vars: dict) -> dict:
        calls.append("called")
        return {"pass": True, "reason": ""}

    verifier = LLMTokenVerifier(runner=_runner)
    processor = S3Processor(rule_engine=engine, llm_verifier=verifier, policy=policy)

    candidate = _candidate("Robotics", "robotics", level=1, count=1)
    evidence = VerificationInput(
        candidate=candidate,
        rationale=Rationale(),
        institutions=["MIT"],
        record_fingerprints=["rec-42"],
    )

    result = processor.process([evidence])

    assert not calls
    assert result.stats["verified"] == 1
    assert result.stats["llm_called"] == 0


def test_rule_engine_flags_known_venue_alias() -> None:
    policy = _policy()
    engine = TokenRuleEngine(policy=policy, minimal_form=_label_policy().minimal_canonical_form)

    evaluation = engine.apply_all_rules("NeurIPS", level=3)

    assert evaluation.passed is False
    assert any("neurips" in reason.lower() for reason in evaluation.reasons)


def test_processor_adds_rule_suggestions_to_aliases() -> None:
    policy = _policy(prefer_rule_over_llm=False)
    engine = TokenRuleEngine(policy=policy, minimal_form=_label_policy().minimal_canonical_form)
    verifier = LLMTokenVerifier(runner=lambda prompt, vars: {"pass": True, "reason": "standard label"})
    processor = S3Processor(rule_engine=engine, llm_verifier=verifier, policy=policy)

    candidate = _candidate("Machine-Learning", "machine-learning", level=2, count=1)
    evidence = VerificationInput(
        candidate=candidate,
        rationale=Rationale(),
        institutions=["CMU"],
        record_fingerprints=["rec-99"],
    )

    result = processor.process([evidence])

    decision = result.verified[0]
    assert decision.passed is True
    assert any(alias.lower() == "machine learning" for alias in decision.candidate.aliases)
