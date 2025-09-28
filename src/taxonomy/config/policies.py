"""Policy configuration primitives derived from docs/policies.md."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

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


class NearDuplicateDedupPolicy(BaseModel):
    """Configuration for collapsing near-identical records per institution."""

    enabled: bool = Field(default=True)
    prefix_delimiters: List[str] = Field(
        default_factory=lambda: ["::", "#", "@"],
        description="Delimiters indicating suffixes to strip when deduplicating records.",
    )
    strip_numeric_suffix: bool = Field(
        default=True,
        description="Strip trailing numeric or version suffixes when computing dedup keys.",
    )
    min_prefix_length: int = Field(
        default=6,
        ge=1,
        description="Minimum prefix length required before a delimiter to be considered meaningful.",
    )

    @field_validator("prefix_delimiters")
    @classmethod
    def _normalize_delimiters(cls, value: List[str]) -> List[str]:
        return [delimiter.strip() for delimiter in value if delimiter.strip()]


class FrequencyFilteringPolicy(BaseModel):
    """Policy controls specific to S2 frequency aggregation."""

    unknown_institution_placeholder: str = Field(
        default="placeholder::unknown",
        min_length=1,
        description="Placeholder identifier used when evidence lacks institution metadata.",
    )
    near_duplicate: NearDuplicateDedupPolicy = Field(
        default_factory=NearDuplicateDedupPolicy,
        description="Settings controlling near-duplicate collapsing of records.",
    )


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
    include_ambiguous_acronyms: bool = Field(
        default=False,
        description="Whether ambiguous acronym expansions (e.g. AI) should be emitted.",
    )
    parent_similarity_cutoff: float = Field(
        default=0.86,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for fuzzy parent matching.",
    )


class SingleTokenVerificationPolicy(BaseModel):
    """Deterministic rules for single-token verification in S3."""

    max_tokens_per_level: Dict[int, int] = Field(
        default_factory=lambda: {0: 2, 1: 2, 2: 3, 3: 2}
    )
    forbidden_punctuation: List[str] = Field(
        default_factory=lambda: ["-", "_", ".", "/", ":"]
    )
    allowlist: List[str] = Field(
        default_factory=lambda: [
            "computer vision",
            "machine learning",
            "natural language processing",
            "artificial intelligence",
            "data science",
        ]
    )
    venue_names: List[str] = Field(
        default_factory=lambda: [
            "neurips",
            "neural information processing systems",
            "icml",
            "international conference on machine learning",
            "cvpr",
            "computer vision and pattern recognition",
            "acl",
            "association for computational linguistics",
            "emnlp",
            "kdd",
            "siggraph",
            "isca",
        ]
    )
    venue_names_forbidden: bool = Field(default=True)
    hyphenated_compounds_allowed: bool = Field(default=False)
    prefer_rule_over_llm: bool = Field(default=True)

    @field_validator("max_tokens_per_level")
    @classmethod
    def _validate_token_limits(cls, value: Dict[int, int]) -> Dict[int, int]:
        normalized = {}
        for level, limit in value.items():
            if limit <= 0:
                raise ValueError("max_tokens_per_level values must be positive")
            normalized[int(level)] = int(limit)
        return normalized

    @field_validator("allowlist")
    @classmethod
    def _normalize_allowlist(cls, value: List[str]) -> List[str]:
        return [token.strip().lower() for token in value if token.strip()]

    @field_validator("forbidden_punctuation")
    @classmethod
    def _normalize_punctuation(cls, value: List[str]) -> List[str]:
        return [mark.strip() for mark in value if mark.strip()]

    @field_validator("venue_names")
    @classmethod
    def _normalize_venue_names(cls, value: List[str]) -> List[str]:
        return [token.strip().lower() for token in value if token.strip()]


class RuleValidationSettings(BaseModel):
    """Configuration for deterministic validation rules."""

    forbidden_patterns: List[str] = Field(default_factory=list)
    required_vocabularies: Dict[int, List[str]] = Field(default_factory=dict)
    venue_patterns: List[str] = Field(default_factory=list)
    structural_checks_enabled: bool = Field(default=True)
    venue_detection_hard: bool = Field(default=False)

    @field_validator("forbidden_patterns", "venue_patterns")
    @classmethod
    def _strip_patterns(cls, value: List[str]) -> List[str]:
        return [pattern.strip() for pattern in value if pattern.strip()]

    @field_validator("required_vocabularies")
    @classmethod
    def _normalize_vocab_keys(cls, value: Dict[int | str, List[str]]) -> Dict[int, List[str]]:
        normalized: Dict[int, List[str]] = {}
        for key, terms in value.items():
            level = int(key)
            normalized[level] = [term.strip().lower() for term in terms if term.strip()]
        return normalized


class WebValidationSettings(BaseModel):
    """Configuration for evidence-based validation using web snapshots."""

    authoritative_domains: List[str] = Field(default_factory=list)
    snippet_max_length: int = Field(default=200, ge=40, le=2000)
    min_snippet_matches: int = Field(default=1, ge=0)
    evidence_timeout_seconds: float = Field(default=10.0, ge=0.1)

    @field_validator("authoritative_domains")
    @classmethod
    def _normalize_domains(cls, value: List[str]) -> List[str]:
        return [domain.strip().lower() for domain in value if domain.strip()]


class LLMValidationSettings(BaseModel):
    """Configuration for entailment checks performed by the LLM."""

    entailment_enabled: bool = Field(default=True)
    max_evidence_tokens: int = Field(default=1000, ge=128)
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)


class ValidationAggregationSettings(BaseModel):
    """Weighted aggregation of validation signals."""

    rule_weight: float = Field(default=1.0, ge=0.0)
    web_weight: float = Field(default=0.7, ge=0.0)
    llm_weight: float = Field(default=0.4, ge=0.0)
    hard_rule_failure_blocks: bool = Field(default=True)
    tie_break_conservative: bool = Field(default=True)
    tie_break_min_strength: float | None = Field(default=None, ge=0.0)


class EvidenceStorageSettings(BaseModel):
    """Controls for evidence retention and sampling."""

    max_snippets_per_concept: int = Field(default=3, ge=0)
    store_evidence_urls: bool = Field(default=True)
    evidence_sampling_rate: float = Field(default=1.0, ge=0.0, le=1.0)


class ValidationPolicy(BaseModel):
    """Aggregate configuration for the validation pipeline."""

    rules: RuleValidationSettings = Field(default_factory=RuleValidationSettings)
    web: WebValidationSettings = Field(default_factory=WebValidationSettings)
    llm: LLMValidationSettings = Field(default_factory=LLMValidationSettings)
    aggregation: ValidationAggregationSettings = Field(
        default_factory=ValidationAggregationSettings
    )
    evidence: EvidenceStorageSettings = Field(
        default_factory=EvidenceStorageSettings
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
    api_key_env_var: str = Field(default="FIRECRAWL_API_KEY", min_length=1)
    endpoint_url: str | None = Field(default=None)
    request_timeout_seconds: float = Field(default=20.0, ge=1.0)
    retry_attempts: int = Field(default=3, ge=0)
    user_agent: str = Field(default="TaxonomyBot/1.0", min_length=3)


class CrawlBudgets(BaseModel):
    """Institution-level crawling budgets."""

    max_pages: int = Field(default=300, ge=1)
    max_depth: int = Field(default=3, ge=0)
    max_time_minutes: int = Field(default=30, ge=0)
    max_content_size_mb: int = Field(default=5, ge=0)


class ContentProcessingSettings(BaseModel):
    """Controls for text extraction and quality filters."""

    language_allowlist: List[str] = Field(default_factory=list)
    language_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    min_text_length: int = Field(default=120, ge=0)
    pdf_extraction_enabled: bool = Field(default=True)
    pdf_size_limit_mb: int = Field(default=5, ge=0)

    @field_validator("language_allowlist")
    @classmethod
    def _normalize_allowlist(cls, value: List[str]) -> List[str]:
        return [code.strip().lower() for code in value if code.strip()]


class CacheSettings(BaseModel):
    """File-based cache configuration."""

    cache_directory: str = Field(default=".cache/web", min_length=1)
    ttl_days: int = Field(default=14, ge=0)
    cleanup_interval_hours: int = Field(default=12, ge=1)
    max_size_gb: int | None = Field(default=None)

    @field_validator("max_size_gb")
    @classmethod
    def _validate_cache_size(cls, value: int | None) -> int | None:
        if value is not None and value <= 0:
            raise ValueError("max_size_gb must be positive when provided")
        return value


class WebObservabilitySettings(BaseModel):
    """Metrics collection configuration for web mining."""

    metrics_enabled: bool = Field(default=True)
    sampling_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    example_snapshot_count: int = Field(default=5, ge=0)


class WebDomainRules(BaseModel):
    """Constraints for web crawling and scraping."""

    allowed_domains: List[str] = Field(default_factory=list)
    disallowed_paths: List[str] = Field(default_factory=list)
    robots_txt_compliance: bool = Field(default=True)
    dynamic_content: bool = Field(default=False)
    pdf_processing_limit: int = Field(default=500, ge=0)
    ttl_cache_days: int = Field(default=14, ge=0)
    firecrawl: FirecrawlPolicy = Field(default_factory=FirecrawlPolicy)
    include_patterns: List[str] = Field(default_factory=list)
    robots_cache_ttl_hours: int = Field(default=12, ge=1)
    sitemap_discovery: bool = Field(default=True)
    respect_crawl_delay: bool = Field(default=True)
    budgets: CrawlBudgets = Field(default_factory=CrawlBudgets)
    content: ContentProcessingSettings = Field(default_factory=ContentProcessingSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    observability: WebObservabilitySettings = Field(default_factory=WebObservabilitySettings)


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


class DisambiguationPolicy(BaseModel):
    """Disambiguation-specific policy controls."""

    min_parent_divergence: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum divergence score between parents required to treat a collision as ambiguous.",
    )
    min_context_overlap_threshold: float = Field(
        default=0.2,
        ge=0.0,
        le=1.0,
        description="Maximum allowed token overlap between context groups before deeming them indistinguishable.",
    )
    require_multiple_parents: bool = Field(
        default=True,
        description="Require at least two distinct parent lineages before attempting disambiguation.",
    )
    max_contexts_per_parent: int = Field(
        default=5,
        ge=1,
        description="Maximum number of context windows retained per parent during analysis.",
    )
    context_window_size: int = Field(
        default=100,
        ge=1,
        description="Number of tokens to capture around each mention when constructing context windows.",
    )
    min_token_frequency: int = Field(
        default=2,
        ge=1,
        description="Minimum token frequency required for inclusion in co-occurrence statistics.",
    )
    llm_enabled: bool = Field(
        default=True,
        description="Enable LLM-backed separability checks before performing splits.",
    )
    max_contexts_for_prompt: int = Field(
        default=10,
        ge=1,
        description="Maximum number of context snippets forwarded to the LLM prompt.",
    )
    gloss_max_words: int = Field(
        default=20,
        ge=1,
        description="Maximum length of gloss strings returned by the LLM per sense.",
    )
    min_evidence_strength: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Minimum confidence required before accepting a split recommendation.",
    )
    defer_ambiguous_threshold: float = Field(
        default=0.4,
        ge=0.0,
        le=1.0,
        description="Confidence threshold below which concepts should be deferred for manual review.",
    )
    allow_multi_parent_exceptions: bool = Field(
        default=False,
        description="Allow disambiguation for same-parent collisions when additional evidence suggests multiple senses.",
    )
    sample_splits_count: int = Field(
        default=5,
        ge=0,
        description="Number of split decisions to sample for detailed audit logging.",
    )
    detailed_logging: bool = Field(
        default=False,
        description="Emit verbose logging for disambiguation scoring and split rationale when True.",
    )


class DeduplicationThresholds(BaseModel):
    """Similarity thresholds for deduplication per level band."""

    l0_l1: float = Field(default=0.93, ge=0.0, le=1.0)
    l2_l3: float = Field(default=0.90, ge=0.0, le=1.0)


class DeduplicationPolicy(BaseModel):
    """Policy governing merge behaviour for similar concepts."""

    thresholds: DeduplicationThresholds
    merge_policy: str = Field(default="conservative")
    prefix_length: int = Field(
        default=6,
        ge=1,
        description="Number of leading characters used for prefix blocking.",
    )
    phonetic_enabled: bool = Field(
        default=True,
        description="Whether Double Metaphone blocking should be applied.",
    )
    phonetic_probe_threshold: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        description="Minimum score required from the phonetic probe before full scoring.",
    )
    acronym_blocking_enabled: bool = Field(
        default=True,
        description="Whether acronym-based blocking should be applied.",
    )
    max_block_size: int = Field(
        default=1000,
        ge=1,
        description="Maximum allowed size of a block before it is split or truncated.",
    )
    jaro_winkler_weight: float = Field(
        default=1.0,
        ge=0.0,
        description="Weight applied to the Jaro-Winkler similarity component.",
    )
    jaccard_weight: float = Field(
        default=1.0,
        ge=0.0,
        description="Weight applied to the token Jaccard similarity component.",
    )
    abbrev_score_weight: float = Field(
        default=1.2,
        ge=0.0,
        description="Weight applied to the acronym/expansion similarity component.",
    )
    heuristic_suffixes: List[str] = Field(
        default_factory=lambda: ["systems", "theory", "engineering"],
        description="Suffix tokens used by the prefix/suffix heuristic hint.",
    )
    min_similarity_threshold: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score required to create a graph edge.",
    )
    parent_context_strict: bool = Field(
        default=True,
        description="Require parent compatibility checks before allowing merges.",
    )
    cross_parent_merge_allowed: bool = Field(
        default=False,
        description="Allow merges across different parents when True.",
    )
    max_comparisons_per_block: int = Field(
        default=10_000,
        ge=1,
        description="Safety limit on the number of pairwise comparisons per block.",
    )
    enable_early_stopping: bool = Field(
        default=True,
        description="Stop evaluating similarity components once the threshold is reached.",
    )
    sample_merge_count: int = Field(
        default=10,
        ge=0,
        description="Number of merge decisions to sample for detailed auditing.",
    )
    detailed_logging: bool = Field(
        default=False,
        description="Emit verbose logs for similarity and merge decisions when True.",
    )


class HierarchyAssemblyPolicy(BaseModel):
    """Configuration controlling hierarchy graph assembly invariants."""

    enforce_acyclicity: bool = Field(default=True)
    enforce_unique_paths: bool = Field(default=True)
    allow_multi_parent_exceptions: List[str] = Field(default_factory=list)
    orphan_strategy: Literal["quarantine", "attach_placeholder", "drop"] = Field(
        default="quarantine",
        description="Strategy for handling concepts missing valid parent references.",
    )
    placeholder_parent_prefix: str = Field(
        default="placeholder::",
        min_length=1,
        description="Prefix applied when synthesising placeholder parent concepts.",
    )
    strict_level_enforcement: bool = Field(default=True)
    allow_level_shortcuts: bool = Field(default=False)
    max_graph_size: int = Field(default=100_000, ge=1)
    cycle_detection_method: Literal["topological_sort", "dfs"] = Field(
        default="topological_sort",
        description="Algorithm to use when checking for cycles in the hierarchy graph.",
    )
    include_graph_stats: bool = Field(default=True)
    include_invariant_proofs: bool = Field(default=True)

    @field_validator("allow_multi_parent_exceptions")
    @classmethod
    def _normalize_exceptions(cls, value: List[str]) -> List[str]:
        return [concept_id.strip() for concept_id in value if concept_id.strip()]


class RawExtractionPolicy(BaseModel):
    """Configuration for S0 raw extraction from mined snapshots."""

    segment_on_headers: bool = Field(default=True)
    segment_on_lists: bool = Field(default=True)
    segment_on_tables: bool = Field(default=True)
    preserve_list_structure: bool = Field(default=True)
    min_chars: int = Field(default=12, ge=0)
    max_chars: int = Field(default=2000, ge=1)
    target_language: str = Field(default="en", min_length=1)
    language_confidence_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    require_language_confidence: bool = Field(
        default=True,
        description="Require language confidence metadata unless target_language is 'any'.",
    )
    intra_page_dedup_enabled: bool = Field(default=True)
    similarity_threshold: float = Field(default=0.95, ge=0.0, le=1.0)
    similarity_method: str = Field(default="jaccard_shingles", min_length=1)
    remove_boilerplate: bool = Field(default=True)
    verbose_text_logging: bool = Field(
        default=False,
        description="Emit truncated text payloads in debug logs when True.",
    )
    boilerplate_patterns: List[str] = Field(
        default_factory=lambda: [
            "© \\d{4}",
            "all rights reserved",
            "privacy policy",
            "terms of use",
            "contact us",
            "home \\| about \\| contact",
        ]
    )
    detect_sections: bool = Field(default=True)
    section_header_patterns: List[str] = Field(
        default_factory=lambda: [
            "^[A-Z][A-Z\\s]{2,50}:?$",
            "^#{1,6}\\s+.+$",
            "^\\d+\\.\\s+[A-Z].+$",
        ]
    )
    preserve_document_order: bool = Field(default=True)

    @field_validator("boilerplate_patterns", "section_header_patterns")
    @classmethod
    def _strip_blanks(cls, value: List[str]) -> List[str]:
        return [pattern for pattern in (entry.strip() for entry in value) if pattern]

    @model_validator(mode="after")
    def _validate_length_bounds(self) -> "RawExtractionPolicy":
        if self.max_chars and self.max_chars < self.min_chars:
            raise ValueError("max_chars must be greater than or equal to min_chars")
        return self


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
    hierarchy_assembly: HierarchyAssemblyPolicy = Field(
        default_factory=HierarchyAssemblyPolicy
    )

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
    "FrequencyFilteringPolicy",
    "NearDuplicateDedupPolicy",
    "LabelPolicy",
    "SingleTokenVerificationPolicy",
    "ValidationPolicy",
    "RuleValidationSettings",
    "WebValidationSettings",
    "LLMValidationSettings",
    "ValidationAggregationSettings",
    "EvidenceStorageSettings",
    "InstitutionPolicy",
    "WebDomainRules",
    "LLMDeterminismSettings",
    "DisambiguationPolicy",
    "DeduplicationPolicy",
    "HierarchyAssemblyPolicy",
    "RawExtractionPolicy",
    "LevelZeroExcelPolicy",
]
