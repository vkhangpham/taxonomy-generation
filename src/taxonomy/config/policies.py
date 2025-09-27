"""Policy configuration primitives derived from docs/policies.md."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class LevelThreshold(BaseModel):
    """Threshold configuration for a specific hierarchy level."""

    min_institutions: int = Field(..., ge=0)
    min_src_count: int = Field(..., ge=0)
    weight_formula: str = Field(
        default="1.0*inst_count + 0.3*log(1+src_count)",
        description="Human-readable representation of the weighting rule.",
    )


class LevelThresholds(BaseModel):
    """Collection of threshold policies for every hierarchy level."""

    level_0: LevelThreshold
    level_1: LevelThreshold
    level_2: LevelThreshold
    level_3: LevelThreshold


class MinimalCanonicalForm(BaseModel):
    """Normalization rules for canonical labels."""

    case: str = Field(default="lower", description="Case normalization rule")
    remove_punctuation: bool = True
    fold_diacritics: bool = True
    collapse_whitespace: bool = True
    min_length: int = Field(default=2, ge=1)
    max_length: int = Field(default=64, ge=2)
    boilerplate_patterns: List[str] = Field(default_factory=list)


class LabelPolicy(BaseModel):
    """Collection of policies governing label generation."""

    minimal_canonical_form: MinimalCanonicalForm
    token_minimality_preference: str = Field(
        default="prefer_shortest_unique",
        description="Strategy for choosing among competing canonical forms.",
    )
    punctuation_handling: str = Field(
        default="strip_terminal",
        description="How punctuation should be treated during normalization.",
    )


class InstitutionPolicy(BaseModel):
    """Rules for mapping and reconciling institutional identities."""

    campus_vs_system: str = Field(default="prefer-campus")
    joint_center_handling: str = Field(default="duplicate-under-both")
    cross_listing_strategy: str = Field(default="merge-with-stronger-parent")
    canonical_mappings: Dict[str, str] = Field(default_factory=dict)


class FirecrawlPolicy(BaseModel):
    """Defaults for firecrawl crawling sessions."""

    concurrency: int = Field(default=6, ge=1, le=16)
    max_depth: int = Field(default=3, ge=1)
    max_pages: int = Field(default=300, ge=1)
    render_timeout_ms: int = Field(default=10000, ge=1000)


class WebDomainRules(BaseModel):
    """Constraints for web crawling and scraping."""

    allowed_domains: List[str] = Field(default_factory=list)
    disallowed_paths: List[str] = Field(default_factory=list)
    robots_txt_compliance: bool = Field(default=True)
    dynamic_content: bool = Field(default=False)
    pdf_processing_limit: int = Field(default=500, ge=0)
    ttl_cache_days: int = Field(default=14, ge=0)
    firecrawl: FirecrawlPolicy = Field(default_factory=FirecrawlPolicy)


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


class ObservabilitySettings(BaseModel):
    """Metrics and audit logging controls."""

    metrics_enabled: bool = True
    audit_logging: bool = False
    performance_tracking: bool = True


class CostTrackingSettings(BaseModel):
    """Cost and quota reporting controls."""

    token_budget_per_hour: int = Field(default=0, ge=0)
    enabled: bool = False


class LLMDeterminismSettings(BaseModel):
    """Deterministic configuration for DSPy orchestrated prompts."""

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
    registry: RegistrySettings = Field(default_factory=lambda: RegistrySettings(
        file="prompts/registry.yaml",
        templates_root="prompts",
        schema_root="prompts",
        hot_reload=False,
    ))
    repair: RepairSettings = Field(default_factory=RepairSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    cost_tracking: CostTrackingSettings = Field(default_factory=CostTrackingSettings)

    @model_validator(mode="after")
    def _ensure_profile(self) -> "LLMDeterminismSettings":
        if self.default_profile and self.default_profile not in self.profiles:
            raise ValueError(
                f"LLM default_profile '{self.default_profile}' is missing from profiles configuration"
            )
        return self


class DeduplicationThresholds(BaseModel):
    """Similarity thresholds for deduplication per level band."""

    l0_l1: float = Field(default=0.93, ge=0.0, le=1.0)
    l2_l3: float = Field(default=0.90, ge=0.0, le=1.0)


class DeduplicationPolicy(BaseModel):
    """Policy governing merge behaviour for similar concepts."""

    thresholds: DeduplicationThresholds
    merge_policy: str = Field(default="conservative")


class LevelZeroExcelPolicy(BaseModel):
    """Specialised configuration for the level 0 Excel handler."""

    excel_file: str = Field(..., description="Path to the Faculty Extraction Report")
    sheets_to_process: List[str] = Field(default_factory=list)
    top_n_institutions: int = Field(default=25, ge=1)
    random_seed: int = Field(default=20230927)


class Policies(BaseModel):
    """Root policy container."""

    policy_version: str = Field(default="2025-09-27")
    level_thresholds: LevelThresholds
    label_policy: LabelPolicy
    institution_policy: InstitutionPolicy
    web: WebDomainRules
    llm: LLMDeterminismSettings
    deduplication: DeduplicationPolicy
    level0_excel: LevelZeroExcelPolicy

    @model_validator(mode="after")
    def _validate_policy_version(self) -> "Policies":
        if not self.policy_version:
            raise ValueError("policy_version must be provided")
        return self


def _resolve_env_overrides(raw: dict) -> dict:
    """Apply environment variable overrides using TAXONOMY_POLICY__ prefix."""

    prefix = "TAXONOMY_POLICY__"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        path = key[len(prefix) :].lower().split("__")
        cursor = raw
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            parsed = value
        cursor[path[-1]] = parsed
    return raw


def load_policies(source: Path | Dict[str, Any]) -> Policies:
    """Load policies from a dictionary or YAML file with environment overrides."""

    if isinstance(source, Path):
        if not source.exists():
            raise FileNotFoundError(f"Policy file not found: {source}")
        with source.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
    else:
        raw = dict(source)
    hydrated = _resolve_env_overrides(raw)
    return Policies.model_validate(hydrated)


__all__ = [
    "Policies",
    "load_policies",
    "LevelThresholds",
    "LevelThreshold",
    "LabelPolicy",
    "InstitutionPolicy",
    "WebDomainRules",
    "LLMDeterminismSettings",
    "DeduplicationPolicy",
    "LevelZeroExcelPolicy",
]
