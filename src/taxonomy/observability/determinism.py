"""Deterministic helpers for observability infrastructure.

The observability layer must never introduce non-deterministic behaviour into the
pipeline. This module centralises utility functions that make it easy to produce
stable ordering, seeded random number generators, canonical serialisation, and
reproducibility checksums.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from hashlib import sha256
import json
import random
import re
from typing import Any, Callable, Iterable, Mapping, TypeVar

_T = TypeVar("_T")


_HEX_ADDRESS_RE = re.compile(r"0x[0-9A-Fa-f]+")


def _stable_value_key(value: Any) -> tuple[int, str]:
    """Return a deterministic sort key for *value*.

    Values already converted/frozen should be JSON serialisable, but we fall
    back to a sanitised ``repr`` when ``json.dumps`` raises ``TypeError``.
    """

    try:
        serialised = json.dumps(value, separators=(",", ":"), sort_keys=True)
    except TypeError:
        serialised = _HEX_ADDRESS_RE.sub("0x", repr(value))
        return (1, serialised)
    return (0, serialised)


def _convert(value: Any) -> Any:
    """Recursively convert *value* into JSON-serialisable primitives.

    - Dataclasses are converted into dictionaries before recursion.
    - Mappings become sorted lists of key/value tuples to guarantee order.
    - Iterables (except ``str`` and ``bytes``) become lists processed recursively.
    - Everything else is returned unchanged.

    The resulting structure is suitable for canonical JSON dumping.
    """

    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Mapping):
        return [
            (str(key), _convert(val))
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        ]
    if isinstance(value, (list, tuple)):
        return [_convert(item) for item in value]
    if isinstance(value, (set, frozenset)):
        converted_items = [_convert(item) for item in value]
        return stable_sorted(converted_items, key=_stable_value_key)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def canonical_json(payload: Any) -> str:
    """Serialise *payload* into a canonical JSON string."""

    converted = _convert(payload)
    return json.dumps(converted, separators=(",", ":"), sort_keys=False)


def stable_hash(payload: Any) -> str:
    """Return a hex digest for *payload* using canonical JSON serialisation."""

    return sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def stable_sorted(
    items: Iterable[_T], *, key: Callable[[_T], Any] | None = None, reverse: bool = False
) -> list[_T]:
    """Stable sorting helper that always materialises into a list."""

    return sorted(list(items), key=key, reverse=reverse)


def build_rng(seed: int, namespace: str | None = None) -> random.Random:
    """Create a deterministic ``random.Random`` instance.

    When *namespace* is provided the seed is combined with a stable hash so that
    consumers can request isolated random generators that still yield
    deterministic sequences across runs.
    """

    if namespace is None:
        effective_seed = seed
    else:
        namespace_digest = sha256(f"{namespace}:{seed}".encode("utf-8")).digest()
        effective_seed = int.from_bytes(namespace_digest[:8], "big", signed=False)
    rng = random.Random()
    rng.seed(effective_seed)
    return rng


def freeze(payload: Any) -> Any:
    """Return an immutable representation of *payload* suitable for hashing."""

    if is_dataclass(payload):
        payload = asdict(payload)
    if isinstance(payload, Mapping):
        return tuple(
            (key, freeze(value))
            for key, value in sorted(payload.items(), key=lambda item: str(item[0]))
        )
    if isinstance(payload, (list, tuple)):
        return tuple(freeze(item) for item in payload)
    if isinstance(payload, (set, frozenset)):
        frozen_items = [freeze(item) for item in payload]
        sorted_items = stable_sorted(frozen_items, key=_stable_value_key)
        return tuple(sorted_items)
    return payload
