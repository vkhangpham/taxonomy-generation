"""Web mining package exports."""

from __future__ import annotations

import os
from pathlib import Path

from taxonomy.config.policies import Policies
from taxonomy.entities.core import PageSnapshot

from .cache import CacheManager
from .client import WebMiner
from .content import ContentProcessor
from .models import (
    BudgetStatus,
    CacheEntry,
    ContentMetadata,
    CrawlConfig,
    CrawlError,
    CrawlResult,
    CrawlSession,
)
from .observability import MetricsCollector
from .robots import RobotsChecker
from .utils import RateLimiter


def build_web_miner(policies: Policies, paths_root: Path) -> WebMiner:
    """Construct a WebMiner instance wired according to policy settings."""

    cache_settings = policies.web.cache
    cache_dir = Path(cache_settings.cache_directory).expanduser()
    if not cache_dir.is_absolute():
        cache_dir = (paths_root / cache_dir).resolve()

    cache = CacheManager(
        cache_dir,
        ttl_days=cache_settings.ttl_days,
        cleanup_interval_hours=cache_settings.cleanup_interval_hours,
        max_cache_size_gb=cache_settings.max_size_gb,
    )

    content_settings = policies.web.content
    content_processor = ContentProcessor(
        language_allowlist=content_settings.language_allowlist,
        language_confidence_threshold=content_settings.language_confidence_threshold,
        min_text_length=content_settings.min_text_length,
        pdf_extraction_enabled=content_settings.pdf_extraction_enabled,
        pdf_size_limit_mb=content_settings.pdf_size_limit_mb,
    )

    firecrawl_settings = policies.web.firecrawl
    robots_checker = RobotsChecker(
        user_agent=firecrawl_settings.user_agent,
        cache_ttl_seconds=policies.web.robots_cache_ttl_hours * 3600,
        request_timeout_seconds=firecrawl_settings.request_timeout_seconds,
    )

    api_key = os.getenv(firecrawl_settings.api_key_env_var)

    return WebMiner(
        cache=cache,
        content_processor=content_processor,
        robots_checker=robots_checker,
        user_agent=firecrawl_settings.user_agent,
        max_concurrency=firecrawl_settings.concurrency,
        rate_limit_per_sec=float(firecrawl_settings.concurrency),
        firecrawl_api_key=api_key,
        firecrawl_endpoint=firecrawl_settings.endpoint_url,
    )

__all__ = [
    "BudgetStatus",
    "CacheEntry",
    "CacheManager",
    "ContentMetadata",
    "ContentProcessor",
    "build_web_miner",
    "CrawlConfig",
    "CrawlError",
    "CrawlResult",
    "CrawlSession",
    "MetricsCollector",
    "PageSnapshot",
    "RateLimiter",
    "RobotsChecker",
    "WebMiner",
]
