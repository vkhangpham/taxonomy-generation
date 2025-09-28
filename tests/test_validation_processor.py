"""Integration-style tests for the validation processor."""

from __future__ import annotations

from datetime import datetime, timezone

from taxonomy.config.policies import ValidationPolicy
from taxonomy.config.settings import Settings
from taxonomy.entities.core import Concept, PageSnapshot, FindingMode, ValidationFinding
from taxonomy.pipeline.validation.processor import ValidationProcessor
from taxonomy.pipeline.validation.llm import LLMResult
from types import SimpleNamespace
from unittest.mock import patch
from taxonomy.pipeline.validation import main as validation_main


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


def _concept(label: str, level: int = 2) -> Concept:
    return Concept(
        id=f"concept-{label.lower().replace(' ', '-')}",
        level=level,
        canonical_label=label,
        parents=["parent"] if level > 0 else [],
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


def test_processor_tie_break_uses_evidence_strength() -> None:
    base_policy = ValidationPolicy()
    policy = base_policy.model_copy(
        update={
            "web": base_policy.web.model_copy(update={"min_snippet_matches": 2}),
            "llm": base_policy.llm.model_copy(update={"entailment_enabled": False}),
            "aggregation": base_policy.aggregation.model_copy(
                update={
                    "rule_weight": 1.0,
                    "web_weight": 1.0,
                    "llm_weight": 0.0,
                    "tie_break_conservative": True,
                    "tie_break_min_strength": 0.8,
                }
            ),
        }
    )

    processor = ValidationProcessor(policy, enable_llm=False)
    processor.prepare_evidence([
        _snapshot("Applied Data Science is a flagship program with strong outcomes."),
    ])

    outcome = processor.process([_concept("Applied Data Science")])[0]

    # Rule passes, web fails due to threshold but evidence strength triggers override
    assert outcome.decision.passed
    assert outcome.decision.scores["llm"] == 0.0


def test_processor_tie_break_respects_min_strength() -> None:
    base_policy = ValidationPolicy()
    policy = base_policy.model_copy(
        update={
            "web": base_policy.web.model_copy(update={"min_snippet_matches": 2}),
            "llm": base_policy.llm.model_copy(update={"entailment_enabled": False}),
            "aggregation": base_policy.aggregation.model_copy(
                update={
                    "rule_weight": 1.0,
                    "web_weight": 1.0,
                    "llm_weight": 0.0,
                    "tie_break_conservative": True,
                    "tie_break_min_strength": 1.3,
                }
            ),
        }
    )

    processor = ValidationProcessor(policy, enable_llm=False)
    processor.prepare_evidence([
        _snapshot("Applied Data Science is a flagship program with strong outcomes."),
    ])

    outcome = processor.process([_concept("Applied Data Science")])[0]

    assert not outcome.decision.passed


def test_processor_treats_unknown_web_as_non_voting() -> None:
    base_policy = ValidationPolicy()
    policy = base_policy.model_copy(
        update={
            "llm": base_policy.llm.model_copy(update={"entailment_enabled": False}),
            "aggregation": base_policy.aggregation.model_copy(
                update={"rule_weight": 1.0, "web_weight": 1.0}
            ),
        }
    )

    processor = ValidationProcessor(policy, enable_llm=False)
    processor.prepare_evidence([])

    outcome = processor.process([_concept("Quantum Computing")])[0]

    assert outcome.decision.passed
    assert outcome.decision.scores["web"] == 0.0
    web_findings = [finding for finding in outcome.decision.findings if finding.mode == FindingMode.WEB]
    assert web_findings
    assert web_findings[0].detail.startswith("Web evidence unavailable")


def test_processor_stats_include_observability_counters() -> None:
    base_policy = ValidationPolicy()
    policy = base_policy.model_copy(
        update={
            "rules": base_policy.rules.model_copy(update={"forbidden_patterns": ["neurips"]}),
            "llm": base_policy.llm.model_copy(update={"entailment_enabled": True}),
        }
    )

    processor = ValidationProcessor(policy, enable_llm=True)

    processor.prepare_evidence([
        _snapshot("Applied Data Science is a flagship program."),
    ])

    def _llm_stub(concept: Concept, evidence: list[object]) -> LLMResult:
        passed = concept.canonical_label.startswith("Applied")
        detail = "LLM ok" if passed else "LLM insufficient evidence"
        finding = ValidationFinding(
            concept_id=concept.id,
            mode=FindingMode.LLM,
            passed=passed,
            detail=detail,
        )
        return LLMResult(passed=passed, confidence=0.6 if passed else 0.1, findings=[finding], summary=detail)

    processor._llm_validator = SimpleNamespace(validate_concept=_llm_stub)  # type: ignore[attr-defined]

    concepts = [
        _concept("Applied Data Science"),
        _concept("Quantum Computing"),
        _concept("NeurIPS", level=3),
    ]

    processor.process(concepts)
    stats = processor.stats

    assert stats["concepts"] == 3
    assert stats["checked"] == 3
    assert stats["rule_passed"] == 2
    assert stats["rule_failed"] == 1
    assert stats["web_passed"] == 1
    assert stats["web_failed"] >= 1
    assert stats["llm_passed"] == 1
    assert stats["llm_failed"] == 2
    assert stats["validation_passed"] == 1
    assert stats["passed_all"] == 1


def test_validate_concepts_mode_flags(tmp_path) -> None:
    settings = Settings()
    instances: list[object] = []

    class DummyProcessor:
        def __init__(self, _policy, *, enable_web: bool, enable_llm: bool) -> None:
            self.enable_web = enable_web
            self.enable_llm = enable_llm
            self._stats: dict = {}
            instances.append(self)

        def prepare_evidence(self, snapshots) -> None:  # pragma: no cover - interface stub
            self.snapshots = snapshots

        def process(self, concepts):  # pragma: no cover - interface stub
            self.concepts = list(concepts)
            return []

        @property
        def stats(self) -> dict:
            return self._stats

    output_path = tmp_path / "out.jsonl"

    with (
        patch.object(validation_main, "ValidationProcessor", DummyProcessor),
        patch.object(validation_main, "load_concepts", return_value=[_concept("Applied Data Science")]),
        patch.object(validation_main, "write_validated_concepts"),
        patch.object(validation_main, "write_validation_findings"),
        patch.object(validation_main, "export_evidence_samples"),
        patch.object(validation_main, "generate_validation_metadata", return_value={}),
    ):
        validation_main.validate_concepts(
            concepts_path="concepts.jsonl",
            snapshots_path=None,
            output_path=output_path,
            mode="llm",
            settings=settings,
        )

    assert instances
    assert instances[0].enable_web is False
    assert instances[0].enable_llm is True


def test_validate_concepts_mode_flags_web_only(tmp_path) -> None:
    settings = Settings()
    instances: list[object] = []

    class DummyProcessor:
        def __init__(self, _policy, *, enable_web: bool, enable_llm: bool) -> None:
            self.enable_web = enable_web
            self.enable_llm = enable_llm
            self._stats: dict = {}
            instances.append(self)

        def prepare_evidence(self, snapshots) -> None:  # pragma: no cover - interface stub
            self.snapshots = snapshots

        def process(self, concepts):  # pragma: no cover - interface stub
            self.concepts = list(concepts)
            return []

        @property
        def stats(self) -> dict:
            return self._stats

    output_path = tmp_path / "out.jsonl"

    with (
        patch.object(validation_main, "ValidationProcessor", DummyProcessor),
        patch.object(validation_main, "load_concepts", return_value=[_concept("Applied Data Science")]),
        patch.object(validation_main, "write_validated_concepts"),
        patch.object(validation_main, "write_validation_findings"),
        patch.object(validation_main, "export_evidence_samples"),
        patch.object(validation_main, "generate_validation_metadata", return_value={}),
    ):
        validation_main.validate_concepts(
            concepts_path="concepts.jsonl",
            snapshots_path=None,
            output_path=output_path,
            mode="web",
            settings=settings,
        )

    assert instances
    assert instances[0].enable_web is True
    assert instances[0].enable_llm is False
