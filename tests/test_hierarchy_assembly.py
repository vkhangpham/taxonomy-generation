import pytest

from taxonomy.config.policies import HierarchyAssemblyPolicy
from taxonomy.entities.core import Concept
from taxonomy.pipeline.hierarchy_assembly import (
    GraphValidator,
    HierarchyAssembler,
    HierarchyGraph,
    InvariantChecker,
)


def make_concept(concept_id: str, level: int, parents=None) -> Concept:
    return Concept(
        id=concept_id,
        level=level,
        canonical_label=f"Concept {concept_id}",
        parents=list(parents or []),
    )


def test_graph_add_concepts_and_statistics():
    policy = HierarchyAssemblyPolicy()
    graph = HierarchyGraph(policy)
    graph.add_concept(make_concept("root", 0))
    graph.add_concept(make_concept("child", 1, ["root"]))

    stats = graph.statistics()
    assert stats["node_count"] == 2
    assert stats["edge_count"] == 1
    assert stats["level_counts"][0] == 1
    assert stats["level_counts"][1] == 1


def test_graph_unique_path_violation_raises():
    policy = HierarchyAssemblyPolicy()
    graph = HierarchyGraph(policy)
    graph.add_concept(make_concept("root", 0))
    graph.add_concept(make_concept("parent_a", 1, ["root"]))
    graph.add_concept(make_concept("parent_b", 1, ["root"]))

    with pytest.raises(ValueError):
        graph.add_concept(make_concept("child", 2, ["parent_a", "parent_b"]))


def test_assembler_quarantine_strategy_tracks_orphans():
    policy = HierarchyAssemblyPolicy(orphan_strategy="quarantine")
    assembler = HierarchyAssembler(policy)
    assembler.process_concepts([make_concept("dangling", 1, ["missing"])])

    assert list(assembler.graph.concepts()) == []
    assert assembler.orphans
    assert assembler.orphans[0]["strategy"] == "quarantine"


def test_assembler_attach_placeholder_creates_chain():
    policy = HierarchyAssemblyPolicy(orphan_strategy="attach_placeholder")
    assembler = HierarchyAssembler(policy)
    result = assembler.run([make_concept("topic", 2, ["missing"])])

    placeholder_level1 = f"{policy.placeholder_parent_prefix}level1"
    placeholder_level0 = f"{policy.placeholder_parent_prefix}level0"
    assert placeholder_level1 in result.placeholders
    assert placeholder_level0 in result.placeholders

    inserted = result.graph.get("topic")
    assert inserted is not None
    assert inserted.parents == [placeholder_level1]


def test_validator_detects_multi_parent_violation():
    policy = HierarchyAssemblyPolicy()
    assembler = HierarchyAssembler(policy)
    assembler.process_concepts(
        [
            make_concept("root", 0),
            make_concept("child", 1, ["root"]),
        ]
    )
    graph = assembler.graph
    graph._parents["child"].add("ghost")  # type: ignore[attr-defined]

    validator = GraphValidator(InvariantChecker(policy))
    report = validator.run(graph)

    assert not report.passed
    codes = {violation["code"] for violation in report.violations}
    assert "non-unique-path" in codes


def test_run_generates_manifest_structure():
    policy = HierarchyAssemblyPolicy()
    assembler = HierarchyAssembler(policy)
    result = assembler.run([make_concept("root", 0)])

    manifest = result.manifest
    assert "policy" in manifest
    assert "graph_stats" in manifest
    assert manifest["graph_stats"]["node_count"] == 1
