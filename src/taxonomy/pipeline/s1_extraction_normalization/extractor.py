"""LLM-backed extraction for S1 candidate generation."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence, TYPE_CHECKING

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
    """Counters tracked for observability and testing."""

    records_in: int = 0
    candidates_out: int = 0
    invalid_json: int = 0
    quarantined: int = 0
    provider_errors: int = 0
    retries: int = 0


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
        self.metrics = ExtractionMetrics()
        self._log = get_logger(module=__name__)
        self._max_retries = max(0, max_retries)
        self._observability = observability

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

        obs = observability or self._observability
        phase_cm = obs.phase("S1") if obs is not None else nullcontext()
        results: List[RawExtractionCandidate] = []
        with phase_cm as phase:
            phase_handle: "PhaseHandle" | None = phase if obs is not None else None
            for record in records:
                self.metrics.records_in += 1
                if phase_handle is not None:
                    phase_handle.increment("records_in")
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
                        self.metrics.invalid_json += 1
                        final_error = str(exc)
                        error_reason = "invalid_json"
                        self._log.warning(
                            "LLM validation error during extraction",
                            error=final_error,
                            institution=record.provenance.institution,
                            attempt=attempt,
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
                        self.metrics.retries += 1
                        if phase_handle is not None:
                            phase_handle.increment("retries")
                        continue
                    except ProviderError as exc:
                        self.metrics.provider_errors += 1
                        final_error = str(exc)
                        error_reason = "provider_error"
                        self._log.error(
                            "Provider error during extraction",
                            error=final_error,
                            institution=record.provenance.institution,
                            attempt=attempt,
                        )
                        retryable = getattr(exc, "retryable", False)
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
                        self.metrics.retries += 1
                        if phase_handle is not None:
                            phase_handle.increment("retries")
                        continue
                    except QuarantineError as exc:
                        self.metrics.quarantined += 1
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
                self.metrics.candidates_out += produced
                if phase_handle is not None:
                    if produced:
                        phase_handle.increment("candidates_out", value=produced)
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
