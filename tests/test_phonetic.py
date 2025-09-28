from taxonomy.utils.phonetic import (
    bucket_by_phonetic,
    double_metaphone,
    generate_phonetic_key,
    normalize_for_phonetic,
    phonetic_bucket_keys,
)


def test_normalize_for_phonetic_strips_punctuation():
    assert normalize_for_phonetic("Computer-Science!") == "computer science"


def test_double_metaphone_consistency():
    code1 = double_metaphone("Computer Science")
    code2 = double_metaphone("computer science")
    assert code1 == code2
    assert len(code1) >= 1


def test_generate_phonetic_key_not_none():
    key = generate_phonetic_key("Artificial Intelligence")
    assert key is not None
    assert isinstance(key, str)


def test_bucket_by_phonetic_groups_similar_terms():
    items = ["Data Science", "Deta Sciense", "Machine Learning"]
    buckets = bucket_by_phonetic(items)
    # Expect the two spelling variants to share a bucket
    shared = [key for key, values in buckets.items() if "Data Science" in values]
    assert shared
    key = shared[0]
    assert "Deta Sciense" in buckets[key]


def test_phonetic_bucket_keys_returns_all_codes():
    codes = phonetic_bucket_keys("Information Systems")
    assert isinstance(codes, tuple)
    assert all(isinstance(code, str) for code in codes)
