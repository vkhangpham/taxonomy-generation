"""Observability context coordination."""
from __future__ import annotations

import collections
import logging
import time
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, is_dataclass
from threading import RLock
import typing as t

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
    """Composite snapshot used when exporting observability data."""

    counters: t.Mapping[str, t.Mapping[str, t.Any]]
    quarantine: t.Mapping[str, t.Any]
    evidence: t.Mapping[str, t.Any]
    operations: tuple[OperationLogEntry, ...]
    performance: t.Mapping[str, t.Any]
    prompt_versions: t.Mapping[str, str]
    thresholds: t.Mapping[str, t.Any]
    seeds: t.Mapping[str, int]
    checksum: str
    snapshot_timestamp: float
    captured_at: str


def _sanitize(obj: t.Any) -> t.Any:
    """Return a JSON-serialisable representation of ``obj`` with stable ordering."""

    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (bytes, bytearray)):
        return obj.decode("utf-8", errors="replace")
    if is_dataclass(obj):
        return _sanitize(asdict(obj))
    if isinstance(obj, Mapping):
        items = sorted(((str(key), _sanitize(value)) for key, value in obj.items()), key=lambda item: item[0])
        return {key: value for key, value in items}
    if isinstance(obj, (set, frozenset)):
        return [_sanitize(item) for item in sorted(obj, key=lambda value: repr(value))]
    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        return [_sanitize(item) for item in obj]
    if hasattr(obj, "__dict__"):
        return _sanitize(vars(obj))
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
        max_operation_entries = getattr(policy, "max_operation_log_entries", 5000) or 5000
        try:
            max_operation_entries = int(max_operation_entries)
        except (TypeError, ValueError):
            max_operation_entries = 5000
        self._operations: collections.deque[OperationLogEntry] = collections.deque(
            maxlen=max(1, max_operation_entries)
        )
        self._operation_sequence = 0
        self._performance: dict[str, dict[str, t.Any]] = {}
        self._prompt_versions: dict[str, str] = {}
        self._thresholds: dict[str, t.Any] = {}
        self._seeds: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Phase context helpers
    # ------------------------------------------------------------------
    @contextmanager
    def phase(self, name: str) -> t.Iterator["PhaseHandle"]:
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
        if not getattr(self.policy, "counter_registry_enabled", True):
            return
        self.registry.increment(counter, value, phase=phase, label=label)

    def set_counter(
        self,
        counter: str,
        value: int,
        *,
        phase: str | None = None,
    ) -> None:
        if not getattr(self.policy, "counter_registry_enabled", True):
            return
        self.registry.set(counter, value, phase=phase)

    def bulk_update(
        self,
        values: t.Mapping[str, int],
        *,
        phase: str | None = None,
    ) -> None:
        if not getattr(self.policy, "counter_registry_enabled", True):
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
        if getattr(self.policy, "quarantine_logging_enabled", True):
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
        if getattr(self.policy, "audit_trail_generation", True):
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
        with self._lock:
            self._operation_sequence += 1
            sanitized_payload = _sanitize(payload or {})
            if not isinstance(sanitized_payload, dict):
                sanitized_payload = {"value": sanitized_payload}
            entry = OperationLogEntry(
                sequence=self._operation_sequence,
                phase=phase,
                operation=operation,
                outcome=outcome,
                payload=sanitized_payload,
            )
            self._operations.append(entry)
            return entry

    def record_performance(
        self,
        *,
        phase: str,
        metrics: t.Mapping[str, t.Any],
    ) -> None:
        if not getattr(self.policy, "performance_tracking_enabled", True):
            return
        with self._lock:
            self._performance[phase] = dict(metrics)

    def register_prompt_version(self, prompt: str, version: str) -> None:
        with self._lock:
            self._prompt_versions[prompt] = version

    def register_threshold(self, name: str, value: t.Any) -> None:
        with self._lock:
            self._thresholds[name] = value

    def register_seed(self, name: str, value: int) -> None:
        with self._lock:
            self._seeds[name] = int(value)

    # ------------------------------------------------------------------
    # Export helpers
    # ------------------------------------------------------------------
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

        counters_raw = self.registry.as_dict()["counters"]
        quarantine_snapshot = self.quarantine.snapshot()
        evidence_raw = self.evidence.as_dict()

        max_quarantine_items = getattr(self.policy, "max_quarantine_items", None)
        try:
            if max_quarantine_items is not None:
                max_quarantine_items = max(1, int(max_quarantine_items))
        except (TypeError, ValueError):
            max_quarantine_items = None

        items = quarantine_snapshot.items
        if max_quarantine_items:
            items = items[-max_quarantine_items:]

        with self._lock:
            operations = tuple(self._operations)
            performance_raw = {
                phase: dict(metrics)
                for phase, metrics in sorted(self._performance.items())
            }
            prompt_versions_raw = dict(sorted(self._prompt_versions.items()))
            thresholds_raw = dict(sorted(self._thresholds.items()))
            seeds_raw: dict[str, int] = {}
            for name, value in sorted(self._seeds.items()):
                try:
                    seeds_raw[name] = int(value)
                except (TypeError, ValueError):
                    _LOGGER.warning("Skipping invalid observability seed '%s'", name)

        sanitized_counters = _sanitize(counters_raw)
        sanitized_quarantine = {
            "total": quarantine_snapshot.total,
            "by_reason": _sanitize(quarantine_snapshot.by_reason),
            "items": [
                {
                    "phase": item.phase,
                    "reason": item.reason,
                    "item_id": item.item_id,
                    "payload": _sanitize(item.payload),
                    "sequence": item.sequence,
                }
                for item in items
            ],
        }
        sanitized_evidence = _sanitize(evidence_raw)
        sanitized_operations = [
            {
                "sequence": entry.sequence,
                "phase": entry.phase,
                "operation": entry.operation,
                "outcome": entry.outcome,
                "payload": _sanitize(entry.payload),
            }
            for entry in operations
        ]
        sanitized_performance = _sanitize(performance_raw)
        sanitized_prompt_versions = _sanitize(prompt_versions_raw)
        sanitized_thresholds = _sanitize(thresholds_raw)
        sanitized_seeds = _sanitize(seeds_raw)

        payload = {
            "counters": sanitized_counters,
            "quarantine": sanitized_quarantine,
            "evidence": sanitized_evidence,
            "operations": sanitized_operations,
            "performance": sanitized_performance,
            "prompt_versions": sanitized_prompt_versions,
            "thresholds": sanitized_thresholds,
            "seeds": sanitized_seeds,
        }
        checksum = stable_hash(payload)
        timestamp_ns = time.time_ns()
        snapshot_timestamp = timestamp_ns / 1_000_000_000
        captured_at = _format_utc_timestamp(timestamp_ns)
        return ObservabilitySnapshot(
            counters=sanitized_counters,
            quarantine=sanitized_quarantine,
            evidence=sanitized_evidence,
            operations=operations,
            performance=sanitized_performance,
            prompt_versions=sanitized_prompt_versions,
            thresholds=sanitized_thresholds,
            seeds=sanitized_seeds,
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
            "operations": [
                {
                    "sequence": entry.sequence,
                    "phase": entry.phase,
                    "operation": entry.operation,
                    "outcome": entry.outcome,
                    "payload": _sanitize(entry.payload),
                }
                for entry in snap.operations
            ],
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
        """Log an operation outcome for this phase with a JSON-safe payload."""

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
