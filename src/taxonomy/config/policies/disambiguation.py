"""Disambiguation policy models."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field


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
