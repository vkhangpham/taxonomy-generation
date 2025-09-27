"""Web mining client built on Firecrawl SDK with caching and observability."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence

import requests

try:  # pragma: no cover - optional dependency
    from firecrawl import FirecrawlApp
except Exception:  # pragma: no cover - fallback path
    FirecrawlApp = None

from taxonomy.entities.core import PageSnapshot
from taxonomy.utils.logging import get_logger

from .cache import CacheManager
from .content import ContentProcessor
from .models import CrawlConfig, CrawlError, CrawlResult, CrawlSession, URLQueueEntry
from .observability import MetricsCollector
from .robots import RobotsChecker
from .utils import RateLimiter, canonicalize_url, should_follow, within_content_budget


@dataclass
class FetchResponse:
    url: str
    status_code: int
    content_type: str
    body: bytes
    rendered: bool
    redirects: List[str]
    fetched_at: datetime
    bytes_downloaded: int


class WebMiner:
    """Primary interface for institutional web crawling."""

    def __init__(
        self,
        *,
        cache: CacheManager,
        content_processor: ContentProcessor,
        robots_checker: RobotsChecker,
        user_agent: str = "TaxonomyBot/1.0",
        max_concurrency: int = 4,
        rate_limit_per_sec: float = 1.0,
        firecrawl_api_key: str | None = None,
        firecrawl_endpoint: str | None = None,
    ) -> None:
        self.cache = cache
        self.content_processor = content_processor
        self.robots_checker = robots_checker
        self.user_agent = user_agent
        self.rate_limiter = RateLimiter(rate_per_second=rate_limit_per_sec, burst=max_concurrency)
        self._logger = get_logger(component="web_miner", user_agent=user_agent)
        self._firecrawl = None
        if FirecrawlApp is not None and (firecrawl_api_key or os.getenv("FIRECRAWL_API_KEY")):
            api_key = firecrawl_api_key or os.getenv("FIRECRAWL_API_KEY")
            self._firecrawl = FirecrawlApp(api_key=api_key, base_url=firecrawl_endpoint)

    def crawl_institution(self, config: CrawlConfig) -> CrawlResult:
        metrics = MetricsCollector(config.institution_id)
        session = CrawlSession(config=config)
        session.enqueue_seed_urls()
        result = CrawlResult(institution_id=config.institution_id)
        visited: set[str] = set()

        while True:
            if not session.budget.within_limits():
                self._logger.info("Budget exhausted", institution=config.institution_id)
                break
            queue_entry = session.queue.dequeue()
            if queue_entry is None:
                break
            url = queue_entry.url
            if url in visited:
                continue
            visited.add(url)
            session.budget.depth_max_seen = max(session.budget.depth_max_seen, queue_entry.depth)
            if queue_entry.depth > config.max_depth:
                continue
            if not should_follow(url, config.allowed_domains, config.disallowed_paths):
                metrics.increment("filtered")
                continue
            if config.respect_robots and not self.robots_checker.is_allowed(url):
                metrics.record_fetch(robots_blocked=True)
                continue
            crawl_delay = self.robots_checker.crawl_delay(url) if config.respect_robots else None
            if crawl_delay:
                time.sleep(crawl_delay)

            cached_snapshot = self.cache.get(url)
            if cached_snapshot:
                metrics.record_cache_hit()
                result.add_snapshot(cached_snapshot)
                session.visited[url] = datetime.now(timezone.utc)
                session.budget.pages_fetched += 1
                continue

            metrics.record_cache_miss()
            try:
                fetch_response = self._fetch_url(url, config)
            except Exception as exc:
                error = CrawlError(url=url, error_type="fetch", detail=str(exc), retryable=True)
                session.record_error(error)
                result.add_error(error)
                metrics.record_error("fetch")
                continue

            session.budget.bytes_downloaded += fetch_response.bytes_downloaded
            if not within_content_budget(fetch_response.bytes_downloaded, config.max_content_size_mb):
                metrics.record_error("over_budget")
                continue

            try:
                snapshot, content_meta = self.content_processor.process(
                    institution=config.institution_id,
                    url=fetch_response.url,
                    http_status=fetch_response.status_code,
                    content_type=fetch_response.content_type,
                    body=fetch_response.body,
                    fetched_at=fetch_response.fetched_at,
                    rendered=fetch_response.rendered,
                    robots_blocked=False,
                    redirects=fetch_response.redirects,
                )
            except Exception as exc:
                error = CrawlError(url=url, error_type="content", detail=str(exc), retryable=False)
                session.record_error(error)
                result.add_error(error)
                metrics.record_error("content")
                continue

            if snapshot.http_status >= 400:
                error = CrawlError(
                    url=url,
                    error_type="http",
                    detail=f"HTTP status {snapshot.http_status}",
                    retryable=False,
                )
                session.record_error(error)
                result.add_error(error)
                metrics.record_error("http")
                continue

            self.cache.store(snapshot)
            result.add_snapshot(snapshot)
            session.visited[url] = fetch_response.fetched_at
            session.budget.pages_fetched += 1
            metrics.record_fetch(rendered=fetch_response.rendered)

            if queue_entry.depth < config.max_depth and snapshot.html:
                discovered = self._discover_links(snapshot.html, snapshot.url)
                followable = [link for link in discovered if should_follow(link, config.allowed_domains, config.disallowed_paths)]
                for link in followable:
                    if link not in visited:
                        session.queue.enqueue(
                            URLQueueEntry(url=link, depth=queue_entry.depth + 1, discovered_from=snapshot.url)
                        )
                        metrics.increment("urls_queued")

        result.budget_status = session.budget
        result.merge_metrics(metrics.finalize())
        result.errors.extend(session.errors)
        return result

    def _fetch_url(self, url: str, config: CrawlConfig) -> FetchResponse:
        self.rate_limiter.acquire()
        headers = {"User-Agent": self.user_agent}
        redirects: List[str] = []
        fetched_at = datetime.now(timezone.utc)

        if self._firecrawl is not None:
            response = self._firecrawl.get_url(url, params={"timeout": int(config.page_timeout_seconds * 1000)})
            status_code = response.get("status_code", 200)
            content_type = response.get("headers", {}).get("content-type", "text/html")
            body = response.get("content", "").encode("utf-8")
            redirects = response.get("redirects", [])
            rendered = response.get("rendered", False)
        else:
            resp = requests.get(url, headers=headers, timeout=config.page_timeout_seconds)
            status_code = resp.status_code
            content_type = resp.headers.get("content-type", "text/html")
            body = resp.content
            redirects = [r.url for r in getattr(resp, "history", []) if getattr(r, "url", None)]
            if getattr(resp, "url", None) and resp.url != url:
                redirects.append(resp.url)
            rendered = False

        return FetchResponse(
            url=url,
            status_code=status_code,
            content_type=content_type.split(";")[0].lower(),
            body=body,
            rendered=rendered,
            redirects=[link for link in redirects if link],
            fetched_at=fetched_at,
            bytes_downloaded=len(body),
        )

    def _discover_links(self, html: str, base_url: str) -> Sequence[str]:
        anchors = re.findall(r"<a[^>]+href=\"([^\"]+)\"", html, flags=re.IGNORECASE)
        normalized: List[str] = []
        for href in anchors:
            try:
                normalized.append(canonicalize_url(href, base=base_url))
            except Exception:
                continue
        return normalized


__all__ = ["WebMiner", "FetchResponse"]
