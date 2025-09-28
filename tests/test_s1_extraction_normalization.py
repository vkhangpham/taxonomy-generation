from collections import Counter
from typing import List

import pytest

from taxonomy.config.policies import LabelPolicy, MinimalCanonicalForm
from taxonomy.entities.core import Candidate, Provenance, SourceMeta, SourceRecord, SupportStats
from taxonomy.pipeline.s1_extraction_normalization.extractor import ExtractionProcessor
from taxonomy.pipeline.s1_extraction_normalization.normalizer import CandidateNormalizer
from taxonomy.pipeline.s1_extraction_normalization.parent_index import ParentIndex
from taxonomy.pipeline.s1_extraction_normalization.processor import S1Processor


@pytest.fixture()
def label_policy() -> LabelPolicy:
    return LabelPolicy(minimal_canonical_form=MinimalCanonicalForm())


@pytest.fixture()
def sample_records() -> List[SourceRecord]:
    prov = Provenance(institution="Example University", url="https://example.edu/departments")
    meta = SourceMeta(hints={"level": "1"})
    record1 = SourceRecord(text="Department of Computer Science (CS)", provenance=prov, meta=meta)
    record2 = SourceRecord(text="Department of Computer Science", provenance=prov, meta=meta)
    return [record1, record2]


def test_extraction_processor_uses_runner(sample_records: List[SourceRecord]) -> None:
    calls = Counter()

    def runner(prompt_key, variables):
        calls[prompt_key] += 1
        return [
            {
                "label": "Department of Computer Science",
                "normalized": "computer science",
                "aliases": ["CS"],
                "parents": ["College of Engineering"],
            }
        ]

    extractor = ExtractionProcessor(runner=runner)
    raw = extractor.extract_candidates(sample_records, level=1)
    assert len(raw) == 2
    assert extractor.metrics.records_in == 2
    assert extractor.metrics.candidates_out == 2
    assert calls["taxonomy.extract"] == 2


def test_parent_index_resolves_aliases(label_policy: LabelPolicy) -> None:
    parent = Candidate(
        level=0,
        label="College of Engineering",
        normalized="college of engineering",
        parents=[],
        aliases=["College of Engineering", "College of Eng"],
        support=SupportStats(records=1, institutions=1, count=1),
    )
    index = ParentIndex(label_policy=label_policy)
    index.build_index([parent])
    assert index.resolve_anchor("College of Engineering", 1) == ["L0:college of engineering"]
    assert index.resolve_anchor("College of Eng", 1) == ["L0:college of engineering"]


def test_s1_processor_end_to_end(sample_records: List[SourceRecord], label_policy: LabelPolicy) -> None:
    parents = [
        Candidate(
            level=0,
            label="College of Engineering",
            normalized="college of engineering",
            parents=[],
            aliases=["College of Engineering"],
            support=SupportStats(records=1, institutions=1, count=1),
        )
    ]

    def runner(prompt_key, variables):
        return [
            {
                "label": variables["source_text"],
                "normalized": "computer science",
                "aliases": ["CS"],
                "parents": ["College of Engineering"],
            }
        ]

    extractor = ExtractionProcessor(runner=runner)
    normalizer = CandidateNormalizer(label_policy=label_policy)
    index = ParentIndex(label_policy=label_policy)
    processor = S1Processor(extractor=extractor, normalizer=normalizer, parent_index=index)

    final_candidates = processor.process_level(sample_records, level=1, previous_candidates=parents)
    assert len(final_candidates) == 1
    candidate = final_candidates[0]
    assert candidate.normalized == "computer science"
    assert candidate.parents == ["L0:college of engineering"]
    assert candidate.support.records == 2
    assert candidate.support.institutions == 1
    assert "CS" in candidate.aliases


def test_candidate_allows_empty_parents_above_level_zero() -> None:
    support = SupportStats(records=1, institutions=1, count=1)
    candidate = Candidate(
        level=1,
        label="Computer Science",
        normalized="computer science",
        parents=[],
        aliases=[],
        support=support,
    )
    assert candidate.parents == []
