"""Utilities for detecting and scoring acronym relationships."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, Optional

from .logging import get_logger
from .similarity import preprocess_for_similarity


_LOGGER = get_logger(module=__name__)
_ACRONYM_RE = re.compile(r"^[A-Z]{2,}(?:[&/][A-Z]{2,})?$")
_ALPHANUMERIC_RE = re.compile(r"[A-Za-z0-9]")
_COMMON_ACRONYMS = {
    "AI": "artificial intelligence",
    "ML": "machine learning",
    "NLP": "natural language processing",
    "CV": "computer vision",
    "HCI": "human computer interaction",
    "EE": "electrical engineering",
    "EECS": "electrical engineering and computer science",
    "CS": "computer science",
    "DS": "data science",
    "IS": "information systems",
    "SE": "software engineering",
    "STAT": "statistics",
}


def _normalize_acronym(text: str) -> str:
    return re.sub(r"[^A-Za-z]", "", text).upper()


def _first_letters(tokens: Iterable[str]) -> str:
    letters = [token[0] for token in tokens if token]
    return "".join(letters).upper()


@lru_cache(maxsize=1024)
def detect_acronym(text: str) -> Optional[str]:
    """Return the normalized acronym form if the text represents an acronym."""

    if not text:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    normalized = _normalize_acronym(stripped)
    if len(normalized) < 2:
        return None
    letters_only = re.sub(r"[^A-Za-z]", "", stripped)
    if len(letters_only) < 2:
        return None
    uppercase_letters = sum(1 for ch in letters_only if ch.isupper())
    if uppercase_letters < 2:
        return None
    uppercase_ratio = uppercase_letters / len(letters_only)
    if uppercase_ratio < 0.8 and stripped.upper() != stripped:
        return None
    if _ACRONYM_RE.match(normalized):
        _LOGGER.debug("Detected acronym", text=text, normalized=normalized)
        return normalized
    if normalized in _COMMON_ACRONYMS:
        _LOGGER.debug("Detected known acronym", text=text, normalized=normalized)
        return normalized
    return None


@lru_cache(maxsize=2048)
def is_acronym_expansion(acronym: str, expansion: str) -> bool:
    """Check if *expansion* matches the supplied *acronym*."""

    normalized_acronym = detect_acronym(acronym)
    if not normalized_acronym:
        return False

    normalized_expansion = preprocess_for_similarity(expansion)
    if not normalized_expansion:
        return False

    tokens = tuple(token for token in normalized_expansion.split() if token)
    if not tokens:
        return False
    first_letters = _first_letters(tokens)
    if first_letters == normalized_acronym:
        return True

    # Allow special-case overrides for known acronyms with historical nuances.
    expected = _COMMON_ACRONYMS.get(normalized_acronym)
    if expected and expected == normalized_expansion:
        return True

    return False


def _score_pair(text1: str, text2: str) -> float:
    if is_acronym_expansion(text1, text2):
        return 1.0
    return 0.0


def abbrev_score(text1: str, text2: str) -> float:
    """Return 1.0 for acronym/expansion matches, else 0.0."""

    if not text1 or not text2:
        return 0.0
    score_forward = _score_pair(text1, text2)
    if score_forward == 1.0:
        _LOGGER.debug("Acronym match", acronym=text1, expansion=text2)
        return 1.0
    score_reverse = _score_pair(text2, text1)
    if score_reverse == 1.0:
        _LOGGER.debug("Acronym match", acronym=text2, expansion=text1)
        return 1.0
    return 0.0


__all__ = ["detect_acronym", "is_acronym_expansion", "abbrev_score"]
