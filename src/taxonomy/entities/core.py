"""Core domain entities used throughout the taxonomy pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from math import log
from typing import Any, Dict, List, Mapping, Sequence
from urllib.parse import urlparse, urlunparse
import hashlib
import re
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


def _normalize_url(url: str) -> str:
    """Normalize and validate URLs for canonical storage."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL must use http or https scheme")
    if not parsed.netloc:
        raise ValueError("URL must include a hostname")

    netloc = parsed.netloc.lower()
    scheme = parsed.scheme.lower()
    path = parsed.path or "/"
    normalized = parsed._replace(scheme=scheme, netloc=netloc, fragment="", path=path)
    return urlunparse(normalized)


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
    """Aggregated evidence counts for candidates and concepts.

    The policy definitions in ``config/default.yaml`` refer to ``inst_count`` and
    ``src_count``. ``inst_count`` maps to :attr:`institutions` while ``src_count``
    corresponds to :attr:`count`, the total frequency across supporting records.
    """

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
        """Calculate the support weight using the default policy formula.

        ``inst_count`` is sourced from :attr:`institutions` and ``src_count`` is
        sourced from :attr:`count`, mirroring the thresholds in
        ``docs/policies.md``.
        """

        return 1.0 * self.institutions + 0.3 * log(1 + self.count)


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
        if (
            self.level > 0
            and not self.parents
            and self.support.institutions != 1
        ):
            raise ValueError(
                "aggregated non-root candidates must declare at least one parent"
            )
        return self


class Rationale(BaseModel):
    """Decision trail captured during validation."""

    passed_gates: Dict[str, bool] = Field(default_factory=dict)
    reasons: List[str] = Field(default_factory=list)
    thresholds: Dict[str, float] = Field(default_factory=dict)

    @field_validator("passed_gates", mode="before")
    @classmethod
    def _normalize_passed_gates(cls, value: Mapping[str, Any] | None) -> Dict[str, bool]:
        if value is None:
            return {}
        if isinstance(value, dict):
            items = value.items()
        else:
            try:
                items = dict(value).items()
            except Exception as exc:  # pragma: no cover - defensive guard
                raise ValueError("passed_gates must be a mapping of gate -> bool") from exc

        normalized: Dict[str, bool] = {}
        for raw_gate, raw_passed in items:
            if not isinstance(raw_gate, str):
                raise ValueError("passed_gates keys must be non-empty strings")
            gate = raw_gate.strip()
            if not gate:
                raise ValueError("passed_gates keys must be non-empty strings")
            if not isinstance(raw_passed, bool):
                raise ValueError("passed_gates values must be booleans")
            normalized[gate] = raw_passed
        return normalized

    def set_gate(self, gate: str, passed: bool | None) -> None:
        """Update the recorded outcome for a validation gate."""

        if not isinstance(gate, str):
            raise ValueError("gate must be a non-empty string")
        name = gate.strip()
        if not name:
            raise ValueError("gate must be a non-empty string")

        if passed is None:
            self.passed_gates.pop(name, None)
            return
        if not isinstance(passed, bool):
            raise ValueError("passed must be a bool or None")
        self.passed_gates[name] = passed

    def overall(self) -> bool | None:
        """Aggregate the recorded gate outcomes into a single decision."""

        return None if not self.passed_gates else all(self.passed_gates.values())


class Concept(BaseModel):
    """Stable taxonomy node that survived promotion and validation."""

    id: str = Field(..., min_length=1, description="Stable concept identifier")
    level: int = Field(..., ge=0, le=3)
    canonical_label: str = Field(..., min_length=1)
    parents: List[str] = Field(default_factory=list)
    aliases: List[str] = Field(default_factory=list)
    support: SupportStats = Field(default_factory=SupportStats)
    rationale: Rationale = Field(default_factory=Rationale)
    validation_passed: bool | None = Field(
        default=None,
        description="Overall validation decision aggregated across all validators.",
    )
    validation_metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Validator-specific metadata including evidence counts and scores.",
    )

    @field_validator("canonical_label")
    @classmethod
    def _trim_canonical_label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("canonical_label must contain non-whitespace characters")
        return cleaned

    def set_validation_passed(self, passed: bool | None, *, gate: str = "validation") -> None:
        """Record the outcome for a validation gate and update the aggregate result.

        ``passed`` must be ``True`` or ``False`` to record the outcome of ``gate``
        and ``None`` to remove a previously recorded value. After each update the
        concept's ``validation_passed`` flag becomes ``all`` recorded gate values
        when any remain, otherwise it resets to ``None``.

        Args:
            passed: Gate outcome. ``None`` clears the stored result for ``gate``.
            gate: Name of the validator gate whose result is being recorded.

        Raises:
            ValueError: If ``gate`` is missing, empty, or ``self.rationale`` is unset.
        """

        if self.rationale is None:
            raise ValueError(
                "Concept.rationale must be initialized before updating validation results"
            )

        self.rationale.set_gate(gate, passed)
        self.validation_passed = self.rationale.overall()

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
    evidence: Dict[str, Any] | None = Field(default=None)

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
    evidence: Dict[str, Any] | None = Field(default=None)
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
    evidence: Dict[str, Any] | None = Field(default=None)
    performed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def _validate_split(self) -> "SplitOp":
        if self.source_id in self.new_ids:
            raise ValueError("split operations must generate new IDs distinct from the source")
        if len(set(self.new_ids)) != len(self.new_ids):
            raise ValueError("split operations must generate unique new IDs")
        return self


class PageSnapshotMeta(BaseModel):
    """Supplemental metadata recorded for a fetched page snapshot."""

    rendered: bool = Field(default=False, description="Whether headless rendering was required")
    robots_blocked: bool = Field(default=False, description="Whether the fetch was blocked by robots.txt")
    alias_urls: List[str] = Field(
        default_factory=list,
        description="Canonicalized URLs that share the same content checksum.",
    )
    redirects: List[str] = Field(
        default_factory=list,
        description="Ordered list of redirect URLs that occurred before the final fetch.",
    )
    source: str = Field(
        default="crawl",
        min_length=1,
        description="Origin of the snapshot capture (e.g. crawl, cache, manual).",
    )

    @field_validator("redirects")
    @classmethod
    def _validate_redirects(cls, value: List[str]) -> List[str]:
        return [_normalize_url(item) for item in value]

    @field_validator("alias_urls")
    @classmethod
    def _validate_aliases(cls, value: List[str]) -> List[str]:
        normalized = [_normalize_url(item) for item in value]
        return sorted(dict.fromkeys(normalized))

    @field_validator("source")
    @classmethod
    def _normalize_source(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("meta.source must not be empty")
        return normalized


class PageSnapshot(BaseModel):
    """Canonical representation of a fetched institutional web page."""

    institution: str = Field(..., min_length=1, description="Institution identifier associated with the page")
    url: str = Field(..., description="Landing URL that was requested for the snapshot")
    canonical_url: str | None = Field(
        default=None,
        description="Normalized canonical URL for the page, defaults to the landing URL",
    )
    fetched_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of when the page was fetched",
    )
    http_status: int = Field(..., ge=100, le=599, description="HTTP status code returned by the fetch")
    content_type: str = Field(..., min_length=3, description="MIME content type reported by the server")
    html: str | None = Field(default=None, description="Raw HTML payload when available")
    text: str = Field(..., min_length=1, description="Extracted and normalized textual content")
    lang: str = Field(default="und", min_length=2, description="Detected language code (BCP-47)")
    checksum: str = Field(..., min_length=64, max_length=64, description="SHA-256 checksum of normalized text")
    meta: PageSnapshotMeta = Field(default_factory=PageSnapshotMeta)

    @staticmethod
    def compute_checksum(text: str) -> str:
        """Return the SHA-256 checksum for the normalized text."""

        normalized = " ".join(text.split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    @field_validator("institution")
    @classmethod
    def _normalize_institution(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("institution must contain non-whitespace characters")
        return normalized

    @field_validator("url")
    @classmethod
    def _normalize_url_field(cls, value: str) -> str:
        return _normalize_url(value)

    @field_validator("canonical_url")
    @classmethod
    def _normalize_canonical_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalize_url(value)

    @field_validator("content_type")
    @classmethod
    def _normalize_content_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if "/" not in normalized:
            raise ValueError("content_type must be a valid MIME type")
        return normalized

    @field_validator("lang")
    @classmethod
    def _normalize_lang(cls, value: str) -> str:
        code = value.strip().lower()
        if len(code) < 2 or len(code) > 35 or not re.match(r"^[a-z0-9-]+$", code):
            raise ValueError("lang must be a valid BCP-47 identifier")
        return code

    @field_validator("checksum")
    @classmethod
    def _validate_checksum(cls, value: str) -> str:
        checksum = value.strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", checksum):
            raise ValueError("checksum must be a 64-character hexadecimal SHA-256 digest")
        return checksum

    @field_validator("text")
    @classmethod
    def _validate_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("text must contain non-whitespace characters")
        return cleaned

    @model_validator(mode="after")
    def _finalize(self) -> "PageSnapshot":
        if self.canonical_url is None:
            self.canonical_url = self.url
        expected_checksum = self.compute_checksum(self.text)
        if self.checksum != expected_checksum:
            raise ValueError("checksum does not match normalized text content")
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
    "PageSnapshotMeta",
    "PageSnapshot",
]
