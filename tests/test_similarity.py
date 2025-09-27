"""Unit tests for text similarity utilities."""

from __future__ import annotations

import math

import pytest

from taxonomy.utils import (
    compute_similarity,
    find_duplicates,
    jaccard_similarity,
    minhash_similarity,
    preprocess_for_similarity,
)


def test_preprocess_for_similarity_normalizes_text() -> None:
    processed = preprocess_for_similarity("Hello, World!!  ")
    assert processed == "hello world"


def test_jaccard_similarity_identical_texts() -> None:
    assert jaccard_similarity("taxonomy", "taxonomy") == 1.0


def test_jaccard_similarity_distinct_texts() -> None:
    assert jaccard_similarity("taxonomy", "biology") == 0.0


def test_minhash_similarity_consistency() -> None:
    score = minhash_similarity("applied data science", "applied data science")
    assert math.isclose(score, 1.0)


def test_compute_similarity_dispatches_methods() -> None:
    jaccard = compute_similarity("machine learning", "machine learning", method="jaccard_shingles")
    minhash = compute_similarity(
        "machine learning",
        "machine learning",
        method="minhash",
        num_hashes=64,
    )
    assert math.isclose(jaccard, 1.0)
    assert math.isclose(minhash, 1.0)


def test_find_duplicates_identifies_near_duplicates() -> None:
    blocks = [
        "Department of Chemistry",
        "Department of Chemistry",
        "Department of Physics",
    ]
    duplicates = find_duplicates(blocks, threshold=0.95)
    assert duplicates == [1]


def test_find_duplicates_respects_threshold() -> None:
    blocks = [
        "Undergraduate Programs",
        "Undergraduate Program Overview",
    ]
    duplicates = find_duplicates(blocks, threshold=0.99)
    assert duplicates == []


def test_compute_similarity_invalid_method() -> None:
    with pytest.raises(ValueError):
        compute_similarity("a", "b", method="cosine")

