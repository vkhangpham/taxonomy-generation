"""Text similarity helpers for intra-page deduplication."""

from __future__ import annotations

import hashlib
import math
import re
from functools import lru_cache
from typing import Iterable, List, Sequence, Tuple

from loguru import logger

from .helpers import normalize_whitespace


_NON_WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)


@lru_cache(maxsize=2048)
def preprocess_for_similarity(text: str) -> str:
    """Normalize text for similarity calculations."""

    if not text:
        return ""
    normalized = normalize_whitespace(text)
    lowered = normalized.lower()
    stripped = _NON_WORD_RE.sub(" ", lowered)
    collapsed = " ".join(stripped.split())
    logger.debug("Preprocessed text for similarity", original=text[:200], processed=collapsed[:200])
    return collapsed


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
    """Compute the Jaccard similarity coefficient between two strings."""

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
    logger.debug(
        "Computed Jaccard similarity",
        score=score,
        intersection=intersection,
        union=union,
        shingles=len(shingles_a) + len(shingles_b),
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
    logger.debug(
        "Computed MinHash similarity",
        score=score,
        matches=matches,
        num_hashes=num_hashes,
    )
    return score


def compute_similarity(text1: str, text2: str, *, method: str = "jaccard_shingles", **kwargs: object) -> float:
    """Dispatch similarity computation based on the configured method."""

    method_normalized = method.lower()
    if method_normalized == "jaccard_shingles":
        return jaccard_similarity(text1, text2, **{"n": kwargs.get("n", 3)})
    if method_normalized == "minhash":
        return minhash_similarity(
            text1,
            text2,
            num_hashes=int(kwargs.get("num_hashes", 128)),
            n=int(kwargs.get("n", 3)),
        )
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
            logger.debug(
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
    "minhash_similarity",
    "compute_similarity",
    "find_duplicates",
]

