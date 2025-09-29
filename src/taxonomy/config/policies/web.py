"""Web mining and crawling policy models."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, field_validator


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

    @field_validator("language_allowlist", mode="before")
    def _normalize_allowlist(value: List[str]) -> List[str]:
        return [code.strip().lower() for code in value if code and code.strip()]


class CacheSettings(BaseModel):
    """File-based cache configuration."""

    cache_directory: str = Field(default=".cache/web", min_length=1)
    ttl_days: int = Field(default=14, ge=0)
    cleanup_interval_hours: int = Field(default=12, ge=1)
    max_size_gb: int | None = Field(default=None)

    @field_validator("max_size_gb", mode="before")
    def _validate_cache_size(value: int | None) -> int | None:
        if value is not None and int(value) <= 0:
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
