"""Unit tests for taxonomy.entities.core."""

from __future__ import annotations

import pytest

from taxonomy.entities import (
    Candidate,
    Concept,
    MergeOp,
    SourceRecord,
    SupportStats,
    ValidationFinding,
)
from taxonomy.entities.core import FindingMode, Provenance, SplitOp


def _concept() -> Concept:
    return Concept(
        id="c:test",
        level=1,
        canonical_label="Test Concept",
        parents=["c:parent"],
    )


def _provenance() -> Provenance:
    return Provenance(
        institution="Example University",
        url="https://example.edu/catalog",
        section="departments",
    )


def test_source_record_creation() -> None:
    record = SourceRecord(text="College of Engineering", provenance=_provenance())
    assert record.text == "College of Engineering"
    assert record.meta.language == "en"


def test_source_record_rejects_empty_text() -> None:
    with pytest.raises(ValueError):
        SourceRecord(text="   ", provenance=_provenance())


def test_candidate_parent_rules() -> None:
    candidate = Candidate(
        level=1,
        label="School of Design",
        normalized="school of design",
        parents=["inst:1"],
        aliases=["Design School"],
        support=SupportStats(records=5, institutions=3, count=7),
    )
    assert candidate.level == 1
    with pytest.raises(ValueError):
        Candidate(
            level=1,
            label="School of Design",
            normalized="school of design",
            parents=[],
        )
    with pytest.raises(ValueError):
        Candidate(
            level=0,
            label="College",
            normalized="college",
            parents=["parent"],
        )


def test_concept_hierarchy_validation() -> None:
    parent = Concept(
        id="c:1",
        level=0,
        canonical_label="Engineering",
        parents=[],
    )
    child = Concept(
        id="c:2",
        level=1,
        canonical_label="Mechanical Engineering",
        parents=["c:1"],
    )
    child.validate_hierarchy(parent_concepts=[parent])
    with pytest.raises(ValueError):
        parent.validate_hierarchy(parent_concepts=[child])


def test_validation_finding_requires_detail() -> None:
    finding = ValidationFinding(
        concept_id="c:1",
        mode=FindingMode.RULE,
        passed=True,
        detail="threshold met",
    )
    assert finding.mode is FindingMode.RULE
    with pytest.raises(ValueError):
        ValidationFinding(concept_id="c:1", mode=FindingMode.LLM, passed=False, detail="   ")


def test_merge_op_validation() -> None:
    op = MergeOp(winners=["c:1"], losers=["c:2"], rule="duplicate", evidence={"score": "0.95"})
    assert op.operation_id
    with pytest.raises(ValueError):
        MergeOp(winners=["c:1"], losers=["c:1"], rule="duplicate")


def test_split_op_validation() -> None:
    op = SplitOp(source_id="c:1", new_ids=["c:2", "c:3"], rule="specialization")
    assert len(op.new_ids) == 2
    with pytest.raises(ValueError):
        SplitOp(source_id="c:1", new_ids=["c:1"], rule="specialization")
    with pytest.raises(ValueError):
        SplitOp(source_id="c:1", new_ids=["c:2", "c:2"], rule="specialization")


def test_concept_validation_passed_aggregates_gates() -> None:
    concept = _concept()

    concept.set_validation_passed(True, gate="rule")
    assert concept.rationale.passed_gates == {"rule": True}
    assert concept.validation_passed is True

    concept.set_validation_passed(True, gate="web")
    assert concept.validation_passed is True
    assert concept.rationale.passed_gates == {"rule": True, "web": True}

    concept.set_validation_passed(False, gate="llm")
    assert concept.validation_passed is False
    assert concept.rationale.passed_gates["llm"] is False


def test_concept_validation_passed_clears_gates() -> None:
    concept = _concept()

    concept.set_validation_passed(True, gate="rule")
    concept.set_validation_passed(False, gate="web")
    assert concept.validation_passed is False

    concept.set_validation_passed(None, gate="rule")
    assert concept.validation_passed is False

    concept.set_validation_passed(None, gate="web")
    assert concept.rationale.passed_gates == {}
    assert concept.validation_passed is None


def test_concept_validation_passed_rejects_non_bool_inputs() -> None:
    concept = _concept()

    numpy = pytest.importorskip("numpy")

    with pytest.raises(ValueError):
        concept.set_validation_passed(numpy.bool_(True), gate="rule")
    with pytest.raises(ValueError):
        concept.set_validation_passed(1, gate="rule")
