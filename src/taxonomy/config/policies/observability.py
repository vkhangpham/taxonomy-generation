"""Observability and audit policy models."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class ObservabilitySettings(BaseModel):
    """Metrics and audit logging controls for LLM integrations."""

    metrics_enabled: bool = True
    audit_logging: bool = False
    performance_tracking: bool = True


class CostTrackingSettings(BaseModel):
    """Cost and quota reporting controls."""

    token_budget_per_hour: int = Field(default=0, ge=0)
    enabled: bool = False


class ObservabilityPolicy(BaseModel):
    """Global observability controls for the taxonomy pipeline.

    When ``audit_trail_generation`` is enabled an audit file is written using the
    redaction keys configured via ``redact_observability_fields``.
    """

    counter_registry_enabled: bool = Field(default=True)
    evidence_sampling_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    quarantine_logging_enabled: bool = Field(default=True)
    max_evidence_samples_per_phase: int = Field(default=100, ge=1)
    deterministic_sampling_seed: int = Field(default=42)
    performance_tracking_enabled: bool = Field(default=True)
    audit_trail_generation: bool = Field(default=True)
    fail_fast_observability: bool = Field(default=False)
    redact_observability_fields: tuple[str, ...] = Field(
        default=("authorization", "api_key", "apiKey", "secret", "token", "password"),
    )
    manifest_checksum_validation: bool = Field(default=True)
    max_operation_log_entries: int = Field(default=5000, ge=1)
    max_quarantine_items: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _validate_sampling(self) -> "ObservabilityPolicy":
        if self.max_evidence_samples_per_phase <= 0:
            raise ValueError(
                "max_evidence_samples_per_phase must be a positive integer"
            )
        if self.deterministic_sampling_seed < 0:
            raise ValueError(
                "deterministic_sampling_seed must be greater than or equal to 0"
            )
        return self
