"""Extraction and deduplication policy models."""

from __future__ import annotations

import re
from typing import Any, Iterable, List

from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator
from pydantic_core import PydanticUndefined


def _sanitize_string_sequence(value: Any) -> List[str]:
    """Normalise diverse inputs into a trimmed list of strings."""

    if value is None or value is PydanticUndefined:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        items = list(value)
    else:
        items = [value]

    cleaned: List[str] = []
    for item in items:
        if not isinstance(item, str):
            raise TypeError("Expected string entries, but received non-string input")
        stripped = item.strip()
        if stripped:
            cleaned.append(stripped)
    return cleaned


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

    @field_validator("prefix_delimiters", mode="before")
    def _normalize_delimiters(cls, value: Any) -> List[str]:
        return _sanitize_string_sequence(value)


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

    @field_validator("heuristic_suffixes", mode="before")
    def _strip_suffixes(cls, value: Any) -> List[str]:
        return _sanitize_string_sequence(value)


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

    _compiled_boilerplate_patterns: List[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _compiled_section_header_patterns: List[re.Pattern[str]] = PrivateAttr(default_factory=list)

    @field_validator("boilerplate_patterns", "section_header_patterns", mode="before")
    def _strip_blanks(cls, value: Any) -> List[str]:
        return _sanitize_string_sequence(value)

    @model_validator(mode="after")
    def _validate_regex_patterns(self) -> "RawExtractionPolicy":
        compiled_boilerplate: List[re.Pattern[str]] = []
        for index, pattern in enumerate(self.boilerplate_patterns):
            try:
                compiled_boilerplate.append(re.compile(pattern))
            except re.error as exc:  # pragma: no cover - explicit error path
                raise ValueError(
                    f"Invalid regex in boilerplate_patterns[{index}] ({pattern!r}): {exc}"
                ) from exc

        compiled_section_headers: List[re.Pattern[str]] = []
        for index, pattern in enumerate(self.section_header_patterns):
            try:
                compiled_section_headers.append(re.compile(pattern))
            except re.error as exc:  # pragma: no cover - explicit error path
                raise ValueError(
                    f"Invalid regex in section_header_patterns[{index}] ({pattern!r}): {exc}"
                ) from exc

        self._compiled_boilerplate_patterns = compiled_boilerplate
        self._compiled_section_header_patterns = compiled_section_headers
        return self

    @model_validator(mode="after")
    def _validate_length_bounds(self) -> "RawExtractionPolicy":
        if self.max_chars < self.min_chars:
            raise ValueError("max_chars must not be smaller than min_chars")
        return self


class LevelZeroExcelPolicy(BaseModel):
    """Specialised configuration for the level 0 Excel handler."""

    excel_file: str = Field(..., description="Path to the Faculty Extraction Report")
    sheets_to_process: List[str] = Field(default_factory=list)
    top_n_institutions: int = Field(default=25, ge=1)
    random_seed: int = Field(default=20230927)
