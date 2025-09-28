"""Evidence sampling utilities for observability."""
from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any, Dict, Mapping

from .determinism import build_rng, stable_sorted


@dataclass(frozen=True)
class EvidenceSample:
    """Captured evidence supporting an observability decision."""

    phase: str
    category: str
    outcome: str
    payload: Mapping[str, Any]
    sequence: int


@dataclass(frozen=True)
class EvidenceSnapshot:
    """Immutable snapshot of collected evidence."""

    samples: Mapping[str, tuple[EvidenceSample, ...]]
    total_considered: Mapping[str, int]


class EvidenceSampler:
    """Reservoir sampler with deterministic seeding."""

    def __init__(
        self,
        *,
        sampling_rate: float = 0.1,
        max_samples_per_phase: int = 100,
        seed: int = 42,
    ) -> None:
        self._rate = max(0.0, min(1.0, sampling_rate))
        self._limit = max(1, int(max_samples_per_phase))
        self._rng = build_rng(seed, namespace="observability.evidence")
        self._lock = RLock()
        self._samples: Dict[str, list[EvidenceSample]] = {}
        self._counters: Dict[str, int] = {}
        self._sequence = 0

    def consider(
        self,
        *,
        phase: str,
        category: str,
        outcome: str,
        payload: Mapping[str, Any],
        weight: float = 1.0,
    ) -> EvidenceSample | None:
        """Consider *payload* for sampling.

        Returns the sampled entry when it is kept, otherwise ``None``.
        """

        if weight <= 0:
            return None
        probability = min(1.0, max(0.0, self._rate * weight))
        with self._lock:
            self._sequence += 1
            seen = self._counters.get(phase, 0) + 1
            self._counters[phase] = seen
            if probability == 0 and seen > self._limit:
                return None
            trigger = probability >= 1.0 or self._rng.random() < probability
            if not trigger:
                return None

            entry = EvidenceSample(
                phase=phase,
                category=category,
                outcome=outcome,
                payload=dict(payload),
                sequence=self._sequence,
            )

            bucket = self._samples.setdefault(phase, [])
            if len(bucket) < self._limit:
                bucket.append(entry)
            else:
                # Reservoir sampling with deterministic RNG.
                idx = int(self._rng.random() * seen)
                if idx < self._limit:
                    bucket[idx] = entry
                else:
                    return None
            return entry

    def snapshot(self) -> EvidenceSnapshot:
        with self._lock:
            samples = {
                phase: tuple(
                    sorted(entries, key=lambda sample: sample.sequence)
                )
                for phase, entries in self._samples.items()
            }
            totals = dict(self._counters)
        ordered_samples = {
            phase: tuple(entries)
            for phase, entries in sorted(samples.items(), key=lambda item: item[0])
        }
        ordered_totals = {
            phase: totals.get(phase, 0)
            for phase in stable_sorted(totals)
        }
        return EvidenceSnapshot(samples=ordered_samples, total_considered=ordered_totals)

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()
            self._counters.clear()
            self._sequence = 0

    def as_dict(self) -> Dict[str, Any]:
        snap = self.snapshot()
        return {
            "samples": {
                phase: [
                    {
                        "category": entry.category,
                        "outcome": entry.outcome,
                        "sequence": entry.sequence,
                        "payload": dict(entry.payload),
                    }
                    for entry in entries
                ]
                for phase, entries in snap.samples.items()
            },
            "total_considered": dict(snap.total_considered),
        }
