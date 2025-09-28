"""General-purpose helpers for deterministic taxonomy processing."""

from __future__ import annotations

import json
import random
import re
import unicodedata
from pathlib import Path
import itertools
from typing import Iterable, Iterator, List, Sequence, TypeVar

from .logging import get_logger, verbose_text_logging_enabled

T = TypeVar("T")
_WORD_BOUNDARY_PATTERN = re.compile(r"\s+")
_PUNCTUATION_PATTERN = re.compile(r"[\u2018\u2019\u201C\u201D\-\u2010\u2011\u2012\u2013\u2014\u2015\.,;:/\\]+")

_LOGGER = get_logger(module=__name__)


def normalize_whitespace(text: str) -> str:
    """Collapse repeated whitespace into single spaces."""

    collapsed = _WORD_BOUNDARY_PATTERN.sub(" ", text.strip())
    if verbose_text_logging_enabled():
        _LOGGER.debug(
            "Normalized whitespace",
            original=text[:120],
            normalized=collapsed[:120],
        )
    else:
        _LOGGER.debug(
            "Normalized whitespace",
            original_length=len(text),
            normalized_length=len(collapsed),
        )
    return collapsed


def fold_diacritics(text: str) -> str:
    """Remove diacritics by decomposing unicode characters."""

    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_label(label: str) -> str:
    """Apply canonical label rules: lowercase, whitespace collapse, punctuation removal."""

    lowered = fold_diacritics(label).lower()
    stripped = _PUNCTUATION_PATTERN.sub(" ", lowered)
    return normalize_whitespace(stripped)


def ensure_directory(path: Path | str) -> Path:
    """Ensure that a directory exists and return the resolved Path."""

    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target.resolve()


def serialize_json(data: object, destination: Path | str, *, indent: int = 2) -> Path:
    """Serialize data to JSON with deterministic ordering."""

    dest_path = Path(destination)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(
        json.dumps(data, indent=indent, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    _LOGGER.debug("Serialized JSON", path=str(dest_path), size=dest_path.stat().st_size)
    return dest_path


def stable_shuffle(items: Sequence[T], seed: int) -> List[T]:
    """Return a deterministically shuffled copy of the input sequence."""

    result = list(items)
    random.Random(seed).shuffle(result)
    return result


def chunked(iterable: Iterable[T], size: int) -> Iterable[List[T]]:
    """Yield chunks of a given size from the input iterable."""

    if size <= 0:
        raise ValueError("size must be positive")

    iterator: Iterator[T] = iter(iterable)
    while True:
        batch = list(itertools.islice(iterator, size))
        if not batch:
            break
        yield batch


__all__ = [
    "normalize_whitespace",
    "fold_diacritics",
    "normalize_label",
    "ensure_directory",
    "serialize_json",
    "stable_shuffle",
    "chunked",
]
