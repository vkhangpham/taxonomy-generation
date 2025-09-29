"""Validation-oriented policy models."""

from __future__ import annotations

from typing import Dict, List

from pydantic import BaseModel, Field, field_validator


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

    @field_validator("max_tokens_per_level", mode="before")
    def _validate_token_limits(value: Dict[int, int]) -> Dict[int, int]:
        normalized: Dict[int, int] = {}
        for level, limit in value.items():
            if int(limit) <= 0:
                raise ValueError("max_tokens_per_level must contain positive integers")
            normalized[int(level)] = int(limit)
        return normalized

    @field_validator("allowlist", mode="before")
    def _normalize_allowlist(value: List[str]) -> List[str]:
        return [token.strip().lower() for token in value if token and token.strip()]

    @field_validator("forbidden_punctuation", mode="before")
    def _normalize_punctuation(value: List[str]) -> List[str]:
        return [mark.strip() for mark in value if mark and mark.strip()]

    @field_validator("venue_names", mode="before")
    def _normalize_venue_names(value: List[str]) -> List[str]:
        return [token.strip().lower() for token in value if token and token.strip()]


class RuleValidationSettings(BaseModel):
    """Configuration for deterministic validation rules."""

    forbidden_patterns: List[str] = Field(default_factory=list)
    required_vocabularies: Dict[int, List[str]] = Field(default_factory=dict)
    venue_patterns: List[str] = Field(default_factory=list)
    structural_checks_enabled: bool = Field(default=True)
    venue_detection_hard: bool = Field(default=False)

    @field_validator("forbidden_patterns", "venue_patterns", mode="before")
    def _strip_patterns(value: List[str]) -> List[str]:
        return [pattern.strip() for pattern in value if pattern and pattern.strip()]

    @field_validator("required_vocabularies", mode="before")
    def _normalize_vocab_keys(value: Dict[int | str, List[str]]) -> Dict[int, List[str]]:
        normalized: Dict[int, List[str]] = {}
        for key, terms in value.items():
            level = int(key)
            normalized[level] = [term.strip().lower() for term in terms if term and term.strip()]
        return normalized


class WebValidationSettings(BaseModel):
    """Configuration for evidence-based validation using web snapshots."""

    authoritative_domains: List[str] = Field(default_factory=list)
    snippet_max_length: int = Field(default=200, ge=40, le=2000)
    min_snippet_matches: int = Field(default=1, ge=0)
    evidence_timeout_seconds: float = Field(default=10.0, ge=0.1)

    @field_validator("authoritative_domains", mode="before")
    def _normalize_domains(value: List[str]) -> List[str]:
        return [domain.strip().lower() for domain in value if domain and domain.strip()]


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
