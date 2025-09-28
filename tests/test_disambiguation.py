import json

from taxonomy.config.policies import DisambiguationPolicy
from taxonomy.entities.core import (
    Concept,
    Provenance,
    Rationale,
    SourceMeta,
    SourceRecord,
    SupportStats,
)
from taxonomy.llm.models import LLMResponse, TokenUsage
from taxonomy.pipeline.disambiguation.detector import AmbiguityDetector
from taxonomy.pipeline.disambiguation.llm import LLMDisambiguator, LLMSenseDefinition
from taxonomy.pipeline.disambiguation.processor import DisambiguationProcessor
from taxonomy.pipeline.disambiguation.splitter import ConceptSplitter
from taxonomy.utils.context_features import ContextWindow


def make_concept(concept_id: str, parents: list[str]) -> Concept:
    return Concept.model_validate(
        {
            "id": concept_id,
            "level": 1,
            "canonical_label": "Machine Learning",
            "parents": parents,
            "aliases": [],
            "support": SupportStats(records=6, institutions=4, count=20),
            "validation_metadata": {},
        }
    )


def make_context(concept_id: str, text: str, parent: str, institution: str) -> ContextWindow:
    return ContextWindow(
        concept_id=concept_id,
        text=text,
        institution=institution,
        parent_lineage=f"L1:{parent}",
        source_index=0,
    )


def make_record(text: str, institution: str) -> SourceRecord:
    provenance = Provenance(institution=institution, url="https://example.org")
    return SourceRecord(text=text, provenance=provenance, meta=SourceMeta())


def fake_llm_response() -> LLMResponse:
    content = {
        "separable": True,
        "confidence": 0.9,
        "senses": [
            {
                "label": "Research",
                "gloss": "Focus on research programs",
                "parent_hints": ["p1"],
                "evidence_indices": [0],
            },
            {
                "label": "Teaching",
                "gloss": "Focus on teaching curriculum",
                "parent_hints": ["p2"],
                "evidence_indices": [1],
            },
        ],
    }
    return LLMResponse.success(content, json.dumps(content), TokenUsage(), {}, 0.01)


def test_ambiguity_detector_flags_divergent_parents():
    policy = DisambiguationPolicy(min_context_overlap_threshold=0.6)
    detector = AmbiguityDetector(policy)
    concept_a = make_concept("a", ["p1"])
    concept_b = make_concept("b", ["p2"])
    contexts = {
        "a": [make_context("a", "robotics research lab", "p1", "inst1")],
        "b": [make_context("b", "finance teaching track", "p2", "inst2")],
    }
    candidates = detector.detect_collisions([concept_a, concept_b], contexts)
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.parent_divergence > 0.5
    assert candidate.context_overlap < policy.min_context_overlap_threshold


def test_llm_disambiguator_parses_senses():
    policy = DisambiguationPolicy()
    disambiguator = LLMDisambiguator(policy, runner=lambda *_: fake_llm_response())
    concept = make_concept("a", ["p1"])
    contexts = {"a": [make_context("a", "research domain", "p1", "inst1")]}
    result = disambiguator.check_separability(
        "Machine Learning",
        concept.level,
        [concept],
        contexts,
    )
    assert result.separable is True
    assert len(result.senses) == 2
    assert all(isinstance(sense, LLMSenseDefinition) for sense in result.senses)


def test_concept_splitter_builds_new_concepts():
    policy = DisambiguationPolicy()
    splitter = ConceptSplitter(policy)
    source = make_concept("a", ["p1"])
    contexts = {
        "a": [
            make_context("a", "robotics research lab", "p1", "inst1"),
            make_context("a", "curriculum design seminar", "p1", "inst2"),
        ]
    }
    senses = [
        LLMSenseDefinition(label="Research", gloss="Research focus", confidence=0.9, parent_hints=["p1"], evidence_indices=[0]),
        LLMSenseDefinition(label="Teaching", gloss="Teaching focus", confidence=0.8, parent_hints=["p2"], evidence_indices=[1]),
    ]
    parent_mapping = {"Research": ["p1"], "Teaching": ["p2"]}
    evidence_mapping = {"Research": [0], "Teaching": [1]}
    decision = splitter.split(
        source,
        [source],
        senses,
        parent_mapping,
        evidence_mapping,
        confidence=0.85,
        context_lookup=contexts,
    )
    assert len(decision.new_concepts) == 2
    assert all(concept.id.startswith("a::split::") for concept in decision.new_concepts)
    assert decision.split_op.source_id == "a"
    assert len(decision.split_op.new_ids) == 2
    evidence = decision.split_op.evidence or {}
    senses_payload = evidence.get("senses", [])
    assert senses_payload and all("exemplars" in sense for sense in senses_payload)
    first_exemplar = senses_payload[0]["exemplars"][0]
    assert first_exemplar["text"] == "robotics research lab"


def test_splitter_combines_group_support_and_rationales():
    policy = DisambiguationPolicy()
    splitter = ConceptSplitter(policy)

    primary = make_concept("a", ["p1"])
    secondary = make_concept("b", ["p2"])

    primary.aliases.append("ML Research")
    secondary.aliases.append("ML Teaching")

    primary.support = SupportStats(records=6, institutions=4, count=20)
    secondary.support = SupportStats(records=3, institutions=2, count=7)

    primary.rationale = Rationale(
        passed_gates={"seed": True},
        reasons=["primary rationale"],
        thresholds={"seed": 0.3},
    )
    secondary.rationale = Rationale(
        passed_gates={"seed": False},
        reasons=["secondary rationale"],
        thresholds={"seed": 0.7},
    )

    contexts = {
        "a": [make_context("a", "research snippet", "p1", "inst1")],
        "b": [make_context("b", "teaching snippet", "p2", "inst2")],
    }

    senses = [
        LLMSenseDefinition(label="Research", gloss="Research focus", confidence=0.9, parent_hints=["p1"], evidence_indices=[0]),
        LLMSenseDefinition(label="Teaching", gloss="Teaching focus", confidence=0.8, parent_hints=["p2"], evidence_indices=[1]),
    ]
    parent_mapping = {"Research": ["p1"], "Teaching": ["p2"]}
    evidence_mapping = {"Research": [0], "Teaching": [1]}

    decision = splitter.split(
        primary,
        [primary, secondary],
        senses,
        parent_mapping,
        evidence_mapping,
        confidence=0.9,
        context_lookup=contexts,
    )

    total_records = sum(concept.support.records for concept in decision.new_concepts)
    total_institutions = sum(concept.support.institutions for concept in decision.new_concepts)
    total_count = sum(concept.support.count for concept in decision.new_concepts)

    assert total_records == 9
    assert total_institutions == 6
    assert total_count == 27

    for concept in decision.new_concepts:
        assert "ML Teaching" in concept.aliases
        assert any("primary rationale" in reason for reason in concept.rationale.reasons)
        assert any("secondary rationale" in reason for reason in concept.rationale.reasons)
        assert concept.rationale.passed_gates["seed"] is False


def test_disambiguation_processor_creates_split_ops():
    policy = DisambiguationPolicy(min_context_overlap_threshold=0.6)
    disambiguator = LLMDisambiguator(policy, runner=lambda *_: fake_llm_response())
    processor = DisambiguationProcessor(policy, disambiguator=disambiguator)

    concept_a = make_concept("a", ["p1"])
    concept_b = make_concept("b", ["p2"])

    context_index = {
        "a": [make_record("Machine Learning research initiative", "inst1")],
        "b": [make_record("Machine Learning teaching center", "inst2")],
    }

    outcome = processor.process([concept_a, concept_b], context_index)

    assert outcome.split_ops, "expected at least one split operation"
    split_op = outcome.split_ops[0]
    assert split_op.source_id in {"a", "b"}
    assert len(split_op.new_ids) == 2
    new_concepts = {concept.id: concept for concept in outcome.concepts}
    aggregated_support = sum(concept.support.records for concept in [concept_a, concept_b])
    aggregated_support_counts = sum(concept.support.count for concept in [concept_a, concept_b])
    aggregated_institutions = sum(concept.support.institutions for concept in [concept_a, concept_b])

    total_records = 0
    total_counts = 0
    total_institutions = 0
    for new_id in split_op.new_ids:
        assert new_id in new_concepts
        concept = new_concepts[new_id]
        assert concept.rationale.passed_gates["disambiguation"] is True
        total_records += concept.support.records
        total_counts += concept.support.count
        total_institutions += concept.support.institutions

    assert total_records == aggregated_support
    assert total_counts == aggregated_support_counts
    assert total_institutions == aggregated_institutions
