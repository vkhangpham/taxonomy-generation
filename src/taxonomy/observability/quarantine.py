"""Failure isolation helpers for taxonomy observability."""
from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Dict, Iterable, Mapping

from .determinism import stable_sorted


@dataclass(frozen=True)
class QuarantinedItem:
    """Details about a quarantined artefact."""

    phase: str
    reason: str
    item_id: str | None
    payload: Mapping[str, Any]
    sequence: int


@dataclass(frozen=True)
class QuarantineSnapshot:
    """Immutable snapshot summarising quarantine state."""

    total: int
    by_reason: Mapping[str, int]
    items: tuple[QuarantinedItem, ...]


class QuarantineManager:
    """Centralised quarantine tracker.

    The manager maintains deterministic ordering of quarantine entries by using a
    monotonically increasing sequence number protected by a reentrant lock. This
    allows the pipeline to continue processing while failures are isolated for
    audit.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._items: list[QuarantinedItem] = []
        self._reason_counts: Dict[str, int] = {}
        self._sequence = 0

    def quarantine(
        self,
        *,
        phase: str,
        reason: str,
        item_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> QuarantinedItem:
        """Record a new quarantined item and return the captured entry."""

        if not reason:
            raise ValueError("reason must be provided for quarantine entries")
        with self._lock:
            self._sequence += 1
            entry = QuarantinedItem(
                phase=phase,
                reason=reason,
                item_id=item_id,
                payload=dict(payload or {}),
                sequence=self._sequence,
            )
            self._items.append(entry)
            self._reason_counts[reason] = self._reason_counts.get(reason, 0) + 1
            return entry

    def iter_items(self) -> Iterable[QuarantinedItem]:
        with self._lock:
            return tuple(self._items)

    def counts(self) -> Mapping[str, int]:
        with self._lock:
            return dict(self._reason_counts)

    def snapshot(self) -> QuarantineSnapshot:
        with self._lock:
            items = tuple(self._items)
            summary = {reason: self._reason_counts[reason] for reason in stable_sorted(self._reason_counts)}
            return QuarantineSnapshot(total=len(items), by_reason=summary, items=items)

    def reset(self) -> None:
        with self._lock:
            self._items.clear()
            self._reason_counts.clear()
            self._sequence = 0

    def __len__(self) -> int:  # pragma: no cover - convenience
        with self._lock:
            return len(self._items)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        with self._lock:
            total = len(self._items)
            reasons = dict(self._reason_counts)
        return f"QuarantineManager(total={total}, reasons={reasons})"
