from taxonomy.config.policies import DeduplicationPolicy, DeduplicationThresholds
from taxonomy.entities.core import Concept, SupportStats
from taxonomy.pipeline.deduplication.blocking import CompositeBlocker, PrefixBlocker
from taxonomy.pipeline.deduplication.processor import DeduplicationProcessor
from taxonomy.pipeline.deduplication.similarity import SimilarityScorer


def make_concept(
    concept_id: str,
    label: str,
    *,
    level: int = 1,
    parents: list[str] | None = None,
    aliases: list[str] | None = None,
    institutions: int = 2,
    records: int = 1,
    count: int = 5,
) -> Concept:
    return Concept(
        id=concept_id,
        level=level,
        canonical_label=label,
        parents=parents or ["root"],
        aliases=aliases or [],
        support=SupportStats(records=records, institutions=institutions, count=count),
    )


def base_policy(**overrides) -> DeduplicationPolicy:
    policy = DeduplicationPolicy(
        thresholds=DeduplicationThresholds(l0_l1=0.8, l2_l3=0.75),
        merge_policy="deterministic",
        **overrides,
    )
    return policy


def test_prefix_blocker_creates_expected_blocks():
    policy = base_policy(prefix_length=4)
    blocker = CompositeBlocker([PrefixBlocker(policy)], policy)
    concepts = [
        make_concept("c1", "Computer Science"),
        make_concept("c2", "Computer Security"),
        make_concept("c3", "Artificial Intelligence"),
    ]
    output = blocker.build_blocks(concepts)
    keys = list(output.blocks)
    assert any(key.startswith("prefix:") for key in keys)
    assert output.metrics.total_blocks >= 1
    assert output.metrics.strategy_counts["prefix"] >= 1


def test_similarity_scorer_parent_compatibility():
    policy = base_policy()
    scorer = SimilarityScorer(policy)
    compatible_a = make_concept("c1", "Computer Science", parents=["root"])
    compatible_b = make_concept("c2", "Comp Sci", parents=["root"])
    decision = scorer.score_pair(compatible_a, compatible_b)
    assert decision.passed

    incompatible_a = make_concept("c3", "Computer Science", parents=["root-a"])
    incompatible_b = make_concept("c4", "Computer Science", parents=["root-b"])
    assert not scorer.parent_compatible(incompatible_a, incompatible_b)


def test_deduplication_processor_merges_similar_concepts():
    policy = base_policy(min_similarity_threshold=0.7)
    processor = DeduplicationProcessor(policy)

    winner = make_concept("c1", "Computer Science", institutions=5, aliases=["CS"])
    loser = make_concept("c2", "Comp Sci", institutions=2, aliases=["CompSci"])
    distinct = make_concept("c3", "Mechanical Engineering", parents=["engineering"])

    result = processor.process([winner, loser, distinct])

    assert len(result.concepts) == 2
    assert len(result.merge_ops) == 1

    merged_winner = next(concept for concept in result.concepts if concept.id == "c1")
    assert "Comp Sci" in merged_winner.aliases
    assert merged_winner.support.institutions >= 7
    assert result.stats["graph"]["edges"] >= 1
    assert result.samples, "Expected sampled merges for audit trail"
