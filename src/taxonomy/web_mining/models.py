"""Pydantic models supporting the web mining subsystem."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Callable, Deque, Dict, Iterable, List, Optional, Sequence

from pydantic import BaseModel, Field, PrivateAttr, field_validator, model_validator

from taxonomy.entities.core import PageSnapshot


class QualityMetrics(BaseModel):
    """Indicators describing the quality of an extracted page."""

    text_length: int = Field(default=0, ge=0)
    language_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    contains_lists: bool = Field(default=False)
    readability_score: float | None = Field(default=None, ge=0.0, le=1.0)


class BudgetStatus(BaseModel):
    """Tracks resource consumption against configured limits."""

    pages_fetched: int = Field(default=0, ge=0)
    bytes_downloaded: int = Field(default=0, ge=0)
    max_pages: int = Field(default=0, ge=0)
    max_depth: int = Field(default=0, ge=0)
    max_time_minutes: int = Field(default=0, ge=0)
    max_content_size_mb: int = Field(default=0, ge=0)
    depth_max_seen: int = Field(default=0, ge=0)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def elapsed_seconds(self) -> float:
        return (datetime.now(timezone.utc) - self.started_at).total_seconds()

    def within_limits(self) -> bool:
        if self.max_pages and self.pages_fetched >= self.max_pages:
            return False
        if self.max_time_minutes and self.elapsed_seconds() >= self.max_time_minutes * 60:
            return False
        if self.max_depth and self.depth_max_seen > self.max_depth:
            return False
        return True


class ContentMetadata(BaseModel):
    """Metadata derived during content processing."""

    title: str | None = Field(default=None)
    description: str | None = Field(default=None)
    language: str = Field(default="und", min_length=2)
    language_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    checksum: str = Field(..., min_length=64, max_length=64)
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    quality: QualityMetrics = Field(default_factory=QualityMetrics)


class CacheEntry(BaseModel):
    """Cache metadata persisted on disk."""

    url: str = Field(..., min_length=1)
    alias_urls: List[str] = Field(default_factory=list)
    checksum: str = Field(..., min_length=64, max_length=64)
    stored_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_seconds: int = Field(default=0, ge=0)
    size_bytes: int = Field(default=0, ge=0)

    def expires_at(self) -> datetime:
        return self.stored_at + timedelta(seconds=self.ttl_seconds)

    def is_expired(self, now: datetime | None = None) -> bool:
        reference = now or datetime.now(timezone.utc)
        return reference >= self.expires_at()


class CrawlError(BaseModel):
    """Structured error representation for crawling issues."""

    url: str = Field(..., min_length=1)
    error_type: str = Field(..., min_length=1)
    detail: str = Field(..., min_length=1)
    retryable: bool = Field(default=False)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RobotsInfo(BaseModel):
    """Information derived from a robots.txt document."""

    robots_url: str = Field(..., min_length=1)
    crawl_delay: float | None = Field(default=None, ge=0.0)
    sitemaps: List[str] = Field(default_factory=list)
    disallowed: List[str] = Field(default_factory=list)
    allowed: List[str] = Field(default_factory=list)
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class URLQueueEntry(BaseModel):
    """Queue entry describing a URL awaiting fetch."""

    url: str = Field(..., min_length=1)
    depth: int = Field(default=0, ge=0)
    discovered_from: str | None = Field(default=None)

    @field_validator("url")
    @classmethod
    def _trim_url(cls, value: str) -> str:
        return value.strip()


class URLQueue(BaseModel):
    """Simple FIFO queue for URL traversal with depth tracking."""

    _queue: Deque[URLQueueEntry] = PrivateAttr(default_factory=deque)

    def enqueue(self, entry: URLQueueEntry, *, priority: bool = False) -> None:
        if priority:
            self._queue.appendleft(entry)
        else:
            self._queue.append(entry)

    def extend(self, entries: Iterable[URLQueueEntry], *, priority: bool = False) -> None:
        for entry in entries:
            self.enqueue(entry, priority=priority)

    def dequeue(self) -> URLQueueEntry | None:
        if not self._queue:
            return None
        return self._queue.popleft()

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._queue)

    def iter_pending(self) -> Sequence[URLQueueEntry]:
        return tuple(self._queue)


class CrawlConfig(BaseModel):
    """Configuration for an institutional crawl invocation."""

    institution_id: str = Field(..., min_length=1)
    seed_urls: List[str] = Field(default_factory=list)
    allowed_domains: List[str] = Field(default_factory=list)
    disallowed_paths: List[str] = Field(default_factory=list)
    include_patterns: List[str] = Field(default_factory=list)
    max_pages: int = Field(default=100, ge=1)
    max_depth: int = Field(default=3, ge=0)
    ttl_days: int = Field(default=14, ge=0)
    respect_robots: bool = Field(default=True)
    respect_crawl_delay: bool = Field(default=True)
    page_timeout_seconds: float = Field(default=20.0, ge=1.0)
    render_timeout_seconds: float = Field(default=15.0, ge=1.0)
    crawl_time_budget_minutes: int = Field(default=30, ge=1)
    max_content_size_mb: int = Field(default=5, ge=0)
    retry_attempts: int = Field(default=3, ge=0)

    @field_validator("seed_urls")
    @classmethod
    def _trim_seed_urls(cls, value: List[str]) -> List[str]:
        return [url.strip() for url in value if url.strip()]

    @model_validator(mode="after")
    def _validate_domains(self) -> "CrawlConfig":
        if not self.allowed_domains:
            raise ValueError("allowed_domains must contain at least one domain")
        return self


class CrawlSession(BaseModel):
    """Represents the state of an ongoing crawl."""

    config: CrawlConfig
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    queue: URLQueue = Field(default_factory=URLQueue)
    visited: Dict[str, datetime] = Field(default_factory=dict)
    errors: List[CrawlError] = Field(default_factory=list)
    metrics: Dict[str, int] = Field(default_factory=dict)
    budget: BudgetStatus = Field(default_factory=BudgetStatus)

    @model_validator(mode="after")
    def _initialize_budget(self) -> "CrawlSession":
        self.budget.max_pages = self.config.max_pages
        self.budget.max_depth = self.config.max_depth
        self.budget.max_time_minutes = self.config.crawl_time_budget_minutes
        self.budget.max_content_size_mb = self.config.max_content_size_mb
        return self

    def enqueue_seed_urls(self, *, prioritize: Callable[[str], bool] | None = None) -> None:
        for url in self.config.seed_urls:
            entry = URLQueueEntry(url=url, depth=0, discovered_from=None)
            is_priority = prioritize(url) if prioritize else False
            self.queue.enqueue(entry, priority=is_priority)

    def record_error(self, error: CrawlError) -> None:
        self.errors.append(error)
        self.metrics["errors"] = self.metrics.get("errors", 0) + 1


class CrawlResult(BaseModel):
    """Result container returned by the crawler."""

    institution_id: str = Field(..., min_length=1)
    snapshots: List[PageSnapshot] = Field(default_factory=list)
    errors: List[CrawlError] = Field(default_factory=list)
    budget_status: BudgetStatus = Field(default_factory=BudgetStatus)
    metrics: Dict[str, int | float | str | List[str]] = Field(default_factory=dict)
    finished_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def merge_metrics(self, other: Dict[str, int | float | str | List[str]]) -> None:
        for key, value in other.items():
            if isinstance(value, (int, float)):
                existing = self.metrics.get(key, 0) if isinstance(self.metrics.get(key, 0), (int, float)) else 0
                self.metrics[key] = existing + value
            else:
                self.metrics[key] = value

    def add_snapshot(self, snapshot: PageSnapshot) -> None:
        self.snapshots.append(snapshot)
        self.metrics["snapshots"] = self.metrics.get("snapshots", 0) + 1

    def add_error(self, error: CrawlError) -> None:
        self.errors.append(error)
        self.metrics["errors"] = self.metrics.get("errors", 0) + 1


__all__ = [
    "BudgetStatus",
    "CacheEntry",
    "ContentMetadata",
    "CrawlConfig",
    "CrawlError",
    "CrawlResult",
    "CrawlSession",
    "QualityMetrics",
    "RobotsInfo",
    "URLQueue",
    "URLQueueEntry",
]
