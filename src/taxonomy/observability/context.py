"""Observability context coordination."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from typing import Any, Dict, Iterator, Mapping, TYPE_CHECKING

from .determinism import stable_hash
from .evidence import EvidenceSampler
from .quarantine import QuarantineManager
from .registry import CounterRegistry

if TYPE_CHECKING:  # pragma: no cover - typing only
    from taxonomy.config.policies import ObservabilityPolicy


@dataclass(frozen=True)
class OperationLogEntry:
    """Deterministic record of an operation executed during a phase."""

    sequence: int
    phase: str
    operation: str
    outcome: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class ObservabilitySnapshot:
    """Composite snapshot used when exporting observability data."""

    counters: Mapping[str, Mapping[str, Any]]
    quarantine: Mapping[str, Any]
    evidence: Mapping[str, Any]
    operations: tuple[OperationLogEntry, ...]
    performance: Mapping[str, Any]
    prompt_versions: Mapping[str, str]
    thresholds: Mapping[str, Any]
    seeds: Mapping[str, int]
    checksum: str


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
        self._operations: list[OperationLogEntry] = []
        self._operation_sequence = 0
        self._performance: Dict[str, Dict[str, Any]] = {}
        self._prompt_versions: Dict[str, str] = {}
        self._thresholds: Dict[str, Any] = {}
        self._seeds: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Phase context helpers
    # ------------------------------------------------------------------
    @contextmanager
    def phase(self, name: str) -> Iterator["PhaseHandle"]:
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
        values: Mapping[str, int],
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
        payload: Mapping[str, Any] | None = None,
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
        payload: Mapping[str, Any],
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
        payload: Mapping[str, Any] | None = None,
    ) -> OperationLogEntry:
        with self._lock:
            self._operation_sequence += 1
            entry = OperationLogEntry(
                sequence=self._operation_sequence,
                phase=phase,
                operation=operation,
                outcome=outcome,
                payload=dict(payload or {}),
            )
            self._operations.append(entry)
            return entry

    def record_performance(
        self,
        *,
        phase: str,
        metrics: Mapping[str, Any],
    ) -> None:
        if not getattr(self.policy, "performance_tracking_enabled", True):
            return
        with self._lock:
            self._performance[phase] = dict(metrics)

    def register_prompt_version(self, prompt: str, version: str) -> None:
        with self._lock:
            self._prompt_versions[prompt] = version

    def register_threshold(self, name: str, value: Any) -> None:
        with self._lock:
            self._thresholds[name] = value

    def register_seed(self, name: str, value: int) -> None:
        with self._lock:
            self._seeds[name] = int(value)

    # ------------------------------------------------------------------
    # Export helpers
    # ------------------------------------------------------------------
    def snapshot(self) -> ObservabilitySnapshot:
        counters = self.registry.as_dict()["counters"]
        quarantine = self.quarantine.snapshot()
        evidence = self.evidence.as_dict()
        with self._lock:
            operations = tuple(self._operations)
            performance = {
                phase: dict(metrics)
                for phase, metrics in sorted(self._performance.items())
            }
            prompt_versions = dict(sorted(self._prompt_versions.items()))
            thresholds = dict(sorted(self._thresholds.items()))
            seeds = dict(sorted(self._seeds.items()))
        payload = {
            "counters": counters,
            "quarantine": {
                "total": quarantine.total,
                "by_reason": dict(quarantine.by_reason),
                "items": [
                    {
                        "phase": item.phase,
                        "reason": item.reason,
                        "item_id": item.item_id,
                        "payload": dict(item.payload),
                        "sequence": item.sequence,
                    }
                    for item in quarantine.items
                ],
            },
            "evidence": evidence,
            "operations": [
                {
                    "sequence": entry.sequence,
                    "phase": entry.phase,
                    "operation": entry.operation,
                    "outcome": entry.outcome,
                    "payload": dict(entry.payload),
                }
                for entry in operations
            ],
            "performance": performance,
            "prompt_versions": prompt_versions,
            "thresholds": thresholds,
            "seeds": seeds,
        }
        checksum = stable_hash(payload)
        return ObservabilitySnapshot(
            counters=counters,
            quarantine=payload["quarantine"],
            evidence=evidence,
            operations=operations,
            performance=performance,
            prompt_versions=prompt_versions,
            thresholds=thresholds,
            seeds=seeds,
            checksum=checksum,
        )

    def export(self) -> Dict[str, Any]:
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
                    "payload": dict(entry.payload),
                }
                for entry in snap.operations
            ],
            "performance": snap.performance,
            "prompt_versions": snap.prompt_versions,
            "thresholds": snap.thresholds,
            "seeds": snap.seeds,
            "checksum": snap.checksum,
        }


class PhaseHandle:
    """Helper exposed when entering a phase context."""

    def __init__(self, context: ObservabilityContext, phase: str) -> None:
        self._context = context
        self.phase = phase

    def increment(self, counter: str, value: int = 1, *, label: str | None = None) -> None:
        self._context.increment(counter, value, phase=self.phase, label=label)

    def set(self, counter: str, value: int) -> None:
        self._context.set_counter(counter, value, phase=self.phase)

    def bulk_update(self, values: Mapping[str, int]) -> None:
        self._context.bulk_update(values, phase=self.phase)

    def quarantine(
        self,
        *,
        reason: str,
        item_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
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
        payload: Mapping[str, Any],
        weight: float = 1.0,
    ) -> None:
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
        payload: Mapping[str, Any] | None = None,
    ) -> OperationLogEntry:
        return self._context.record_operation(
            phase=self.phase,
            operation=operation,
            outcome=outcome,
            payload=payload,
        )

    def performance(self, metrics: Mapping[str, Any]) -> None:
        self._context.record_performance(phase=self.phase, metrics=metrics)
