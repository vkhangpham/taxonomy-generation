"""Utility helpers shared across taxonomy modules."""

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
from .similarity import (
    compute_similarity,
    find_duplicates,
    jaccard_similarity,
    minhash_similarity,
    preprocess_for_similarity,
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
    "minhash_similarity",
    "compute_similarity",
    "find_duplicates",
]
