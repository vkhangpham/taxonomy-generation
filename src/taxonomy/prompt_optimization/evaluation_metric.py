"""Evaluation metric with strict guardrails for GEPA optimization."""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Tuple

import dspy

from ..llm.validation import JSONValidator


@dataclass
class MetricStats:
    """Rolling statistics collected across metric invocations."""

    total: int = 0
    json_success: int = 0
    schema_success: int = 0
    latency_ms: List[float] = field(default_factory=list)
    token_cost: List[int] = field(default_factory=list)

    def record_json(self, ok: bool) -> None:
        self.total += 1
        if ok:
            self.json_success += 1

    def record_schema(self, ok: bool) -> None:
        if ok:
            self.schema_success += 1

    @property
    def json_validity(self) -> float:
        if self.total == 0:
            return 0.0
        return self.json_success / self.total

    @property
    def schema_adherence(self) -> float:
        if self.total == 0:
            return 0.0
        return self.schema_success / self.total

    def register_latency(self, value: float | None) -> None:
        if value is not None:
            self.latency_ms.append(float(value))

    def register_token_cost(self, value: int | None) -> None:
        if value is not None:
            self.token_cost.append(int(value))

    def summary(self) -> Dict[str, float]:
        latency = statistics.mean(self.latency_ms) if self.latency_ms else 0.0
        tokens = statistics.mean(self.token_cost) if self.token_cost else 0.0
        return {
            "json_validity": round(self.json_validity, 4),
            "schema_adherence": round(self.schema_adherence, 4),
            "avg_latency_ms": round(latency, 2),
            "avg_tokens": round(tokens, 2),
        }


class TaxonomyEvaluationMetric:
    """Callable object producing GEPA-compatible scores with textual feedback."""

    def __init__(
        self,
        *,
        validator: JSONValidator,
        schema_path: str = "schemas/extraction.json",
        json_validity_threshold: float = 0.995,
        schema_adherence_threshold: float = 1.0,
    ) -> None:
        self._validator = validator
        self._schema_path = schema_path
        self._json_validity_threshold = json_validity_threshold
        self._schema_adherence_threshold = schema_adherence_threshold
        self._stats = MetricStats()

    @property
    def stats(self) -> MetricStats:
        return self._stats

    def __call__(
        self,
        gold,
        pred,
        trace=None,
        pred_name=None,
        pred_trace=None,
    ) -> dspy.Prediction:
        """Evaluate a prediction and return score + textual feedback."""

        guardrail_errors: List[str] = []
        try:
            expected_labels = self._normalize_labels(getattr(gold, "gold_labels", []))
            raw_response = self._extract_response(pred)
            validation = self._validator.validate(
                raw_response,
                self._schema_path,
                enforce_order_by="normalized",
            )
            self._stats.record_json(validation.ok)
            self._stats.record_schema(validation.ok)
            current_json_validity = 1.0 if validation.ok else 0.0
            current_schema_adherence = 1.0 if validation.ok else 0.0

            if not validation.ok or not isinstance(validation.parsed, list):
                guardrail_errors.append("Invalid JSON or schema mismatch")
                predicted = []
            else:
                normalized_values, unique_values = self._normalize_prediction(validation.parsed)
                predicted = unique_values
                guardrail_errors.extend(
                    self._collect_guardrail_errors(
                        raw=raw_response,
                        normalized_sequence=normalized_values,
                        unique_sequence=unique_values,
                    )
                )

            if current_json_validity < self._json_validity_threshold:
                guardrail_errors.append(
                    f"JSON validity below threshold: {current_json_validity:.3f}"
                )
            if current_schema_adherence < self._schema_adherence_threshold:
                guardrail_errors.append(
                    f"Schema adherence below threshold: {current_schema_adherence:.3f}"
                )

            precision, recall, f1 = self._compute_scores(expected_labels, predicted)

            if guardrail_errors:
                score = 0.0
            else:
                score = f1

            feedback = self._build_feedback(
                precision=precision,
                recall=recall,
                f1=f1,
                guardrail_errors=guardrail_errors,
                expected=expected_labels,
                predicted=predicted,
            )
            return dspy.Prediction(score=score, feedback=feedback)
        except Exception as exc:  # pragma: no cover - defensive path
            return dspy.Prediction(
                score=0.0,
                feedback=f"Metric error: {exc}",
            )

    def _extract_response(self, pred) -> str:
        if hasattr(pred, "raw_response"):
            return str(pred.raw_response)
        if hasattr(pred, "response"):
            return str(pred.response)
        if isinstance(pred, str):
            return pred
        if hasattr(pred, "candidates"):
            return json.dumps(getattr(pred, "candidates"))
        raise ValueError("Prediction does not expose a response payload")

    @staticmethod
    def _normalize_labels(labels: Iterable[str]) -> List[str]:
        normalized = []
        for label in labels:
            text = str(label).strip().lower()
            if text:
                normalized.append(text)
        return sorted(set(normalized))

    @staticmethod
    def _normalize_prediction(payload: Sequence[dict]) -> Tuple[List[str], List[str]]:
        normalized: List[str] = []
        for item in payload:
            normalized_value = str(item.get("normalized", "")).strip().lower()
            if not normalized_value:
                continue
            normalized.append(normalized_value)
        unique_sorted = sorted(set(normalized))
        return normalized, unique_sorted

    def _collect_guardrail_errors(
        self,
        *,
        raw: str,
        normalized_sequence: Sequence[str],
        unique_sequence: Sequence[str],
    ) -> List[str]:
        errors: List[str] = []
        if raw.strip() and not raw.strip().startswith("["):
            errors.append("Non-JSON prefix detected")
        if len(normalized_sequence) != len(unique_sequence):
            errors.append("Duplicate normalized labels emitted")
        if normalized_sequence != sorted(normalized_sequence):
            errors.append("Output not sorted by normalized field")
        if raw.count("\n\n") > 8:
            errors.append("Possible chain-of-thought leakage detected")
        if unique_sequence and any("{" in label or "}" in label for label in unique_sequence):
            errors.append("Normalized labels contain braces")
        return errors

    @staticmethod
    def _compute_scores(
        expected: Sequence[str],
        predicted: Sequence[str],
    ) -> Tuple[float, float, float]:
        expected_set = set(expected)
        predicted_set = set(predicted)
        true_positive = len(expected_set & predicted_set)
        precision = true_positive / len(predicted_set) if predicted_set else 0.0
        recall = true_positive / len(expected_set) if expected_set else 0.0
        if precision + recall == 0.0:
            f1 = 0.0
        else:
            f1 = 2 * precision * recall / (precision + recall)
        return precision, recall, f1

    def _build_feedback(
        self,
        *,
        precision: float,
        recall: float,
        f1: float,
        guardrail_errors: Sequence[str],
        expected: Sequence[str],
        predicted: Sequence[str],
    ) -> str:
        summary = (
            f"Precision={precision:.3f}, Recall={recall:.3f}, F1={f1:.3f}."
            f" Expected={list(expected)} Predicted={list(predicted)}."
        )
        if guardrail_errors:
            guardrail_text = "; ".join(guardrail_errors)
            return f"Guardrail violation: {guardrail_text}. {summary}"
        if f1 == 1.0:
            return f"Perfect match. {summary}"
        if precision < 1.0:
            return f"Drop spurious labels. {summary}"
        if recall < 1.0:
            return f"Add missing gold labels. {summary}"
        return summary


__all__ = ["TaxonomyEvaluationMetric", "MetricStats"]
