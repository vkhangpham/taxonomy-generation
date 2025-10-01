from collections import Counter
from types import SimpleNamespace
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


def test_extract_candidates_respects_audit_limit(monkeypatch) -> None:
    from taxonomy.pipeline.s1_extraction_normalization import main as s1_main

    records = list(range(20))

    monkeypatch.setattr(s1_main, "load_source_records", lambda _: iter(records))

    captured: dict[str, int] = {}
    original_limit = s1_main._limit_source_records

    def tracking_limit(iterable, *, limit: int):
        captured["limit"] = limit
        return original_limit(iterable, limit=limit)

    monkeypatch.setattr(s1_main, "_limit_source_records", tracking_limit)

    class DummyExtractor:
        def __init__(self, observability=None):
            self.observability = observability
            self.metrics = SimpleNamespace(
                records_in=0,
                candidates_out=0,
                invalid_json=0,
                quarantined=0,
                provider_errors=0,
                retries=0,
            )

        def extract_candidates(self, batch, *, level: int, observability=None):
            return []

    class DummyNormalizer:
        def __init__(self, label_policy):
            pass

        def normalize(self, raw, *, level: int):
            return raw

    class DummyParentIndex:
        def __init__(self, **kwargs):
            pass

        def build_index(self, parents):
            return None

    class DummyProcessor:
        def __init__(self, extractor, normalizer, parent_index):
            pass

        def _aggregate(self, normalized):
            return normalized

        def _materialize(self, values):
            return []

    monkeypatch.setattr(s1_main, "ExtractionProcessor", DummyExtractor)
    monkeypatch.setattr(s1_main, "CandidateNormalizer", DummyNormalizer)
    monkeypatch.setattr(s1_main, "ParentIndex", DummyParentIndex)
    monkeypatch.setattr(s1_main, "S1Processor", DummyProcessor)
    monkeypatch.setattr(s1_main, "_merge_aggregated_state", lambda target, items: None)

    result = s1_main.extract_candidates(
        "dummy",
        level=0,
        audit_mode=True,
        audit_limit=5,
    )

    assert captured["limit"] == 5
    assert result == []
