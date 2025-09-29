"""Observability context coordination."""
from __future__ import annotations

import collections
import logging
import time
from collections.abc import Mapping as CollectionsMapping, Sequence
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass, is_dataclass
from threading import RLock
import typing as t
from typing import ContextManager

from .determinism import stable_hash
from .evidence import EvidenceSampler
from .quarantine import QuarantineManager
from .registry import CounterRegistry

if t.TYPE_CHECKING:  # pragma: no cover - typing only
    from taxonomy.config.policies import ObservabilityPolicy


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class OperationLogEntry:
    """Deterministic record of an operation executed during a phase."""

    sequence: int
    phase: str
    operation: str
    outcome: str
    payload: t.Mapping[str, t.Any]


@dataclass(frozen=True)
class ObservabilitySnapshot:
    """Composite snapshot used when exporting observability data.

    The ``checksum`` is computed from the fully sanitised payload emitted via
    :meth:`ObservabilityContext.snapshot`, ensuring downstream systems can
    detect drift when any sanitised content changes. ``snapshot_timestamp``
    captures the monotonic seconds since the Unix epoch when the snapshot was
    assembled, while ``captured_at`` provides the same moment formatted as a
    UTC ISO-8601 string for human readability. Together these timestamps make
    it clear exactly when the underlying state was captured.
    """

    counters: t.Mapping[str, t.Mapping[str, t.Any]]
    quarantine: t.Mapping[str, t.Any]
    evidence: t.Mapping[str, t.Any]
    operations: tuple[dict[str, t.Any], ...]
    performance: t.Mapping[str, t.Any]
    prompt_versions: t.Mapping[str, str]
    thresholds: t.Mapping[str, t.Any]
    seeds: t.Mapping[str, int]
    checksum: str
    snapshot_timestamp: float
    captured_at: str


_SANITIZE_DEFAULT_MAX_DEPTH = 8
_SANITIZE_DEFAULT_MAX_ITEMS = 512
_SANITIZE_DEPTH_SENTINEL = "__max_depth_exceeded__"


def _sanitize(
    obj: t.Any,
    *,
    max_depth: int = _SANITIZE_DEFAULT_MAX_DEPTH,
    max_items: int = _SANITIZE_DEFAULT_MAX_ITEMS,
    _depth: int = 0,
) -> t.Any:
    """Return a JSON-serialisable representation of ``obj`` with stable ordering.

    The helper keeps recursion depth and collection sizes bounded so that
    extremely large or deeply nested payloads cannot exhaust resources.
    """

    if max_depth is not None and _depth >= max_depth:
        return _SANITIZE_DEPTH_SENTINEL

    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    if is_dataclass(obj):
        return _sanitize(asdict(obj), max_depth=max_depth, max_items=max_items, _depth=_depth + 1)
    if isinstance(obj, CollectionsMapping):
        sorted_items = sorted(((str(key), value) for key, value in obj.items()), key=lambda item: item[0])
        if max_items is not None:
            sorted_items = sorted_items[:max_items]
        return {
            key: _sanitize(value, max_depth=max_depth, max_items=max_items, _depth=_depth + 1)
            for key, value in sorted_items
        }
    if isinstance(obj, (set, frozenset)):
        sanitised_items = [
            _sanitize(item, max_depth=max_depth, max_items=max_items, _depth=_depth + 1)
            for item in obj
        ]
        sanitised_items.sort(key=lambda value: repr(value))
        if max_items is not None:
            sanitised_items = sanitised_items[:max_items]
        return sanitised_items
    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        seq = list(obj)
        if max_items is not None:
            seq = seq[:max_items]
        return [
            _sanitize(item, max_depth=max_depth, max_items=max_items, _depth=_depth + 1)
            for item in seq
        ]
    if hasattr(obj, "__dict__"):
        return _sanitize(vars(obj), max_depth=max_depth, max_items=max_items, _depth=_depth + 1)
    return repr(obj)


def _format_utc_timestamp(nanoseconds: int) -> str:
    """Return an ISO-8601 UTC timestamp with microsecond precision."""

    seconds, remainder = divmod(nanoseconds, 1_000_000_000)
    microseconds = remainder // 1_000
    base = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(seconds))
    return f"{base}.{microseconds:06d}Z"


class ObservabilityContext:
    """Coordinates counters, evidence, and quarantine state for a run."""

    def __init__(
        self,
        *,
        run_id: str,
        policy: "ObservabilityPolicy" | None = None,
    ) -> None:
        self.run_id = run_id
        self.policy = policy
        self._counter_registry_enabled = bool(getattr(policy, "counter_registry_enabled", True))
        self._quarantine_logging_enabled = bool(getattr(policy, "quarantine_logging_enabled", True))
        self._audit_trail_generation = bool(getattr(policy, "audit_trail_generation", True))
        self._performance_tracking_enabled = bool(getattr(policy, "performance_tracking_enabled", True))
        seed = getattr(policy, "deterministic_sampling_seed", 42)
        rate = getattr(policy, "evidence_sampling_rate", 0.1)
        limit = getattr(policy, "max_evidence_samples_per_phase", 100)
        self.registry = CounterRegistry(run_id=run_id)
        self.quarantine = QuarantineManager()
        self.evidence = EvidenceSampler(
            sampling_rate=rate,
            max_samples_per_phase=limit,
            seed=seed,
        )
        self._lock = RLock()
        max_operation_entries_raw = getattr(policy, "max_operation_log_entries", None)
        if max_operation_entries_raw is None:
            max_operation_entries = 5000
        else:
            try:
                max_operation_entries = int(max_operation_entries_raw)
            except (TypeError, ValueError):
                max_operation_entries = 5000
        if max_operation_entries < 0:
            max_operation_entries = 0
        self._max_operation_entries = max_operation_entries
        self._operations: collections.deque[dict[str, t.Any]] | None
        if max_operation_entries == 0:
            self._operations = None
        else:
            self._operations = collections.deque(maxlen=max_operation_entries)
        self._operation_sequence = 0
        self._performance: dict[str, dict[str, t.Any]] = {}
        self._prompt_versions: dict[str, str] = {}
        self._thresholds: dict[str, t.Any] = {}
        self._seeds: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Phase context helpers
    # ------------------------------------------------------------------
    @contextmanager
    def phase(self, name: str) -> ContextManager["PhaseHandle"]:
        """Context manager that automatically pushes and pops the phase stack."""

        handle = PhaseHandle(self, name)
        self.registry.push_phase(name)
        try:
            yield handle
        finally:
            self.registry.pop_phase(name)

    # ------------------------------------------------------------------
    # Public APIs used by pipeline modules
    # ------------------------------------------------------------------
    def increment(
        self,
        counter: str,
        value: int = 1,
        *,
        phase: str | None = None,
        label: str | None = None,
    ) -> None:
        if not self._counter_registry_enabled:
            return
        self.registry.increment(counter, value, phase=phase, label=label)

    def set_counter(
        self,
        counter: str,
        value: int,
        *,
        phase: str | None = None,
    ) -> None:
        if not self._counter_registry_enabled:
            return
        self.registry.set(counter, value, phase=phase)

    def bulk_update(
        self,
        values: t.Mapping[str, int],
        *,
        phase: str | None = None,
    ) -> None:
        if not self._counter_registry_enabled:
            return
        self.registry.bulk_update(values, phase=phase)

    def quarantine_item(
        self,
        *,
        phase: str,
        reason: str,
        item_id: str | None = None,
        payload: t.Mapping[str, t.Any] | None = None,
    ) -> None:
        if self._quarantine_logging_enabled:
            self.quarantine.quarantine(
                phase=phase,
                reason=reason,
                item_id=item_id,
                payload=payload,
            )

    def sample_evidence(
        self,
        *,
        phase: str,
        category: str,
        outcome: str,
        payload: t.Mapping[str, t.Any],
        weight: float = 1.0,
    ) -> None:
        if self._audit_trail_generation:
            self.evidence.consider(
                phase=phase,
                category=category,
                outcome=outcome,
                payload=payload,
                weight=weight,
            )

    def record_operation(
        self,
        *,
        phase: str,
        operation: str,
        outcome: str = "success",
        payload: t.Mapping[str, t.Any] | None = None,
    ) -> OperationLogEntry:
        """Record an operation outcome and return a deterministic log entry.

        The internal sequence counter always increments, even when
        ``max_operation_log_entries`` is configured to ``0``. In that case the
        returned :class:`OperationLogEntry` enables downstream components to
        retain API parity while no entries are retained in memory.
        """

        with self._lock:
            self._operation_sequence += 1
            sanitized_payload = _sanitize(payload or {})
            if not isinstance(sanitized_payload, dict):
                sanitized_payload = {"value": sanitized_payload}
            entry_payload = {
                "sequence": self._operation_sequence,
                "phase": phase,
                "operation": operation,
                "outcome": outcome,
                "payload": sanitized_payload,
            }
            if self._operations is not None:
                self._operations.append(entry_payload)
            return OperationLogEntry(**entry_payload)

    def record_performance(
        self,
        *,
        phase: str,
        metrics: t.Mapping[str, t.Any],
    ) -> None:
        """Store performance metrics for a phase after sanitising the payload.

        All values are normalised via :func:`_sanitize` so downstream consumers
        receive JSON-serialisable structures regardless of the input mapping.
        """

        if not self._performance_tracking_enabled:
            return
        with self._lock:
            sanitised_metrics = _sanitize(metrics)
            if not isinstance(sanitised_metrics, dict):
                sanitised_metrics = {"value": sanitised_metrics}
            self._performance[phase] = sanitised_metrics

    def register_prompt_version(self, prompt: str, version: str) -> None:
        with self._lock:
            self._prompt_versions[prompt] = deepcopy(version)

    def register_threshold(self, name: str, value: t.Any) -> None:
        with self._lock:
            self._thresholds[name] = deepcopy(value)

    def register_seed(self, name: str, value: int) -> None:
        with self._lock:
            copied_value = deepcopy(value)
            self._seeds[name] = int(copied_value)

    # ------------------------------------------------------------------
    # Export helpers
    # ------------------------------------------------------------------
    def _resolve_max_quarantine_items(self) -> int | None:
        raw_value = getattr(self.policy, "max_quarantine_items", None)
        if raw_value is None:
            return None
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return None
        return value if value >= 0 else None

    def _snapshot_counters(self) -> dict[str, t.Any]:
        counters_raw = self.registry.as_dict().get("counters", {})
        sanitised = _sanitize(counters_raw)
        return sanitised if isinstance(sanitised, dict) else {}

    def _snapshot_quarantine(self) -> dict[str, t.Any]:
        snapshot = self.quarantine.snapshot()
        limit = self._resolve_max_quarantine_items()
        items = list(snapshot.items)
        if limit is None:
            limited_items = items
        elif limit == 0:
            limited_items = []
        else:
            limited_items = items[-limit:]
        return {
            "total": snapshot.total,
            "by_reason": _sanitize(snapshot.by_reason),
            "items": [
                {
                    "phase": item.phase,
                    "reason": item.reason,
                    "item_id": item.item_id,
                    "payload": _sanitize(item.payload),
                    "sequence": item.sequence,
                }
                for item in limited_items
            ],
        }

    def _snapshot_evidence(self) -> dict[str, t.Any]:
        evidence_raw = self.evidence.as_dict()
        sanitised = _sanitize(evidence_raw)
        return sanitised if isinstance(sanitised, dict) else {}

    def _snapshot_operations(self) -> list[dict[str, t.Any]]:
        with self._lock:
            if not self._operations:
                return []
            entries = [deepcopy(entry) for entry in self._operations]
        return [
            _sanitize(entry) if isinstance(entry, dict) else _sanitize(dict(entry))
            for entry in entries
        ]

    def _snapshot_performance(self) -> dict[str, t.Any]:
        with self._lock:
            items = sorted(self._performance.items())
            return {phase: deepcopy(metrics) for phase, metrics in items}

    def _snapshot_prompt_versions(self) -> dict[str, t.Any]:
        with self._lock:
            items = sorted(self._prompt_versions.items())
            return {prompt: deepcopy(version) for prompt, version in items}

    def _snapshot_thresholds(self) -> dict[str, t.Any]:
        with self._lock:
            items = sorted(self._thresholds.items())
            return {name: _sanitize(value) for name, value in items}

    def _snapshot_seeds(self) -> dict[str, int]:
        with self._lock:
            seeds: dict[str, int] = {}
            for name, value in sorted(self._seeds.items()):
                try:
                    seeds[name] = int(value)
                except (TypeError, ValueError):
                    _LOGGER.warning(
                        "Skipping invalid observability seed '%s' with value %r", name, value
                    )
            return seeds

    def _snapshot_metadata(self, payload: dict[str, t.Any]) -> tuple[str, float, str]:
        checksum = stable_hash(payload)
        timestamp_ns = time.time_ns()
        snapshot_timestamp = timestamp_ns / 1_000_000_000
        captured_at = _format_utc_timestamp(timestamp_ns)
        return checksum, snapshot_timestamp, captured_at

    def snapshot(self) -> ObservabilitySnapshot:
        """Return a best-effort snapshot plus capture metadata.

        The snapshot spans multiple subsystems without a single global lock, so
        the returned data may be slightly stale. Consumers can inspect the
        ``snapshot_timestamp`` (seconds since the Unix epoch) or the
        human-readable ``captured_at`` field to understand when the data was
        assembled. When a ``policy.max_quarantine_items`` limit is provided,
        only the most recent quarantine entries up to that limit are included to
        keep payloads bounded.
        """

        counters = self._snapshot_counters()
        quarantine = self._snapshot_quarantine()
        evidence = self._snapshot_evidence()
        operations = tuple(self._snapshot_operations())
        performance = self._snapshot_performance()
        prompt_versions = self._snapshot_prompt_versions()
        thresholds = self._snapshot_thresholds()
        seeds = self._snapshot_seeds()

        payload = {
            "counters": counters,
            "quarantine": quarantine,
            "evidence": evidence,
            "operations": list(operations),
            "performance": performance,
            "prompt_versions": prompt_versions,
            "thresholds": thresholds,
            "seeds": seeds,
        }
        checksum, snapshot_timestamp, captured_at = self._snapshot_metadata(payload)
        return ObservabilitySnapshot(
            counters=counters,
            quarantine=quarantine,
            evidence=evidence,
            operations=operations,
            performance=performance,
            prompt_versions=prompt_versions,
            thresholds=thresholds,
            seeds=seeds,
            checksum=checksum,
            snapshot_timestamp=snapshot_timestamp,
            captured_at=captured_at,
        )

    def export(self) -> dict[str, t.Any]:
        """Serialise the current snapshot into a JSON-friendly mapping."""

        snap = self.snapshot()
        return {
            "counters": snap.counters,
            "quarantine": snap.quarantine,
            "evidence": snap.evidence,
            "operations": list(snap.operations),
            "performance": snap.performance,
            "prompt_versions": snap.prompt_versions,
            "thresholds": snap.thresholds,
            "seeds": snap.seeds,
            "checksum": snap.checksum,
            "snapshot_timestamp": snap.snapshot_timestamp,
            "captured_at": snap.captured_at,
        }


class PhaseHandle:
    """Helper exposed when entering a phase context."""

    def __init__(self, context: ObservabilityContext, phase: str) -> None:
        self._context = context
        self.phase = phase

    def increment(self, counter: str, value: int = 1, *, label: str | None = None) -> None:
        """Increment a counter registered against this phase."""

        self._context.increment(counter, value, phase=self.phase, label=label)

    def set_counter(self, counter: str, value: int) -> None:
        """Set an absolute counter value for this phase."""

        self._context.set_counter(counter, value, phase=self.phase)

    def bulk_update(self, values: t.Mapping[str, int]) -> None:
        """Apply multiple counter updates to the current phase."""

        self._context.bulk_update(values, phase=self.phase)

    def quarantine(
        self,
        *,
        reason: str,
        item_id: str | None = None,
        payload: t.Mapping[str, t.Any] | None = None,
    ) -> None:
        """Quarantine an item for this phase; payload should be JSON-serialisable."""

        self._context.quarantine_item(
            phase=self.phase,
            reason=reason,
            item_id=item_id,
            payload=payload,
        )

    def evidence(
        self,
        *,
        category: str,
        outcome: str,
        payload: t.Mapping[str, t.Any],
        weight: float = 1.0,
    ) -> None:
        """Record sampled evidence for this phase; payload must be JSON-serialisable."""

        self._context.sample_evidence(
            phase=self.phase,
            category=category,
            outcome=outcome,
            payload=payload,
            weight=weight,
        )

    def log_operation(
        self,
        *,
        operation: str,
        outcome: str = "success",
        payload: t.Mapping[str, t.Any] | None = None,
    ) -> OperationLogEntry:
        """Log an operation outcome for this phase with a JSON-safe payload.

        When the context disables in-memory operation retention by setting
        ``max_operation_log_entries`` to ``0``, this still returns a populated
        :class:`OperationLogEntry` so callers can emit events that remain
        sequence-aware.
        """

        return self._context.record_operation(
            phase=self.phase,
            operation=operation,
            outcome=outcome,
            payload=payload,
        )

    def performance(self, metrics: t.Mapping[str, t.Any]) -> None:
        """Record performance metrics for this phase; metrics should be JSON-serialisable."""

        self._context.record_performance(phase=self.phase, metrics=metrics)

    # Deprecated alias for backwards compatibility.
    set = set_counter
