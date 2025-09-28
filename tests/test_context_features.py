import pytest

from taxonomy.entities.core import Concept, Provenance, SourceMeta, SourceRecord, SupportStats
from taxonomy.utils.context_features import (
    ContextWindow,
    analyze_institution_distribution,
    compute_context_divergence,
    compute_token_cooccurrence,
    extract_context_windows,
    extract_parent_lineage_key,
    summarize_contexts_for_llm,
)


def make_concept(**overrides):
    base = {
        "id": "c1",
        "level": 1,
        "canonical_label": "Machine Learning",
        "parents": ["p1"],
        "aliases": ["ML"],
        "support": SupportStats(records=4, institutions=3, count=10),
        "validation_metadata": {},
    }
    base.update(overrides)
    return Concept.model_validate(base)


def make_record(text: str, institution: str = "inst") -> SourceRecord:
    provenance = Provenance(institution=institution, url="https://example.com")
    return SourceRecord(text=text, provenance=provenance, meta=SourceMeta())


def test_extract_parent_lineage_key_root_concept():
    concept = make_concept(id="root", level=0, parents=[])
    assert extract_parent_lineage_key(concept) == "L0:<root>"


def test_extract_context_windows_captures_mentions():
    concept = make_concept()
    records = [
        make_record("Our department researches Machine Learning methods extensively."),
        make_record("The course explores Machine Learning applications in robotics."),
    ]
    contexts = extract_context_windows(concept, records, window_size=6)
    assert len(contexts) == 2
    assert all(concept.canonical_label.split()[0] in ctx.text for ctx in contexts)
    assert all(ctx.institution == "inst" for ctx in contexts)


def test_compute_token_cooccurrence_applies_frequency_threshold():
    contexts = [
        ContextWindow(
            concept_id="c1",
            text="advanced machine learning systems",
            institution="inst",
            parent_lineage="L1:p1",
            source_index=0,
        ),
        ContextWindow(
            concept_id="c1",
            text="machine learning pipelines",
            institution="inst",
            parent_lineage="L1:p1",
            source_index=1,
        ),
    ]
    cooccurrence = compute_token_cooccurrence(contexts, min_frequency=2)
    assert cooccurrence == {"machine": 2, "learning": 2}


def test_analyze_institution_distribution_merges_counts():
    concept_a = make_concept(
        id="a",
        validation_metadata={"institution_counts": {"InstA": 3, "InstB": 1}},
    )
    concept_b = make_concept(
        id="b",
        validation_metadata={"institutions": ["InstC", "InstC", "InstA"]},
    )
    distribution = analyze_institution_distribution([concept_a, concept_b])
    assert distribution["a"] == {"insta": 3, "instb": 1}
    assert distribution["b"] == {"insta": 1, "instc": 2}


def test_compute_context_divergence_considers_parents_and_tokens():
    ctx_a = [
        ContextWindow(
            concept_id="a",
            text="deep learning for vision",
            institution="inst1",
            parent_lineage="L1:p1",
            source_index=0,
        )
    ]
    ctx_b = [
        ContextWindow(
            concept_id="b",
            text="statistics for finance",
            institution="inst2",
            parent_lineage="L1:p2",
            source_index=0,
        )
    ]
    divergence = compute_context_divergence(ctx_a, ctx_b)
    assert divergence > 0.5


def test_summarize_contexts_for_llm_limits_duplicates():
    contexts = [
        ContextWindow(
            concept_id="c1",
            text="the lab studies reinforcement learning",
            institution="inst",
            parent_lineage="L1:p1",
            source_index=0,
        ),
        ContextWindow(
            concept_id="c1",
            text="the lab studies reinforcement learning",
            institution="inst",
            parent_lineage="L1:p1",
            source_index=1,
        ),
        ContextWindow(
            concept_id="c1",
            text="workshops include machine learning",
            institution="inst",
            parent_lineage="L1:p1",
            source_index=2,
        ),
    ]
    summaries = summarize_contexts_for_llm(contexts, max_contexts=2)
    assert len(summaries) == 2
    texts = {item["text"] for item in summaries}
    assert len(texts) == 2
