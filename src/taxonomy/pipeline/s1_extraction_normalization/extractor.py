"""LLM-backed extraction for S1 candidate generation."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from time import perf_counter
from typing import Callable, Dict, List, Mapping, Sequence, TYPE_CHECKING

from taxonomy.entities.core import SourceRecord
from taxonomy.llm import (
    ProviderError,
    QuarantineError,
    ValidationError,
    run as llm_run,
)
from taxonomy.utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    from taxonomy.observability import ObservabilityContext, PhaseHandle

@dataclass
class RawExtractionCandidate:
    """Raw candidate returned by the LLM prior to normalization."""

    label: str
    normalized: str
    aliases: List[str]
    parents: List[str]
    source: SourceRecord


@dataclass
class ExtractionMetrics:
    """Counters tracked for legacy compatibility in S1 extraction."""

    records_in: int = 0
    candidates_out: int = 0
    invalid_json: int = 0
    quarantined: int = 0
    provider_errors: int = 0
    retries: int = 0

    @classmethod
    def from_observability(
        cls,
        context: "ObservabilityContext" | None,
    ) -> "ExtractionMetrics":
        """Create a metrics snapshot backed by the observability registry."""

        if context is None:
            return cls()
        snapshot = context.snapshot()
        counters = snapshot.counters.get("S1", {})
        quarantined_items = snapshot.quarantine.get("items", [])
        quarantined = sum(
            1
            for entry in quarantined_items
            if isinstance(entry, Mapping) and entry.get("phase") == "S1"
        )
        provider_errors = sum(
            1
            for entry in snapshot.operations
            if entry.phase == "S1" and entry.operation == "provider_error"
        )
        invalid_json = sum(
            1
            for entry in snapshot.operations
            if entry.phase == "S1" and entry.operation == "invalid_json"
        )
        return cls(
            records_in=int(counters.get("records_in", 0)),
            candidates_out=int(counters.get("candidates_out", 0)),
            invalid_json=int(invalid_json),
            quarantined=int(quarantined),
            provider_errors=int(provider_errors),
            retries=int(counters.get("retries", 0)),
        )

    def as_dict(self) -> Dict[str, int]:
        return {
            "records_in": self.records_in,
            "candidates_out": self.candidates_out,
            "invalid_json": self.invalid_json,
            "quarantined": self.quarantined,
            "provider_errors": self.provider_errors,
            "retries": self.retries,
        }


class ExtractionProcessor:
    """Orchestrate deterministic LLM extraction for S1 processing."""

    def __init__(
        self,
        *,
        runner: Callable[[str, Dict[str, object]], object] | None = None,
        max_retries: int = 1,
        observability: "ObservabilityContext" | None = None,
    ) -> None:
        self._runner = runner or self._default_runner
        self._legacy_metrics = ExtractionMetrics()
        self._log = get_logger(module=__name__)
        self._max_retries = max(0, max_retries)
        self._observability = observability

    @property
    def metrics(self) -> ExtractionMetrics:
        if self._observability is not None:
            return ExtractionMetrics.from_observability(self._observability)
        return self._legacy_metrics

    @property
    def observability(self) -> "ObservabilityContext" | None:
        return self._observability

    def _increment_legacy(self, field: str, delta: int = 1) -> None:
        if self._observability is not None:
            return
        current = getattr(self._legacy_metrics, field)
        setattr(self._legacy_metrics, field, current + delta)

    def bind_observability(self, context: "ObservabilityContext") -> None:
        self._observability = context

    @staticmethod
    def _default_runner(prompt_key: str, variables: Dict[str, object]) -> object:
        response = llm_run(prompt_key, variables)
        if getattr(response, "ok", False):
            return response.content
        raise ProviderError(response.error or "LLM returned an error response", retryable=False)

    def extract_candidates(
        self,
        records: Sequence[SourceRecord],
        *,
        level: int,
        observability: "ObservabilityContext" | None = None,
    ) -> List[RawExtractionCandidate]:
        """Extract candidate payloads for *records* at the requested level."""

        if observability is not None:
            self._observability = observability
        obs = self._observability
        phase_cm = obs.phase("S1") if obs is not None else nullcontext()
        results: List[RawExtractionCandidate] = []
        batch_start = perf_counter()
        with phase_cm as phase:
            phase_handle: "PhaseHandle" | None = phase if obs is not None else None
            for record in records:
                self._increment_legacy("records_in")
                if phase_handle is not None:
                    phase_handle.increment("records_in")
                    phase_handle.log_operation(
                        operation="record_ingest",
                        payload={
                            "institution": record.provenance.institution,
                            "level": level,
                        },
                    )
                base_variables = {
                    "institution": record.provenance.institution,
                    "level": level,
                    "source_text": record.text,
                    "metadata": record.meta.model_dump(),
                }
                payload: object | None = None
                final_error: str | None = None
                error_reason: str | None = None
                for attempt in range(self._max_retries + 1):
                    variables = dict(base_variables)
                    if attempt > 0:
                        variables["repair"] = True
                    try:
                        payload = self._runner("taxonomy.extract", variables)
                        break
                    except ValidationError as exc:
                        self._increment_legacy("invalid_json")
                        final_error = str(exc)
                        error_reason = "invalid_json"
                        self._log.warning(
                            "LLM validation error during extraction",
                            error=final_error,
                            institution=record.provenance.institution,
                            attempt=attempt,
                        )
                        if phase_handle is not None:
                            phase_handle.log_operation(
                                operation="invalid_json",
                                outcome="error",
                                payload={
                                    "institution": record.provenance.institution,
                                    "attempt": attempt,
                                },
                            )
                        if attempt >= self._max_retries:
                            payload = None
                            if phase_handle is not None:
                                phase_handle.increment("invalid_json")
                                phase_handle.quarantine(
                                    reason="invalid_json",
                                    item_id=record.meta.hints.get("record_id")
                                    if hasattr(record.meta, "hints")
                                    else None,
                                    payload={
                                        "institution": record.provenance.institution,
                                        "level": level,
                                        "error": final_error,
                                    },
                                )
                            break
                        self._increment_legacy("retries")
                        if phase_handle is not None:
                            phase_handle.increment("retries")
                        continue
                    except ProviderError as exc:
                        self._increment_legacy("provider_errors")
                        final_error = str(exc)
                        error_reason = "provider_error"
                        self._log.error(
                            "Provider error during extraction",
                            error=final_error,
                            institution=record.provenance.institution,
                            attempt=attempt,
                        )
                        retryable = getattr(exc, "retryable", False)
                        if phase_handle is not None:
                            phase_handle.log_operation(
                                operation="provider_error",
                                outcome="retry" if retryable else "failure",
                                payload={
                                    "institution": record.provenance.institution,
                                    "attempt": attempt,
                                    "retryable": retryable,
                                },
                            )
                        if (not retryable) or attempt >= self._max_retries:
                            payload = None
                            if phase_handle is not None and not retryable:
                                phase_handle.quarantine(
                                    reason="provider_error",
                                    item_id=record.meta.hints.get("record_id")
                                    if hasattr(record.meta, "hints")
                                    else None,
                                    payload={
                                        "institution": record.provenance.institution,
                                        "level": level,
                                        "error": final_error,
                                    },
                                )
                            break
                        self._increment_legacy("retries")
                        if phase_handle is not None:
                            phase_handle.increment("retries")
                        continue
                    except QuarantineError as exc:
                        self._increment_legacy("quarantined")
                        final_error = str(exc)
                        error_reason = "quarantined"
                        self._log.error(
                            "LLM response quarantined",
                            error=final_error,
                            institution=record.provenance.institution,
                            attempt=attempt,
                        )
                        payload = None
                        if phase_handle is not None:
                            phase_handle.quarantine(
                                reason="llm_quarantine",
                                item_id=record.meta.hints.get("record_id")
                                if hasattr(record.meta, "hints")
                                else None,
                                payload={
                                    "institution": record.provenance.institution,
                                    "level": level,
                                    "error": final_error,
                                },
                            )
                            phase_handle.log_operation(
                                operation="llm_quarantine",
                                outcome="error",
                                payload={
                                    "institution": record.provenance.institution,
                                    "attempt": attempt,
                                },
                            )
                        break
                else:
                    payload = None

                if payload is None:
                    if phase_handle is not None and final_error is not None:
                        phase_handle.evidence(
                            category="extraction",
                            outcome="failure",
                            payload={
                                "institution": record.provenance.institution,
                                "level": level,
                                "error": final_error,
                                "reason": error_reason,
                            },
                            weight=1.0,
                        )
                    continue

                raw_candidates = self._coerce_payload(payload, record)
                results.extend(raw_candidates)
                produced = len(raw_candidates)
                self._increment_legacy("candidates_out", produced)
                if phase_handle is not None:
                    if produced:
                        phase_handle.increment("candidates_out", value=produced)
                        phase_handle.log_operation(
                            operation="candidates_emitted",
                            payload={
                                "institution": record.provenance.institution,
                                "count": produced,
                            },
                        )
                        phase_handle.evidence(
                            category="extraction",
                            outcome="success",
                            payload={
                                "institution": record.provenance.institution,
                                "level": level,
                                "candidates": produced,
                                "sample": raw_candidates[0].normalized,
                            },
                            weight=min(1.0, produced / 5.0),
                        )
                    else:
                        phase_handle.evidence(
                            category="extraction",
                            outcome="failure",
                            payload={
                                "institution": record.provenance.institution,
                                "level": level,
                                "error": "no_candidates_emitted",
                            },
                        )
            if phase_handle is not None:
                elapsed = perf_counter() - batch_start
                phase_handle.performance(
                    {
                        "elapsed_seconds": elapsed,
                        "records": len(records),
                        "raw_candidates": len(results),
                    }
                )
        return results

    def _coerce_payload(
        self,
        payload: object,
        record: SourceRecord,
    ) -> List[RawExtractionCandidate]:
        if not isinstance(payload, list):
            self._log.warning(
                "LLM returned non-list payload",
                payload_type=type(payload).__name__,
                institution=record.provenance.institution,
            )
            return []

        results: List[RawExtractionCandidate] = []
        for entry in payload:
            if not isinstance(entry, dict):
                self._log.debug(
                    "Skipping non-dict candidate entry",
                    entry_type=type(entry).__name__,
                )
                continue
            label = str(entry.get("label", ""))
            normalized = str(entry.get("normalized", ""))
            aliases = [str(alias) for alias in entry.get("aliases", []) if str(alias).strip()]
            parents = [str(anchor) for anchor in entry.get("parents", []) if str(anchor).strip()]
            if not label.strip() or not normalized.strip():
                self._log.debug(
                    "Dropping incomplete candidate",
                    label=len(label),
                    normalized=len(normalized),
                )
                continue
            results.append(
                RawExtractionCandidate(
                    label=label.strip(),
                    normalized=normalized.strip(),
                    aliases=aliases,
                    parents=parents,
                    source=record,
                )
            )
        # Defensive sort ensures deterministic downstream ordering.
        results.sort(key=lambda entry: entry.normalized.lower())
        return results


__all__ = ["ExtractionProcessor", "ExtractionMetrics", "RawExtractionCandidate"]
