"""Typed models for the taxonomy LLM integration layer."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class TokenUsage(BaseModel):
    """Breakdown of token usage for a single provider call."""

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class PerformanceMetrics(BaseModel):
    """Latency and retry metrics captured for each call."""

    latency_ms: float = Field(default=0.0, ge=0.0)
    retries: int = Field(default=0, ge=0)


class PromptMetadata(BaseModel):
    """Metadata describing a stored prompt template variant."""

    prompt_key: str
    version: str
    description: str
    template_path: str
    schema_path: str
    enforce_order_by: Optional[str] = None
    optimization_history: List[Dict[str, Any]] = Field(default_factory=list)

    @field_validator("template_path", "schema_path")
    @classmethod
    def _ensure_relative(cls, value: str) -> str:
        if value.startswith("/"):
            raise ValueError("Prompt paths must be project-relative, not absolute")
        return value


class LLMOptions(BaseModel):
    """Runtime options that can override policy defaults."""

    temperature: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_output_tokens: Optional[int] = Field(default=None, ge=128)
    seed: Optional[int] = Field(default=None, ge=0)
    stop: Optional[List[str]] = None
    provider_hint: Optional[str] = None
    timeout_seconds: Optional[float] = Field(default=None, ge=0.1)
    retry_attempts: Optional[int] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _ensure_stop_entries(self) -> "LLMOptions":
        if self.stop:
            if any(not isinstance(item, str) or not item for item in self.stop):
                raise ValueError("All stop entries must be non-empty strings")
        return self


class LLMRequest(BaseModel):
    """Structured request given to the LLM client."""

    prompt_key: str
    variables: Dict[str, Any] = Field(default_factory=dict)
    options: LLMOptions = Field(default_factory=LLMOptions)

    @field_validator("prompt_key")
    @classmethod
    def _strip_prompt_key(cls, value: str) -> str:
        if not value:
            raise ValueError("prompt_key must not be empty")
        return value.strip()


class ValidationResult(BaseModel):
    """Outcome of schema validation for a provider response."""

    ok: bool
    parsed: Optional[Any] = None
    error: Optional[str] = None
    repaired: bool = False


class ProviderResponse(BaseModel):
    """Normalized provider response surfaced to the client."""

    content: str
    usage: TokenUsage = Field(default_factory=TokenUsage)
    performance: PerformanceMetrics = Field(default_factory=PerformanceMetrics)
    provider: str = "unknown"
    model: str = "unknown"


class LLMResponse(BaseModel):
    """Structured response returned to business logic callers."""

    ok: bool
    content: Any = None
    raw: Optional[str] = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: float = Field(default=0.0, ge=0.0)
    meta: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None

    @classmethod
    def success(
        cls,
        content: Any,
        raw: str,
        tokens: TokenUsage,
        metadata: Dict[str, Any],
        latency_ms: float,
    ) -> "LLMResponse":
        return cls(
            ok=True,
            content=content,
            raw=raw,
            tokens=tokens,
            latency_ms=latency_ms,
            meta=metadata,
        )

    @classmethod
    def failure(
        cls,
        raw: Optional[str],
        tokens: TokenUsage,
        metadata: Dict[str, Any],
        error: str,
        latency_ms: float,
    ) -> "LLMResponse":
        return cls(
            ok=False,
            content=None,
            raw=raw,
            tokens=tokens,
            latency_ms=latency_ms,
            meta=metadata,
            error=error,
        )


class LLMError(Exception):
    """Base exception for LLM client failures."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.timestamp_ms = int(time.time() * 1000)


class ProviderError(LLMError):
    """Raised when the underlying provider fails."""


class ValidationError(LLMError):
    """Raised when validation repeatedly fails."""


class QuarantineError(LLMError):
    """Raised when an item is quarantined after repeated failures."""


__all__ = [
    "LLMOptions",
    "LLMRequest",
    "LLMResponse",
    "LLMError",
    "ProviderError",
    "ValidationError",
    "QuarantineError",
    "PromptMetadata",
    "TokenUsage",
    "PerformanceMetrics",
    "ProviderResponse",
    "ValidationResult",
]
