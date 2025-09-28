"""Text similarity helpers for intra-page deduplication and concept merging."""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import Callable, Dict, Iterable, List, Sequence, Tuple

import jellyfish

from .helpers import normalize_whitespace
from .logging import get_logger, verbose_text_logging_enabled


_NON_WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_LOGGER = get_logger(module=__name__)


def _ordered_pair(text1: str, text2: str) -> Tuple[str, str]:
    """Return a deterministic ordering of two strings for cache keys."""

    return (text1, text2) if text1 <= text2 else (text2, text1)


@lru_cache(maxsize=2048)
def preprocess_for_similarity(text: str) -> str:
    """Normalize text for similarity calculations."""

    if not text:
        return ""
    normalized = normalize_whitespace(text)
    lowered = normalized.lower()
    stripped = _NON_WORD_RE.sub(" ", lowered)
    collapsed = " ".join(stripped.split())
    if verbose_text_logging_enabled():
        _LOGGER.debug(
            "Preprocessed text for similarity",
            original=text[:120],
            processed=collapsed[:120],
        )
    else:
        _LOGGER.debug(
            "Preprocessed text for similarity",
            original_length=len(text),
            processed_length=len(collapsed),
        )
    return collapsed


@lru_cache(maxsize=2048)
def _tokenize(text: str) -> Tuple[str, ...]:
    """Tokenize preprocessed text and cache the result."""

    normalized = preprocess_for_similarity(text)
    if not normalized:
        return tuple()
    tokens = tuple(normalized.split())
    _LOGGER.debug("Tokenized text", token_count=len(tokens))
    return tokens


def _generate_shingles(text: str, n: int) -> List[str]:
    if n <= 0:
        raise ValueError("n must be positive for shingling")
    tokens = text.split()
    if not tokens:
        return []
    if len(tokens) <= n:
        return [" ".join(tokens)]
    return [" ".join(tokens[idx : idx + n]) for idx in range(len(tokens) - n + 1)]


def _ensure_shingles(text1: str, text2: str, n: int) -> Tuple[List[str], List[str]]:
    normalized_1 = preprocess_for_similarity(text1)
    normalized_2 = preprocess_for_similarity(text2)
    return _generate_shingles(normalized_1, n), _generate_shingles(normalized_2, n)


def jaccard_similarity(text1: str, text2: str, *, n: int = 3) -> float:
    """Compute the shingled Jaccard similarity coefficient between two strings."""

    shingles_a, shingles_b = _ensure_shingles(text1, text2, n)
    if not shingles_a and not shingles_b:
        return 1.0
    if not shingles_a or not shingles_b:
        return 0.0
    set_a = set(shingles_a)
    set_b = set(shingles_b)
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    if union == 0:
        return 0.0
    score = intersection / union
    _LOGGER.debug(
        "Computed Jaccard similarity",
        score=score,
        intersection=intersection,
        union=union,
        shingles=len(shingles_a) + len(shingles_b),
    )
    return score


def token_jaccard_similarity(text1: str, text2: str) -> float:
    """Compute Jaccard similarity over token sets with preprocessing."""

    tokens_a = set(_tokenize(text1))
    tokens_b = set(_tokenize(text2))
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    if union == 0:
        return 0.0
    score = intersection / union
    _LOGGER.debug(
        "Computed token Jaccard similarity",
        score=score,
        intersection=intersection,
        union=union,
        token_count=len(tokens_a) + len(tokens_b),
    )
    return score


@lru_cache(maxsize=4096)
def _jaro_winkler_cached(text1: str, text2: str) -> float:
    ordered_a, ordered_b = _ordered_pair(text1, text2)
    return jellyfish.jaro_winkler_similarity(ordered_a, ordered_b)


def jaro_winkler_similarity(text1: str, text2: str, *, prefix_weight: float = 0.1) -> float:
    """Compute the Jaro-Winkler similarity between two strings."""

    normalized_1 = preprocess_for_similarity(text1)
    normalized_2 = preprocess_for_similarity(text2)
    if not normalized_1 and not normalized_2:
        return 1.0
    if not normalized_1 or not normalized_2:
        return 0.0
    score = _jaro_winkler_cached(normalized_1, normalized_2)
    _LOGGER.debug(
        "Computed Jaro-Winkler similarity",
        score=score,
        prefix_weight=prefix_weight,
    )
    return score


def _hash_shingle(shingle: str, seed: int) -> int:
    digest = hashlib.blake2b(f"{seed}|{shingle}".encode("utf-8"), digest_size=8)
    return int.from_bytes(digest.digest(), "big")


def _minhash_signature(shingles: Iterable[str], num_hashes: int) -> List[int]:
    max_hash = 2**64 - 1
    signature: List[int] = [max_hash] * num_hashes
    for shingle in shingles:
        for idx in range(num_hashes):
            hashed = _hash_shingle(shingle, idx)
            if hashed < signature[idx]:
                signature[idx] = hashed
    return signature


def minhash_similarity(text1: str, text2: str, *, num_hashes: int = 128, n: int = 3) -> float:
    """Approximate Jaccard similarity using MinHash signatures."""

    shingles_a, shingles_b = _ensure_shingles(text1, text2, n)
    if not shingles_a and not shingles_b:
        return 1.0
    if not shingles_a or not shingles_b:
        return 0.0
    signature_a = _minhash_signature(shingles_a, num_hashes)
    signature_b = _minhash_signature(shingles_b, num_hashes)
    matches = sum(1 for a, b in zip(signature_a, signature_b) if a == b)
    score = matches / num_hashes
    _LOGGER.debug(
        "Computed MinHash similarity",
        score=score,
        matches=matches,
        num_hashes=num_hashes,
    )
    return score


def _combined_similarity(
    text1: str,
    text2: str,
    *,
    jaro_weight: float = 1.0,
    jaccard_weight: float = 1.0,
    abbrev_weight: float = 1.0,
    prefix_weight: float = 0.1,
    aggregator: str = "max",
    abbrev_func: Callable[[str, str], float] | None = None,
    abbrev_score: float | None = None,
) -> Tuple[float, Dict[str, float]]:
    """Compute a weighted combination of similarity measures."""

    jw = jaro_winkler_similarity(text1, text2, prefix_weight=prefix_weight)
    jaccard = token_jaccard_similarity(text1, text2)
    abbrev = (
        abbrev_func(text1, text2)
        if abbrev_func is not None
        else (abbrev_score if abbrev_score is not None else 0.0)
    )

    weighted_scores = {
        "jaro_winkler": jw * jaro_weight,
        "token_jaccard": jaccard * jaccard_weight,
        "abbrev_score": abbrev * abbrev_weight,
    }

    if aggregator == "max":
        combined = max(weighted_scores.values())
    elif aggregator == "sum":
        combined = sum(weighted_scores.values())
    else:
        raise ValueError(f"Unsupported aggregator: {aggregator}")

    return combined, {
        "jaro_winkler": jw,
        "token_jaccard": jaccard,
        "abbrev_score": abbrev,
    }


def compute_similarity(
    text1: str,
    text2: str,
    *,
    method: str = "jaccard_shingles",
    **kwargs: object,
) -> float | Tuple[float, Dict[str, float]]:
    """Dispatch similarity computation based on the configured method."""

    method_normalized = method.lower()
    if method_normalized == "jaccard_shingles":
        return jaccard_similarity(text1, text2, **{"n": kwargs.get("n", 3)})
    if method_normalized == "token_jaccard":
        return token_jaccard_similarity(text1, text2)
    if method_normalized == "minhash":
        return minhash_similarity(
            text1,
            text2,
            num_hashes=int(kwargs.get("num_hashes", 128)),
            n=int(kwargs.get("n", 3)),
        )
    if method_normalized == "jaro_winkler":
        return jaro_winkler_similarity(
            text1,
            text2,
            prefix_weight=float(kwargs.get("prefix_weight", 0.1)),
        )
    if method_normalized == "combined":
        combined, components = _combined_similarity(
            text1,
            text2,
            jaro_weight=float(kwargs.get("jaro_weight", 1.0)),
            jaccard_weight=float(kwargs.get("jaccard_weight", 1.0)),
            abbrev_weight=float(kwargs.get("abbrev_weight", 1.0)),
            prefix_weight=float(kwargs.get("prefix_weight", 0.1)),
            aggregator=str(kwargs.get("aggregator", "max")),
            abbrev_func=kwargs.get("abbrev_func"),
            abbrev_score=kwargs.get("abbrev_score"),
        )
        if kwargs.get("return_components"):
            return combined, components
        return combined
    raise ValueError(f"Unsupported similarity method: {method}")


def find_duplicates(
    text_blocks: Sequence[str],
    *,
    threshold: float = 0.95,
    method: str = "jaccard_shingles",
    **kwargs: object,
) -> List[int]:
    """Identify duplicate block indices to discard based on similarity threshold."""

    if not text_blocks:
        return []
    if threshold < 0.0 or threshold > 1.0:
        raise ValueError("threshold must be within [0, 1]")

    duplicate_indices: List[int] = []
    kept_indices: List[int] = []

    for idx, candidate in enumerate(text_blocks):
        candidate_clean = candidate or ""
        is_duplicate = False
        for kept_idx in kept_indices:
            reference = text_blocks[kept_idx]
            score = compute_similarity(candidate_clean, reference or "", method=method, **kwargs)
            _LOGGER.debug(
                "Evaluated block similarity",
                candidate_index=idx,
                reference_index=kept_idx,
                score=score,
                method=method,
            )
            if math.isclose(score, 1.0) or score >= threshold:
                duplicate_indices.append(idx)
                is_duplicate = True
                break
        if not is_duplicate:
            kept_indices.append(idx)

    return duplicate_indices


__all__ = [
    "preprocess_for_similarity",
    "jaccard_similarity",
    "token_jaccard_similarity",
    "jaro_winkler_similarity",
    "minhash_similarity",
    "compute_similarity",
    "find_duplicates",
]
