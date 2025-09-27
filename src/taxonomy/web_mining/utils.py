"""Utility helpers for the web mining subsystem."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Sequence, TypeVar
from urllib.parse import urljoin, urlparse, urlunparse

from taxonomy.entities.core import PageSnapshot


T = TypeVar("T")


def _monotonic() -> float:
    return time.monotonic()


def normalize_url(url: str) -> str:
    """Return a normalized version of the URL suitable for comparisons."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("URL must use http or https scheme")
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    normalized = parsed._replace(scheme=parsed.scheme.lower(), netloc=netloc, fragment="", path=path)
    return urlunparse(normalized)


def canonicalize_url(url: str, base: str | None = None) -> str:
    """Canonicalize a URL optionally relative to a base."""

    if base:
        url = urljoin(base, url)
    return normalize_url(url)


def is_allowed_domain(url: str, allowed_domains: Sequence[str]) -> bool:
    """Check whether a URL belongs to an allowed domain list."""

    hostname = urlparse(url).hostname or ""
    hostname = hostname.lower()
    for domain in allowed_domains:
        normalized = domain.lower().lstrip(".")
        if not normalized:
            continue
        if hostname == normalized or hostname.endswith("." + normalized):
            return True
    return False


def is_disallowed_path(url: str, disallowed_paths: Sequence[str]) -> bool:
    """Determine if the URL path matches any disallowed prefix."""

    path = urlparse(url).path or "/"
    return any(path.startswith(prefix) for prefix in disallowed_paths)


def should_follow(url: str, allowed_domains: Sequence[str], disallowed_paths: Sequence[str]) -> bool:
    if not is_allowed_domain(url, allowed_domains):
        return False
    if is_disallowed_path(url, disallowed_paths):
        return False
    return True


def clean_text(text: str) -> str:
    """Normalize whitespace while preserving semantic boundaries."""

    collapsed = " ".join(text.split())
    return collapsed.strip()


def generate_checksum(text: str) -> str:
    """Generate a SHA-256 checksum using the entity helper."""

    return PageSnapshot.compute_checksum(text)


def within_content_budget(content_length_bytes: int, max_size_mb: int) -> bool:
    if not max_size_mb:
        return True
    return content_length_bytes <= max_size_mb * 1024 * 1024


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class RateLimiter:
    """Simple token-bucket rate limiter for politeness constraints."""

    rate_per_second: float
    burst: int

    _tokens: float = field(default=0.0, init=False)
    _last_check: float = field(default_factory=_monotonic, init=False)

    def __post_init__(self) -> None:
        # Seed the bucket to allow an initial burst up to the configured size.
        self._tokens = float(self.burst)
        self._last_check = time.monotonic()

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self._last_check)
        if elapsed == 0:
            return
        if self.rate_per_second > 0:
            self._tokens = min(self.burst, self._tokens + elapsed * self.rate_per_second)
        self._last_check = now

    def _consume_token(self) -> None:
        self._tokens = max(0.0, self._tokens - 1)

    def acquire(self) -> None:
        if self.rate_per_second <= 0:
            self._tokens = float(self.burst)
            self._consume_token()
            self._last_check = time.monotonic()
            return

        now = time.monotonic()
        self._refill(now)

        if self._tokens < 1:
            tokens_needed = 1 - self._tokens
            sleep_time = tokens_needed / self.rate_per_second
            if sleep_time > 0:
                time.sleep(sleep_time)
            post_sleep = time.monotonic()
            self._refill(post_sleep)

        self._consume_token()

    async def acquire_async(self) -> None:
        if self.rate_per_second <= 0:
            self._tokens = float(self.burst)
            self._consume_token()
            self._last_check = time.monotonic()
            return

        now = time.monotonic()
        self._refill(now)

        if self._tokens < 1:
            tokens_needed = 1 - self._tokens
            sleep_time = tokens_needed / self.rate_per_second
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            post_sleep = time.monotonic()
            self._refill(post_sleep)

        self._consume_token()


def exponential_backoff(attempt: int, base_delay: float = 1.0, max_delay: float = 30.0) -> float:
    delay = base_delay * (2 ** max(0, attempt))
    jitter = min(delay * 0.25, 1.0)
    return min(delay + jitter, max_delay)


def retryable(operation: Callable[[], T], retries: int = 3) -> T:  # type: ignore[name-defined]
    """Execute an operation with simple retry semantics."""

    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return operation()
        except Exception as exc:  # pragma: no cover - defensive
            last_exc = exc
            time.sleep(exponential_backoff(attempt))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("retryable exhausted without raising exception")


__all__ = [
    "RateLimiter",
    "canonicalize_url",
    "clean_text",
    "exponential_backoff",
    "generate_checksum",
    "is_allowed_domain",
    "is_disallowed_path",
    "normalize_url",
    "retryable",
    "should_follow",
    "utc_now",
    "within_content_budget",
]
