"""Unit tests for the S2 frequency filtering components."""

from __future__ import annotations

from taxonomy.config.policies import InstitutionPolicy, LevelThreshold, LevelThresholds
from taxonomy.entities.core import Candidate, SupportStats
from taxonomy.pipeline.s2_frequency_filtering.aggregator import (
    CandidateAggregator,
    CandidateEvidence,
)
from taxonomy.pipeline.s2_frequency_filtering.institution_resolver import InstitutionResolver


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
