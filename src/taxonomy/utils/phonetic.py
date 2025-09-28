"""Phonetic encoding helpers for blocking strategies."""

from __future__ import annotations

import re
from collections import defaultdict
from functools import lru_cache
from typing import Dict, Iterable, List, Sequence, Tuple

import jellyfish

try:  # pragma: no cover - optional dependency
    from metaphone import doublemetaphone as _doublemetaphone  # type: ignore
except ImportError:  # pragma: no cover - fallback when metaphone is unavailable
    def _doublemetaphone(value: str) -> Tuple[str, str]:
        primary = jellyfish.metaphone(value)
        return primary, ""

from .logging import get_logger


_LOGGER = get_logger(module=__name__)
_NON_ALPHA_RE = re.compile(r"[^A-Za-z]+")


@lru_cache(maxsize=2048)
def normalize_for_phonetic(text: str) -> str:
    """Normalize text prior to phonetic encoding."""

    if not text:
        return ""
    lowered = text.lower().strip()
    cleaned = _NON_ALPHA_RE.sub(" ", lowered)
    normalized = " ".join(cleaned.split())
    _LOGGER.debug(
        "Normalized text for phonetic encoding",
        original=text[:120],
        normalized=normalized,
    )
    return normalized


@lru_cache(maxsize=4096)
def double_metaphone(text: str) -> Tuple[str, ...]:
    """Return the Double Metaphone codes for *text*."""

    normalized = normalize_for_phonetic(text)
    if not normalized:
        return tuple()
    primary, secondary = _doublemetaphone(normalized)
    codes = tuple(code for code in (primary, secondary) if code)
    _LOGGER.debug("Computed Double Metaphone", text=normalized, codes=codes)
    return codes


def generate_phonetic_key(text: str) -> str | None:
    """Return a stable phonetic key for blocking, preferring primary code."""

    codes = double_metaphone(text)
    if not codes:
        return None
    return codes[0]


def phonetic_bucket_keys(text: str) -> Tuple[str, ...]:
    """Return all candidate bucket keys for the supplied text."""

    codes = double_metaphone(text)
    if not codes:
        return tuple()
    return codes


def bucket_by_phonetic(values: Sequence[str]) -> Dict[str, List[str]]:
    """Group values by their phonetic key with deterministic ordering."""

    buckets: Dict[str, List[str]] = defaultdict(list)
    for value in values:
        key = generate_phonetic_key(value)
        if key is None:
            continue
        buckets[key].append(value)
    for key in list(buckets):
        buckets[key].sort()
    _LOGGER.debug("Created phonetic buckets", bucket_count=len(buckets))
    return dict(sorted(buckets.items()))


__all__ = [
    "normalize_for_phonetic",
    "double_metaphone",
    "generate_phonetic_key",
    "phonetic_bucket_keys",
    "bucket_by_phonetic",
]
