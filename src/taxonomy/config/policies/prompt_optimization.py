"""Prompt optimization policy models."""

from __future__ import annotations

from typing import List, Literal

from pydantic import BaseModel, Field, model_validator


class PromptOptimizationPolicy(BaseModel):
    """Configuration governing one-time DSPy GEPA optimization runs."""

    optimization_budget: Literal["light", "medium", "heavy"] = Field(default="heavy")
    comprehensive_search: bool = Field(default=True)
    deploy_immediately: bool = Field(default=True)
    validation_ratio: float = Field(default=0.2, ge=0.05, le=0.4)
    random_seed: int = Field(default=20250927)
    explore_all_few_shot_k: bool = Field(default=True)
    explore_temperature_variants: bool = Field(default=True)
    explore_constraint_variants: bool = Field(default=True)
    default_few_shot_k: int = Field(default=2, ge=0)
    constraint_variant: str = Field(default="baseline")
    few_shot_k_options: List[int] | None = Field(default=None)
    temperature_variants: List[float] | None = Field(default=None)
    constraint_variants: List[str] | None = Field(default=None)
    json_validity_threshold: float = Field(default=0.995, ge=0.0, le=1.0)
    schema_adherence_threshold: float = Field(default=1.0, ge=0.0, le=1.0)
    strict_guardrail_enforcement: bool = Field(default=True)
    min_trials_for_confidence: int = Field(default=30, ge=1)
    convergence_patience: int = Field(default=15, ge=1)
    backup_before_deployment: bool = Field(default=True)
    validate_deployed_variant: bool = Field(default=True)
    rollback_on_failure: bool = Field(default=True)
    use_merge: bool = Field(default=True)
    reflection_model: str | None = Field(default=None)

    @model_validator(mode="after")
    def _validate_budget(self) -> "PromptOptimizationPolicy":
        if self.optimization_budget not in {"light", "medium", "heavy"}:
            raise ValueError("optimization_budget must be one of 'light', 'medium', or 'heavy'")

        if self.few_shot_k_options:
            deduped = sorted({max(0, int(value)) for value in self.few_shot_k_options})
            if not deduped:
                raise ValueError("few_shot_k_options must include at least one non-negative integer")
            if self.default_few_shot_k not in deduped:
                deduped.append(self.default_few_shot_k)
                deduped = sorted(set(deduped))
            self.few_shot_k_options = deduped

        if self.temperature_variants:
            temps = sorted({max(0.0, float(value)) for value in self.temperature_variants})
            if not temps:
                raise ValueError("temperature_variants must include at least one non-negative float")
            self.temperature_variants = temps

        if self.constraint_variants:
            variants = [str(value).strip() for value in self.constraint_variants if str(value).strip()]
            if not variants:
                raise ValueError("constraint_variants must include at least one identifier")
            if self.constraint_variant not in variants:
                variants.append(self.constraint_variant)
            self.constraint_variants = sorted(set(variants))

        return self


__all__ = ["PromptOptimizationPolicy"]
