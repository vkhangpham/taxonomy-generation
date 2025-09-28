"""Centralised counter registry for taxonomy observability."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from threading import RLock
from typing import Any, Dict, Iterable, Mapping

from .determinism import stable_sorted

PHASE_COUNTERS: Mapping[str, tuple[str, ...]] = {
    "S0": (
        "pages_seen",
        "pages_failed",
        "blocks_total",
        "blocks_kept",
        "by_language",
    ),
    "S1": ("records_in", "candidates_out", "invalid_json", "retries"),
    "S2": (
        "candidates_in",
        "kept",
        "dropped_insufficient_support",
    ),
    "S3": (
        "checked",
        "passed_rule",
        "failed_rule",
        "passed_llm",
        "failed_llm",
    ),
    "Dedup": ("pairs_compared", "edges_kept", "components", "merges_applied"),
    "Disambig": ("collisions_detected", "splits_made", "deferred"),
    "Validation": (
        "checked",
        "rule_failed",
        "web_failed",
        "llm_failed",
        "passed_all",
    ),
    "Hierarchy": ("nodes_in", "nodes_kept", "orphans", "violations", "edges_built"),
}

# Counters that support labelled increments (e.g. language breakdowns).
_LABELLED_COUNTERS: Mapping[str, frozenset[str]] = {
    "S0": frozenset({"by_language"}),
}


@dataclass(frozen=True)
class CounterSnapshot:
    """Immutable snapshot of the registry state."""

    run_id: str | None
    counters: Mapping[str, Mapping[str, Any]]


class CounterRegistry:
    """Thread-safe registry for canonical pipeline counters."""

    def __init__(self, *, run_id: str | None = None) -> None:
        self._lock = RLock()
        self._run_id = run_id
        self._data: Dict[str, Dict[str, Any]] = {
            phase: {counter: 0 for counter in counters}
            for phase, counters in PHASE_COUNTERS.items()
        }
        # initialise labelled counters with dedicated counters
        for phase, labelled in _LABELLED_COUNTERS.items():
            for counter in labelled:
                self._data[phase][counter] = Counter()
        self._phase_stack: list[str] = []

    # ------------------------------------------------------------------
    # Phase context helpers
    # ------------------------------------------------------------------
    def push_phase(self, phase: str) -> None:
        """Record that *phase* is now active for implicit increments."""

        if phase not in PHASE_COUNTERS:
            raise KeyError(f"Unknown observability phase '{phase}'")
        with self._lock:
            self._phase_stack.append(phase)

    def pop_phase(self, phase: str) -> None:
        with self._lock:
            if not self._phase_stack or self._phase_stack[-1] != phase:
                raise RuntimeError("Phase stack out of sync during pop")
            self._phase_stack.pop()

    def current_phase(self) -> str | None:
        with self._lock:
            return self._phase_stack[-1] if self._phase_stack else None

    # ------------------------------------------------------------------
    # Counter manipulation
    # ------------------------------------------------------------------
    def increment(
        self,
        counter: str,
        value: int = 1,
        *,
        phase: str | None = None,
        label: str | None = None,
    ) -> None:
        """Increment *counter* within *phase* by *value*.

        When *label* is provided the counter must be configured to accept
        labelled values (e.g. ``by_language``). The operation is locked so the
        registry is safe to use across threads.
        """

        target_phase = phase or self.current_phase()
        if target_phase is None:
            raise RuntimeError("No active phase for counter increment")
        if target_phase not in PHASE_COUNTERS:
            raise KeyError(f"Unknown observability phase '{target_phase}'")
        if counter not in PHASE_COUNTERS[target_phase]:
            raise KeyError(
                f"Unknown counter '{counter}' for phase '{target_phase}'"
            )

        with self._lock:
            slot = self._data[target_phase][counter]
            if isinstance(slot, Counter):
                if label is None:
                    raise ValueError(
                        f"Counter '{counter}' requires a label but none was provided"
                    )
                slot[label] += value
            else:
                if label is not None:
                    raise ValueError(
                        f"Counter '{counter}' does not support labelled increments"
                    )
                self._data[target_phase][counter] = int(slot) + int(value)

    def set(
        self,
        counter: str,
        value: int,
        *,
        phase: str | None = None,
    ) -> None:
        """Set *counter* in *phase* to *value* (integer counters only)."""

        target_phase = phase or self.current_phase()
        if target_phase is None:
            raise RuntimeError("No active phase for counter assignment")
        if counter not in PHASE_COUNTERS[target_phase]:
            raise KeyError(
                f"Unknown counter '{counter}' for phase '{target_phase}'"
            )

        with self._lock:
            if isinstance(self._data[target_phase][counter], Counter):
                raise ValueError(
                    f"Counter '{counter}' in phase '{target_phase}' is label-based"
                )
            self._data[target_phase][counter] = int(value)

    def bulk_update(
        self,
        values: Mapping[str, int],
        *,
        phase: str | None = None,
    ) -> None:
        """Increment multiple counters for *phase* in a single locked operation."""

        target_phase = phase or self.current_phase()
        if target_phase is None:
            raise RuntimeError("No active phase for bulk update")
        invalid = set(values) - set(PHASE_COUNTERS[target_phase])
        if invalid:
            raise KeyError(
                f"Unknown counters for phase '{target_phase}': {sorted(invalid)}"
            )
        with self._lock:
            for name, delta in values.items():
                slot = self._data[target_phase][name]
                if isinstance(slot, Counter):
                    raise ValueError(
                        f"Counter '{name}' is label-based; use `increment` with a label"
                    )
                self._data[target_phase][name] = int(slot) + int(delta)

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------
    def snapshot(self) -> CounterSnapshot:
        """Return an immutable snapshot of the registry state."""

        with self._lock:
            frozen: Dict[str, Dict[str, Any]] = {}
            for phase in stable_sorted(self._data):
                counters = {}
                for name in PHASE_COUNTERS[phase]:
                    value = self._data[phase][name]
                    if isinstance(value, Counter):
                        counters[name] = {
                            label: value[label]
                            for label in stable_sorted(value)
                        }
                    else:
                        counters[name] = int(value)
                frozen[phase] = counters
        return CounterSnapshot(run_id=self._run_id, counters=frozen)

    def as_dict(self) -> Dict[str, Any]:
        """Convenience: return the snapshot as a plain dictionary."""

        snap = self.snapshot()
        return {
            "run_id": snap.run_id,
            "counters": {
                phase: dict(counters)
                for phase, counters in snap.counters.items()
            },
        }

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def reset(self) -> None:
        """Clear all counters back to their initial state."""

        with self._lock:
            for phase, counters in PHASE_COUNTERS.items():
                for counter in counters:
                    if isinstance(self._data[phase][counter], Counter):
                        self._data[phase][counter].clear()
                    else:
                        self._data[phase][counter] = 0

    def ensure_phase(self, phase: str) -> None:
        """Validate that *phase* is defined."""

        if phase not in PHASE_COUNTERS:
            raise KeyError(f"Unknown observability phase '{phase}'")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"CounterRegistry(run_id={self._run_id!r}, counters={self._data!r})"
