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

# Cache sizes balance reuse against memory (roughly a few MiB per cache at these limits).
_PREPROCESS_CACHE_SIZE = 2048  # Normalized text cache keeps short strings hot without unbounded growth.
_TOKENIZE_CACHE_SIZE = 2048  # Token tuples stay cached while keeping memory within a few MiB.
_JW_CACHE_SIZE = 4096  # Pairwise Jaro-Winkler scores; larger key space but still under tens of MiB.
_DEFAULT_PREFIX_WEIGHT = 0.1
_MAX_PREFIX_LENGTH = 4
_PREFIX_WEIGHT_CAP = 0.25

try:
    jellyfish.jaro_winkler_similarity(
        "prefix",
        "prefix",
        prefix_weight=_DEFAULT_PREFIX_WEIGHT,
    )
except TypeError:
    _JARO_WINKLER_SUPPORTS_PREFIX = False
    _LOGGER.debug(
        "prefix_weight unsupported by jellyfish; using manual Winkler boost fallback",
    )
except Exception as exc:  # pragma: no cover - defensive
    _JARO_WINKLER_SUPPORTS_PREFIX = False
    _LOGGER.debug(
        "prefix_weight support check failed; assuming unsupported",
        error=str(exc),
    )
else:
    _JARO_WINKLER_SUPPORTS_PREFIX = True
    _LOGGER.debug(
        "prefix_weight supported by jellyfish.jaro_winkler_similarity",
    )

def _ordered_pair(text1: str, text2: str) -> Tuple[str, str]:
    """Return a deterministic ordering of two strings for cache keys."""

    return (text1, text2) if text1 <= text2 else (text2, text1)


@lru_cache(maxsize=_PREPROCESS_CACHE_SIZE)
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


@lru_cache(maxsize=_TOKENIZE_CACHE_SIZE)
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


@lru_cache(maxsize=_JW_CACHE_SIZE)
def _jaro_similarity_base_cached(text1: str, text2: str) -> float:
    """Return the base Jaro similarity for a pair of strings."""

    return jellyfish.jaro_similarity(text1, text2)


def _winkler_from_components(
    base_score: float, prefix_length: int, prefix_weight: float
) -> Tuple[float, float]:
    """Apply the Winkler prefix boost and return the boosted score and bounded weight."""

    bounded_prefix_weight = max(0.0, min(_PREFIX_WEIGHT_CAP, prefix_weight))
    boosted = base_score + prefix_length * bounded_prefix_weight * (1.0 - base_score)
    if boosted > 1.0:
        boosted = 1.0
    return boosted, bounded_prefix_weight


def _matched_prefix_length(text1: str, text2: str) -> int:
    """Return the matching prefix length capped at _MAX_PREFIX_LENGTH.

    The cap is a heuristic that bounds how much prefix overlap influences
    similarity calculations.
    """

    prefix = 0
    for ch1, ch2 in zip(text1, text2):
        if ch1 != ch2 or prefix >= _MAX_PREFIX_LENGTH:
            break
        prefix += 1
    return prefix


@lru_cache(maxsize=_JW_CACHE_SIZE)
def _jaro_winkler_cached(text1: str, text2: str, prefix_weight: float) -> float:
    """Return a cached Jaro-Winkler score with fallback when prefix_weight is unavailable.

    Cache keys pair the normalized string order with the effective prefix weight so
    repeat computations reuse the stored result. When jellyfish lacks native support
    for prefix_weight we reconstruct the Winkler boost while delegating the base Jaro
    distance to jellyfish for performance.
    """

    base_score = _jaro_similarity_base_cached(text1, text2)
    prefix = _matched_prefix_length(text1, text2)

    if _JARO_WINKLER_SUPPORTS_PREFIX:
        return jellyfish.jaro_winkler_similarity(text1, text2, prefix_weight=prefix_weight)

    # Jellyfish 1.2+ exposes `long_tolerance` but not `prefix_weight`. When callers
    # request the default scaling we can rely on the built-in implementation.
    if math.isclose(prefix_weight, _DEFAULT_PREFIX_WEIGHT, rel_tol=1e-9, abs_tol=0.0):
        return jellyfish.jaro_winkler_similarity(text1, text2)

    # Reconstruct Winkler boosting using the requested prefix weight while
    # delegating the base Jaro distance to jellyfish for performance.
    boosted, bounded_weight = _winkler_from_components(
        base_score, prefix, prefix_weight
    )
    _LOGGER.debug(
        "Applied manual Winkler boost for cached prefix weight",
        prefix_weight=prefix_weight,
        bounded_prefix_weight=bounded_weight,
        prefix_length=prefix,
        base_score=base_score,
        boosted_score=boosted,
    )
    return boosted


def jaro_winkler_similarity(
    text1: str, text2: str, *, prefix_weight: float = _DEFAULT_PREFIX_WEIGHT
) -> float:
    """Compute the Jaro-Winkler similarity between two strings."""

    normalized_1 = preprocess_for_similarity(text1)
    normalized_2 = preprocess_for_similarity(text2)
    if not normalized_1 and not normalized_2:
        return 1.0
    if not normalized_1 or not normalized_2:
        return 0.0

    ordered_1, ordered_2 = _ordered_pair(normalized_1, normalized_2)

    requested_prefix_weight = float(prefix_weight)
    bounded_prefix_weight = max(0.0, min(_PREFIX_WEIGHT_CAP, requested_prefix_weight))
    cache_prefix_weight = round(bounded_prefix_weight, 4)  # Stabilize cache keys.

    cached_score = _jaro_winkler_cached(ordered_1, ordered_2, cache_prefix_weight)
    if cache_prefix_weight == bounded_prefix_weight:
        score = cached_score
    else:
        base_score = _jaro_similarity_base_cached(ordered_1, ordered_2)
        prefix_length = _matched_prefix_length(ordered_1, ordered_2)
        score, bounded_weight = _winkler_from_components(
            base_score, prefix_length, bounded_prefix_weight
        )
        _LOGGER.debug(
            "Applied manual Winkler boost with exact prefix weight",
            prefix_weight=bounded_weight,
            prefix_length=prefix_length,
            base_score=base_score,
            boosted_score=score,
        )

    _LOGGER.debug(
        "Computed Jaro-Winkler similarity",
        score=score,
        requested_prefix_weight=requested_prefix_weight,
        bounded_prefix_weight=bounded_prefix_weight,
        cache_prefix_weight=cache_prefix_weight,
    )
    return score


def _hash_shingle(shingle: str, seed: int) -> int:
    digest = hashlib.blake2b(f"{seed}|{shingle}".encode("utf-8"), digest_size=8)
    return int.from_bytes(digest.digest(), "big")


def _minhash_signature(shingles: Iterable[str], num_hashes: int) -> List[int]:
    """Generate a MinHash signature by tracking the minimum hash for each seed.

    Each shingle is hashed with deterministic seeds and the signature keeps the
    lowest value per seed so the result approximates Jaccard similarity in later
    comparisons.
    """

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

    def combined_handler() -> float | Tuple[float, Dict[str, float]]:
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

    method_handlers: Dict[str, Callable[[], float | Tuple[float, Dict[str, float]]]] = {
        "jaccard_shingles": lambda: jaccard_similarity(
            text1,
            text2,
            n=int(kwargs.get("n", 3)),
        ),
        "token_jaccard": lambda: token_jaccard_similarity(text1, text2),
        "minhash": lambda: minhash_similarity(
            text1,
            text2,
            num_hashes=int(kwargs.get("num_hashes", 128)),
            n=int(kwargs.get("n", 3)),
        ),
        "jaro_winkler": lambda: jaro_winkler_similarity(
            text1,
            text2,
            prefix_weight=float(kwargs.get("prefix_weight", 0.1)),
        ),
        "combined": combined_handler,
    }

    try:
        handler = method_handlers[method_normalized]
    except KeyError:
        raise ValueError(f"Unsupported similarity method: {method}") from None
    return handler()


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
