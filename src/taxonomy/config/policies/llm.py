"""LLM runtime policy models."""

from __future__ import annotations

from typing import Dict

from pydantic import BaseModel, Field, model_validator

from .observability import CostTrackingSettings, ObservabilitySettings


class ProviderProfileSettings(BaseModel):
    """Configuration for a provider profile mapping."""

    provider: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)


class RegistrySettings(BaseModel):
    """Filesystem configuration for prompt templates and schemas."""

    file: str = Field(..., min_length=1)
    templates_root: str = Field(..., min_length=1)
    schema_root: str = Field(..., min_length=1)
    hot_reload: bool = False


class RepairSettings(BaseModel):
    """Configuration for JSON repair and quarantine logic."""

    quarantine_after_attempts: int = Field(default=3, ge=1)


class LLMDeterminismSettings(BaseModel):
    """Deterministic configuration for DSPy orchestrated prompts.

    When ``profiles`` is empty the ``default_profile`` is auto-populated with an
    OpenAI fallback so that existing configurations continue to succeed without
    additional settings.
    """

    temperature: float = Field(default=0.0, ge=0.0)
    nucleus_top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    json_mode: bool = Field(default=True)
    retry_attempts: int = Field(default=3, ge=0)
    retry_backoff_seconds: float = Field(default=2.0, ge=0.0)
    random_seed: int = Field(default=12345)
    token_budget: int = Field(default=4096, ge=128)
    request_timeout_seconds: float = Field(default=30.0, ge=0.1)
    default_profile: str = Field(default="standard", min_length=1)
    profiles: Dict[str, ProviderProfileSettings] = Field(default_factory=dict)
    registry: RegistrySettings = Field(
        default_factory=lambda: RegistrySettings(
            file="prompts/registry.yaml",
            templates_root="prompts",
            schema_root="prompts",
            hot_reload=False,
        )
    )
    repair: RepairSettings = Field(default_factory=RepairSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    cost_tracking: CostTrackingSettings = Field(default_factory=CostTrackingSettings)

    @model_validator(mode="after")
    def _ensure_profile(self) -> "LLMDeterminismSettings":
        """Ensure the default profile exists, auto-populating when none provided."""

        if self.default_profile and self.default_profile not in self.profiles:
            if not self.profiles:
                self.profiles[self.default_profile] = ProviderProfileSettings(
                    provider="openai",
                    model="gpt-4o-mini",
                )
            else:
                raise ValueError(
                    f"LLM default_profile '{self.default_profile}' is missing from profiles configuration"
                )
        return self
