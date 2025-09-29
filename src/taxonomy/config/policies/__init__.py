"""Policy configuration primitives derived from docs/policies.md."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

import yaml
from pydantic import BaseModel, Field, model_validator

from .disambiguation import DisambiguationPolicy
from .extraction import (
    DeduplicationPolicy,
    DeduplicationThresholds,
    FrequencyFilteringPolicy,
    LevelZeroExcelPolicy,
    NearDuplicateDedupPolicy,
    RawExtractionPolicy,
)
from .hierarchy import HierarchyAssemblyPolicy
from .identity import InstitutionPolicy
from .llm import (
    LLMDeterminismSettings,
    ProviderProfileSettings,
    RegistrySettings,
    RepairSettings,
)
from .observability import CostTrackingSettings, ObservabilityPolicy, ObservabilitySettings
from .prompt_optimization import PromptOptimizationPolicy
from .thresholds import LevelThreshold, LevelThresholds
from .validation import (
    EvidenceStorageSettings,
    LabelPolicy,
    LLMValidationSettings,
    MinimalCanonicalForm,
    RuleValidationSettings,
    SingleTokenVerificationPolicy,
    ValidationAggregationSettings,
    ValidationPolicy,
    WebValidationSettings,
)
from .web import (
    CacheSettings,
    ContentProcessingSettings,
    CrawlBudgets,
    FirecrawlPolicy,
    WebDomainRules,
    WebObservabilitySettings,
)


class Policies(BaseModel):
    """Root policy container."""

    policy_version: str = Field(default="2025-09-27")
    level_thresholds: LevelThresholds
    frequency_filtering: FrequencyFilteringPolicy = Field(
        default_factory=FrequencyFilteringPolicy
    )
    label_policy: LabelPolicy
    single_token: SingleTokenVerificationPolicy = Field(
        default_factory=SingleTokenVerificationPolicy
    )
    institution_policy: InstitutionPolicy
    web: WebDomainRules
    llm: LLMDeterminismSettings
    disambiguation: DisambiguationPolicy = Field(
        default_factory=DisambiguationPolicy
    )
    deduplication: DeduplicationPolicy
    raw_extraction: RawExtractionPolicy
    level0_excel: LevelZeroExcelPolicy
    validation: ValidationPolicy = Field(default_factory=ValidationPolicy)
    observability: ObservabilityPolicy = Field(default_factory=ObservabilityPolicy)
    hierarchy_assembly: HierarchyAssemblyPolicy = Field(
        default_factory=HierarchyAssemblyPolicy
    )
    prompt_optimization: PromptOptimizationPolicy = Field(
        default_factory=PromptOptimizationPolicy
    )

    @model_validator(mode="after")
    def _validate_policy_version(self) -> "Policies":
        if not self.policy_version:
            raise ValueError("policy_version must be provided")
        return self


def _ensure_nested_mapping(
    cursor: MutableMapping[str, Any], part: str, full_path: Sequence[str]
) -> MutableMapping[str, Any]:
    existing = cursor.get(part)
    if existing is None:
        next_cursor: MutableMapping[str, Any] = {}
        cursor[part] = next_cursor
        return next_cursor
    if not isinstance(existing, MutableMapping):
        raise ValueError(
            "Cannot override policy path '"
            f"{'/'.join(full_path)}"
            "' because segment '"
            f"{part}"
            "' resolves to a non-mapping value"
        )
    return existing


def _resolve_env_overrides(raw: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """Apply TAXONOMY_POLICY__ environment variable overrides.

    Environment variables prefixed with ``TAXONOMY_POLICY__`` are parsed by
    splitting on double underscores (``__``) to form a lowercased traversal path.
    Intermediate dictionaries are created on demand; if an intermediate value is
    encountered that is not a mapping, a ``ValueError`` is raised to avoid silent
    data loss. Values are JSON-decoded when possible (e.g. ``true`` -> ``True``),
    otherwise they are preserved as raw strings.
    """

    prefix = "TAXONOMY_POLICY__"
    for key, value in os.environ.items():
        if not key.startswith(prefix):
            continue
        parts = [segment.lower() for segment in key[len(prefix) :].split("__") if segment]
        if not parts:
            continue
        cursor: MutableMapping[str, Any] = raw
        for index, part in enumerate(parts[:-1], start=1):
            cursor = _ensure_nested_mapping(cursor, part, parts[: index + 1])
        leaf_parent = cursor
        leaf_key = parts[-1]
        if not isinstance(leaf_parent, MutableMapping):
            raise ValueError(
                f"Cannot override policy path {'/'.join(parts)} because the parent is not a mapping"
            )
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            parsed = value
        leaf_parent[leaf_key] = parsed
    return raw


def _coerce_source_to_dict(source: Mapping[str, Any] | MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    return dict(source)


def load_policies(source: os.PathLike[str] | str | Mapping[str, Any]) -> Policies:
    """Load policies from a mapping or YAML file with environment overrides."""

    if isinstance(source, Mapping):
        raw: MutableMapping[str, Any] = _coerce_source_to_dict(source)
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"Policy file not found: {path}")
        with path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle)
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, MutableMapping):
            raise ValueError(
                f"Policy file '{path}' must contain a mapping at the top level"
            )
        raw = dict(loaded)
    hydrated = _resolve_env_overrides(raw)
    return Policies.model_validate(hydrated)


__all__ = [
    "Policies",
    "load_policies",
    "LevelThresholds",
    "LevelThreshold",
    "FrequencyFilteringPolicy",
    "NearDuplicateDedupPolicy",
    "DeduplicationPolicy",
    "DeduplicationThresholds",
    "RawExtractionPolicy",
    "LevelZeroExcelPolicy",
    "LabelPolicy",
    "MinimalCanonicalForm",
    "SingleTokenVerificationPolicy",
    "ValidationPolicy",
    "RuleValidationSettings",
    "WebValidationSettings",
    "LLMValidationSettings",
    "ValidationAggregationSettings",
    "EvidenceStorageSettings",
    "InstitutionPolicy",
    "WebDomainRules",
    "FirecrawlPolicy",
    "CrawlBudgets",
    "ContentProcessingSettings",
    "CacheSettings",
    "WebObservabilitySettings",
    "LLMDeterminismSettings",
    "ProviderProfileSettings",
    "RegistrySettings",
    "RepairSettings",
    "ObservabilityPolicy",
    "ObservabilitySettings",
    "CostTrackingSettings",
    "DisambiguationPolicy",
    "HierarchyAssemblyPolicy",
    "PromptOptimizationPolicy",
]
