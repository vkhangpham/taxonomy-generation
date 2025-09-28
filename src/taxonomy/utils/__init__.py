"""Utility helpers shared across taxonomy modules."""

from .acronym import abbrev_score, detect_acronym, is_acronym_expansion
from .helpers import (
    chunked,
    ensure_directory,
    normalize_label,
    normalize_whitespace,
    serialize_json,
    stable_shuffle,
)
from .logging import configure_logging, get_logger
from .normalization import (
    AliasBundle,
    detect_acronyms,
    expand_acronym,
    generate_aliases,
    normalize_by_level,
    remove_boilerplate,
    to_canonical_form,
)
from .phonetic import (
    bucket_by_phonetic,
    double_metaphone,
    generate_phonetic_key,
    normalize_for_phonetic,
    phonetic_bucket_keys,
)
from .similarity import (
    compute_similarity,
    find_duplicates,
    jaccard_similarity,
    jaro_winkler_similarity,
    minhash_similarity,
    preprocess_for_similarity,
    token_jaccard_similarity,
)

__all__ = [
    "configure_logging",
    "get_logger",
    "normalize_label",
    "normalize_whitespace",
    "ensure_directory",
    "serialize_json",
    "stable_shuffle",
    "chunked",
    "AliasBundle",
    "remove_boilerplate",
    "detect_acronyms",
    "expand_acronym",
    "generate_aliases",
    "normalize_by_level",
    "to_canonical_form",
    "preprocess_for_similarity",
    "jaccard_similarity",
    "token_jaccard_similarity",
    "jaro_winkler_similarity",
    "minhash_similarity",
    "compute_similarity",
    "find_duplicates",
    "detect_acronym",
    "is_acronym_expansion",
    "abbrev_score",
    "normalize_for_phonetic",
    "double_metaphone",
    "generate_phonetic_key",
    "phonetic_bucket_keys",
    "bucket_by_phonetic",
]
