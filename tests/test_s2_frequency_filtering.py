"""Unit tests for the S2 frequency filtering components."""

from __future__ import annotations

import pytest

from taxonomy.config.policies import (
    FrequencyFilteringPolicy,
    InstitutionPolicy,
    LevelThreshold,
    LevelThresholds,
    NearDuplicateDedupPolicy,
)
from taxonomy.config.settings import Settings
from taxonomy.entities.core import Candidate, SupportStats
from taxonomy.observability import ObservabilityContext
from taxonomy.pipeline.s2_frequency_filtering.aggregator import (
    CandidateAggregator,
    CandidateEvidence,
)
from taxonomy.pipeline.s2_frequency_filtering.institution_resolver import InstitutionResolver
from taxonomy.pipeline.s2_frequency_filtering.processor import S2Processor


def _thresholds() -> LevelThresholds:
    return LevelThresholds(
        level_0=LevelThreshold(min_institutions=1, min_src_count=1),
        level_1=LevelThreshold(min_institutions=1, min_src_count=1),
        level_2=LevelThreshold(min_institutions=2, min_src_count=1),
        level_3=LevelThreshold(min_institutions=2, min_src_count=3),
    )


def _candidate(level: int, label: str, normalized: str, parents: list[str], count: int = 1) -> Candidate:
    return Candidate(
        level=level,
        label=label,
        normalized=normalized,
        parents=parents,
        aliases=[label],
        support=SupportStats(records=count, institutions=1, count=count),
    )


def _sample_evidence_bundle() -> list[CandidateEvidence]:
    """Create a mixture of passing and failing S2 inputs for testing."""

    resolver_policy = InstitutionPolicy(canonical_mappings={}, campus_vs_system="prefer-campus")
    resolver = InstitutionResolver(policy=resolver_policy)
    aggregator = CandidateAggregator(thresholds=_thresholds(), resolver=resolver)

    keep_primary = _candidate(2, "Computer Vision", "computer vision", ["ai"], count=2)
    keep_alias = _candidate(2, "Computer Vision", "computer vision", ["AI"], count=1)
    drop_candidate = _candidate(2, "Quantum Vision", "quantum vision", ["ai"], count=1)

    evidence = [
        CandidateEvidence(candidate=keep_primary, institutions={"MIT"}, record_fingerprints={"rec-1"}),
        CandidateEvidence(candidate=keep_alias, institutions={"Stanford"}, record_fingerprints={"rec-2"}),
        CandidateEvidence(candidate=drop_candidate, institutions={"OnlyOne"}, record_fingerprints={"rec-3"}),
    ]
    result = aggregator.aggregate(evidence)
    # ensure fixture provides expected pass/fail breakdown for downstream assertions
    assert len(result.kept) == 1
    assert len(result.dropped) == 1
    return evidence


@pytest.fixture
def s2_observability_context() -> ObservabilityContext:
    settings = Settings()
    obs_policy = settings.policies.observability.model_copy(
        update={
            "evidence_sampling_rate": 1.0,
            "max_evidence_samples_per_phase": 50,
        }
    )
    return ObservabilityContext(run_id="s2-test", policy=obs_policy)


def test_institution_resolver_normalizes_variants() -> None:
    policy = InstitutionPolicy(
        canonical_mappings={
            "mit": "Massachusetts Institute of Technology",
            "massachusetts institute of technology": "Massachusetts Institute of Technology",
        },
        campus_vs_system="prefer-system",
    )
    resolver = InstitutionResolver(policy=policy)

    assert resolver.resolve_identity("MIT") == "Massachusetts Institute of Technology"
    assert resolver.resolve_identity("Massachusetts Institute of Technology") == "Massachusetts Institute of Technology"
    assert resolver.resolve_identity("University of California, Berkeley") == "University of California"


def test_aggregator_groups_by_label_and_parents() -> None:
    resolver = InstitutionResolver(policy=InstitutionPolicy(canonical_mappings={}, campus_vs_system="prefer-campus"))
    aggregator = CandidateAggregator(thresholds=_thresholds(), resolver=resolver)

    cand_a = _candidate(2, "Computer Vision", "computer vision", ["ai"])
    cand_b = _candidate(2, "Computer Vision", "computer vision", ["AI"], count=2)

    evidence = [
        CandidateEvidence(candidate=cand_a, institutions={"MIT"}, record_fingerprints={"rec-a"}),
        CandidateEvidence(candidate=cand_b, institutions={"Stanford"}, record_fingerprints={"rec-b"}),
    ]
    result = aggregator.aggregate(evidence)

    assert result.stats["aggregated_groups"] == 1
    assert len(result.kept) == 1
    kept = result.kept[0]
    assert kept.candidate.support.institutions == 2
    assert kept.candidate.support.records == 2
    assert kept.candidate.support.count == 3
    assert kept.rationale.passed_gates["frequency"] is True
    assert "institutions=" in kept.rationale.reasons[0]


def test_aggregator_drops_when_thresholds_not_met() -> None:
    resolver = InstitutionResolver(policy=InstitutionPolicy(canonical_mappings={}, campus_vs_system="prefer-campus"))
    aggregator = CandidateAggregator(thresholds=_thresholds(), resolver=resolver)

    cand = _candidate(2, "Robotics", "robotics", ["engineering"], count=2)
    evidence = [
        CandidateEvidence(candidate=cand, institutions={"Carnegie Mellon"}, record_fingerprints={"rec-1", "rec-2"}),
    ]
    result = aggregator.aggregate(evidence)

    assert len(result.kept) == 0
    assert len(result.dropped) == 1
    dropped = result.dropped[0]
    assert dropped.candidate.support.institutions == 1
    assert dropped.rationale.passed_gates["frequency"] is False
    assert any("institutions=" in reason for reason in dropped.rationale.reasons)


def test_records_threshold_controls_decision() -> None:
    resolver = InstitutionResolver(policy=InstitutionPolicy(canonical_mappings={}, campus_vs_system="prefer-campus"))
    aggregator = CandidateAggregator(thresholds=_thresholds(), resolver=resolver)

    cand_a = Candidate(
        level=3,
        label="Quantum Vision",
        normalized="quantum vision",
        parents=["computer science"],
        aliases=["Quantum Vision"],
        support=SupportStats(records=3, institutions=1, count=3),
    )
    cand_b = Candidate(
        level=3,
        label="Quantum Vision",
        normalized="quantum vision",
        parents=["computer science"],
        aliases=["Quantum Vision"],
        support=SupportStats(records=2, institutions=1, count=2),
    )
    evidence = [
        CandidateEvidence(candidate=cand_a, institutions={"Institution A"}, record_fingerprints={"rec-1"}),
        CandidateEvidence(candidate=cand_b, institutions={"Institution B"}, record_fingerprints={"rec-2"}),
    ]

    result = aggregator.aggregate(evidence)

    assert not result.kept
    assert len(result.dropped) == 1
    dropped = result.dropped[0]
    assert dropped.candidate.support.institutions == 2
    assert dropped.candidate.support.records == 2
    assert result.stats["dropped_insufficient_support"] == 1


def test_missing_institutions_collapse_to_placeholder() -> None:
    resolver = InstitutionResolver(policy=InstitutionPolicy(canonical_mappings={}, campus_vs_system="prefer-campus"))
    aggregator = CandidateAggregator(thresholds=_thresholds(), resolver=resolver)

    cand = _candidate(2, "Unlabeled", "unlabeled", ["parent"], count=1)
    evidence = [
        CandidateEvidence(candidate=cand, institutions=set(), record_fingerprints={"rec-1"}),
        CandidateEvidence(candidate=cand, institutions=set(), record_fingerprints={"rec-2"}),
    ]

    result = aggregator.aggregate(evidence)

    assert len(result.dropped) == 1
    dropped = result.dropped[0]
    assert dropped.candidate.support.institutions == 1
    assert dropped.institutions == ["placeholder::unknown"]


def test_near_duplicate_records_collapsed_by_policy() -> None:
    resolver = InstitutionResolver(policy=InstitutionPolicy(canonical_mappings={}, campus_vs_system="prefer-campus"))
    frequency_policy = FrequencyFilteringPolicy(
        near_duplicate=NearDuplicateDedupPolicy(
            enabled=True,
            prefix_delimiters=["#"],
            strip_numeric_suffix=True,
            min_prefix_length=4,
        )
    )
    aggregator = CandidateAggregator(
        thresholds=_thresholds(),
        resolver=resolver,
        frequency_policy=frequency_policy,
    )

    cand = _candidate(1, "AI", "ai", ["root"], count=2)
    evidence = [
        CandidateEvidence(
            candidate=cand,
            institutions={"Institution A"},
            record_fingerprints={"paper-123#v1", "paper-123#v2"},
        ),
    ]

    result = aggregator.aggregate(evidence)

    assert len(result.kept) == 1
    kept = result.kept[0]
    assert kept.candidate.support.records == 1
    assert len(kept.record_fingerprints) == 1


def test_s2_processor_updates_observability_counters(s2_observability_context: ObservabilityContext) -> None:
    resolver = InstitutionResolver(policy=InstitutionPolicy(canonical_mappings={}, campus_vs_system="prefer-campus"))
    aggregator = CandidateAggregator(thresholds=_thresholds(), resolver=resolver)
    processor = S2Processor(aggregator=aggregator, observability=s2_observability_context)

    evidence = _sample_evidence_bundle()
    result = processor.process(evidence)

    snapshot = s2_observability_context.snapshot()
    counters = snapshot.counters["S2"]
    assert counters["candidates_in"] == len(evidence)
    assert counters["kept"] == 1
    assert counters["dropped_insufficient_support"] == 1
    assert result.stats["kept"] == 1
    assert result.stats["dropped"] == 1
    assert result.stats["observability_checksum"] == snapshot.checksum
    assert s2_observability_context.registry.current_phase() is None


def test_s2_processor_records_evidence_and_performance(s2_observability_context: ObservabilityContext) -> None:
    resolver = InstitutionResolver(policy=InstitutionPolicy(canonical_mappings={}, campus_vs_system="prefer-campus"))
    aggregator = CandidateAggregator(thresholds=_thresholds(), resolver=resolver)
    processor = S2Processor(aggregator=aggregator, observability=s2_observability_context)

    evidence = _sample_evidence_bundle()
    processor.process(evidence)

    snapshot = s2_observability_context.snapshot()
    samples = snapshot.evidence.get("samples", {}).get("S2", [])
    outcomes = {sample.get("outcome") for sample in samples}
    assert "kept" in outcomes
    assert "dropped_insufficient_support" in outcomes

    performance = snapshot.performance.get("S2", {})
    assert performance.get("candidates_processed") == len(evidence)
    assert "elapsed_seconds" in performance


def test_s2_processor_maintains_stats_without_observability() -> None:
    resolver = InstitutionResolver(policy=InstitutionPolicy(canonical_mappings={}, campus_vs_system="prefer-campus"))
    aggregator = CandidateAggregator(thresholds=_thresholds(), resolver=resolver)
    processor = S2Processor(aggregator=aggregator)

    evidence = _sample_evidence_bundle()
    result = processor.process(evidence)

    assert result.stats["kept"] == 1
    assert result.stats["dropped"] == 1
    assert "observability_checksum" not in result.stats
