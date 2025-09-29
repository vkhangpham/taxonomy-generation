"""S2 frequency filtering processor orchestration."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from time import perf_counter
from typing import Iterable, TYPE_CHECKING

from taxonomy.utils.logging import get_logger

from .aggregator import (
    CandidateAggregator,
    CandidateEvidence,
    FrequencyAggregationResult,
    FrequencyDecision,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from taxonomy.observability import ObservabilityContext, PhaseHandle


def _decision_evidence_payload(decision: FrequencyDecision) -> dict[str, object]:
    """Return a JSON-safe payload summarising a frequency decision."""

    candidate_payload = decision.candidate.model_dump(mode="json", exclude_none=True)
    rationale_payload = decision.rationale.model_dump(mode="json")
    return {
        "candidate": candidate_payload,
        "institutions": list(decision.institutions),
        "record_fingerprints": list(decision.record_fingerprints),
        "weight": float(decision.weight),
        "passed": bool(decision.passed),
        "rationale": rationale_payload,
    }


@dataclass
class S2Processor:
    """Coordinate S2 aggregation and threshold evaluation."""

    aggregator: CandidateAggregator
    observability: "ObservabilityContext | None" = None

    def __post_init__(self) -> None:
        self._log = get_logger(module=__name__)

    def bind_observability(self, context: "ObservabilityContext") -> None:
        """Attach an :class:`ObservabilityContext` after initialisation."""

        self.observability = context

    def process(self, items: Iterable[CandidateEvidence]) -> FrequencyAggregationResult:
        """Process an iterable of S1 candidates through frequency filtering."""

        observability = self.observability
        phase_cm = observability.phase("S2") if observability is not None else nullcontext()
        started_at = perf_counter()

        with phase_cm as handle:
            phase: "PhaseHandle | None" = handle if observability is not None else None
            if phase is not None:
                phase.log_operation(operation="frequency_aggregation_start")

            try:
                result = self.aggregator.aggregate(items)
            except Exception as exc:  # pragma: no cover - defensive guard
                if phase is not None:
                    phase.log_operation(
                        operation="frequency_aggregation_failed",
                        outcome="error",
                        payload={"error": repr(exc)},
                    )
                raise

            stats = dict(result.stats)
            total_inputs = int(stats.get("candidates_in", 0))
            kept_decisions = result.kept
            dropped_decisions = result.dropped

            if total_inputs == 0:
                total_inputs = len(kept_decisions) + len(dropped_decisions)

            if phase is not None:
                if total_inputs:
                    phase.increment("candidates_in", total_inputs)

                for decision in kept_decisions:
                    phase.increment("kept")
                    phase.evidence(
                        category="frequency_filtering",
                        outcome="kept",
                        payload=_decision_evidence_payload(decision),
                        weight=max(1.0, float(decision.weight)),
                    )

                for decision in dropped_decisions:
                    phase.increment("dropped_insufficient_support")
                    phase.evidence(
                        category="frequency_filtering",
                        outcome="dropped_insufficient_support",
                        payload=_decision_evidence_payload(decision),
                        weight=max(1.0, float(decision.weight)),
                    )

                elapsed = perf_counter() - started_at
                histogram = stats.get("institutions_histogram", {})
                phase.performance(
                    {
                        "elapsed_seconds": elapsed,
                        "candidates_processed": total_inputs,
                        "aggregated_groups": int(stats.get("aggregated_groups", 0)),
                        "kept": len(kept_decisions),
                        "dropped": len(dropped_decisions),
                        "institutions_histogram": histogram,
                    }
                )
                phase.log_operation(
                    operation="frequency_aggregation_complete",
                    payload={
                        "elapsed_seconds": elapsed,
                        "kept": len(kept_decisions),
                        "dropped": len(dropped_decisions),
                        "groups": int(stats.get("aggregated_groups", 0)),
                    },
                )

                snapshot = observability.snapshot()
                counters = snapshot.counters.get("S2", {})
                for key in ("candidates_in", "kept", "dropped_insufficient_support"):
                    if key in counters:
                        stats[key] = int(counters[key])
                stats["observability_checksum"] = snapshot.checksum

            result.stats = stats

        self._log.info(
            "Completed S2 frequency filtering",
            stats=result.stats,
        )

        return result


__all__ = ["S2Processor"]
