"""Core domain entities used throughout the taxonomy pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from math import log
from typing import Dict, List, Sequence
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class Provenance(BaseModel):
    """Describes the origin of a source snippet."""

    institution: str = Field(..., min_length=1, description="Institution that published the source")
    url: str | None = Field(
        default=None,
        description="URL or URI where the source was retrieved, if applicable.",
    )
    section: str | None = Field(
        default=None,
        description="Specific section within the source (e.g., page title, selector).",
    )
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp indicating when the source was fetched.",
    )

    @field_validator("url")
    @classmethod
    def _validate_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.startswith(("http://", "https://", "file://")):
            return value
        raise ValueError("provenance.url must be an absolute URL or file URI")


class SourceMeta(BaseModel):
    """Metadata collected for a source record."""

    language: str = Field(default="en", min_length=2, description="BCP-47 language tag")
    charset: str = Field(default="utf-8", min_length=3, description="Character set used for decoding")
    hints: Dict[str, str] = Field(
        default_factory=dict,
        description="Implementation-specific hints and annotations for downstream stages.",
    )

    @field_validator("language")
    @classmethod
    def _normalize_language(cls, value: str) -> str:
        code = value.strip().lower()
        if len(code) < 2:
            raise ValueError("language must be at least two characters long")
        return code

    @field_validator("charset")
    @classmethod
    def _normalize_charset(cls, value: str) -> str:
        return value.strip().lower()


class SourceRecord(BaseModel):
    """Raw text snippet paired with provenance and metadata."""

    text: str = Field(..., min_length=1)
    provenance: Provenance
    meta: SourceMeta = Field(default_factory=SourceMeta)

    @field_validator("text")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("text must contain non-whitespace characters")
        return cleaned


class SupportStats(BaseModel):
    """Aggregated evidence counts for candidates and concepts."""

    records: int = Field(
        default=0,
        ge=0,
        description="Number of unique source records supporting the entity.",
    )
    institutions: int = Field(
        default=0,
        ge=0,
        description="Number of unique institutions represented in the support.",
    )
    count: int = Field(
        default=0,
        ge=0,
        description="Total frequency count across all supporting records.",
    )

    def weight(self) -> float:
        """Calculate the support weight using the policy formula."""

        return 1.0 * self.institutions + 0.3 * log(1 + self.records)


class Candidate(BaseModel):
    """Intermediate label proposal emitted by S0-S1 stages."""

    level: int = Field(..., ge=0, le=3, description="Hierarchy depth the candidate belongs to")
    label: str = Field(..., min_length=1, description="Label as extracted from the source")
    normalized: str = Field(..., min_length=1, description="Canonicalized representation of the label")
    parents: List[str] = Field(
        default_factory=list,
        description="Anchors or IDs of candidate parents that contextualize this candidate.",
    )
    aliases: List[str] = Field(
        default_factory=list,
        description="Alternative strings observed for the candidate label.",
    )
    support: SupportStats = Field(default_factory=SupportStats)

    @field_validator("label", "normalized")
    @classmethod
    def _trim_label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("labels must contain non-whitespace characters")
        return cleaned

    @model_validator(mode="after")
    def _validate_parents(self) -> "Candidate":
        if self.level == 0 and self.parents:
            raise ValueError("level 0 candidates must not declare parents")
        if self.level > 0 and not self.parents:
            raise ValueError("candidates above level 0 must provide at least one parent anchor")
        return self


class Rationale(BaseModel):
    """Decision trail captured during validation."""

    passed_gates: Dict[str, bool] = Field(default_factory=dict)
    reasons: List[str] = Field(default_factory=list)
    thresholds: Dict[str, float] = Field(default_factory=dict)


class Concept(BaseModel):
    """Stable taxonomy node that survived promotion and validation."""

    id: str = Field(..., min_length=1, description="Stable concept identifier")
    level: int = Field(..., ge=0, le=3)
    canonical_label: str = Field(..., min_length=1)
    parents: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    support: SupportStats = Field(default_factory=SupportStats)
    rationale: Rationale = Field(default_factory=Rationale)

    @field_validator("canonical_label")
    @classmethod
    def _trim_canonical_label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("canonical_label must contain non-whitespace characters")
        return cleaned

    def validate_hierarchy(self, parent_concepts: Sequence["Concept"] | None = None) -> None:
        """Validate hierarchy invariants.

        Args:
            parent_concepts: Optional iterable of parent concepts to validate structural invariants.
        """

        if self.level == 0 and self.parents:
            raise ValueError("Level 0 concepts must not declare explicit parents")
        if self.level > 0 and not self.parents:
            raise ValueError("Concepts above level 0 must reference at least one parent")
        if parent_concepts is None:
            return
        parent_levels = {concept.level for concept in parent_concepts}
        if parent_levels and min(parent_levels) >= self.level:
            raise ValueError("Parent concepts must be at a shallower hierarchy level than the child")


class FindingMode(str, Enum):
    """Modes that can yield validation findings."""

    RULE = "rule"
    WEB = "web"
    LLM = "llm"


class ValidationFinding(BaseModel):
    """Outcome of a validation check for a concept."""

    concept_id: str = Field(..., min_length=1)
    mode: FindingMode
    passed: bool
    detail: str = Field(..., min_length=1)
    evidence: Dict[str, str] | None = Field(default=None)

    @field_validator("detail")
    @classmethod
    def _trim_detail(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("detail must not be empty")
        return cleaned


class MergeOp(BaseModel):
    """Represents the consolidation of duplicate concepts."""

    operation_id: str = Field(default_factory=lambda: str(uuid4()))
    winners: List[str] = Field(..., min_length=1)
    losers: List[str] = Field(..., min_length=1)
    rule: str = Field(..., min_length=1)
    evidence: Dict[str, str] | None = Field(default=None)
    performed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _validate_op(self) -> "MergeOp":
        if not self.winners or not self.losers:
            raise ValueError("merge operations require at least one winner and one loser")
        if set(self.winners) & set(self.losers):
            raise ValueError("concept IDs cannot appear in both winners and losers")
        return self


class SplitOp(BaseModel):
    """Represents the division of an over-loaded concept into multiple children."""

    operation_id: str = Field(default_factory=lambda: str(uuid4()))
    source_id: str = Field(..., min_length=1)
    new_ids: List[str] = Field(..., min_length=1)
    rule: str = Field(..., min_length=1)
    evidence: Dict[str, str] | None = Field(default=None)
    performed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _validate_split(self) -> "SplitOp":
        if self.source_id in self.new_ids:
            raise ValueError("split operations must generate new IDs distinct from the source")
        if len(set(self.new_ids)) != len(self.new_ids):
            raise ValueError("split operations must generate unique new IDs")
        return self


__all__ = [
    "Provenance",
    "SourceMeta",
    "SourceRecord",
    "SupportStats",
    "Candidate",
    "Rationale",
    "Concept",
    "FindingMode",
    "ValidationFinding",
    "MergeOp",
    "SplitOp",
]
