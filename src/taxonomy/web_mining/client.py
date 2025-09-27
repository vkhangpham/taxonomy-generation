"""Web mining client built on Firecrawl SDK with caching and observability."""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence

import requests
from requests import Response
from requests.exceptions import RequestException

try:  # pragma: no cover - optional dependency
    from firecrawl.v2 import FirecrawlClient
    from firecrawl.v2.types import Document
except Exception:  # pragma: no cover - fallback path
    FirecrawlClient = None  # type: ignore[assignment]
    Document = None  # type: ignore[assignment]

from taxonomy.entities.core import PageSnapshot
from taxonomy.utils.logging import get_logger

from .cache import CacheManager
from .content import ContentPolicyError, ContentProcessor
from .models import CrawlConfig, CrawlError, CrawlResult, CrawlSession, URLQueueEntry
from .observability import MetricsCollector
from .robots import RobotsChecker
from .utils import RateLimiter, canonicalize_url, retryable, should_follow, within_content_budget


class FetchError(Exception):
    """Exception raised when a network fetch fails."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


def _document_html(document: Document | None) -> bytes:
    if document is None:
        return b""
    html = document.html or document.raw_html or document.markdown or ""
    if isinstance(html, str):
        return html.encode("utf-8")
    return html


def _should_render(body: bytes, content_type: str) -> bool:
    if "html" not in content_type:
        return False
    text = body.decode("utf-8", errors="ignore")
    if not text.strip():
        return True
    lowered = text.lower()
    client_side_markers = (
        "<script",
        "id=\"app",
        "id='app",
        "data-reactroot",
        "ng-app",
        "id=\"root",
        "id='root",
    )
    return len(text.strip()) < 256 and any(marker in lowered for marker in client_side_markers)


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
        self._firecrawl: FirecrawlClient | None = None
        if FirecrawlClient is not None and (firecrawl_api_key or os.getenv("FIRECRAWL_API_KEY")):
            api_key = firecrawl_api_key or os.getenv("FIRECRAWL_API_KEY")
            timeout = None
            if firecrawl_endpoint:
                self._firecrawl = FirecrawlClient(api_key=api_key, api_url=firecrawl_endpoint, timeout=timeout)
            else:
                self._firecrawl = FirecrawlClient(api_key=api_key, timeout=timeout)

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
            if crawl_delay and config.respect_crawl_delay:
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
            except ContentPolicyError as exc:
                error = CrawlError(url=url, error_type="content_policy", detail=str(exc), retryable=False)
                session.record_error(error)
                result.add_error(error)
                metrics.record_error("content_policy")
                continue
            except FetchError as exc:
                error = CrawlError(url=url, error_type="fetch", detail=str(exc), retryable=exc.retryable)
                session.record_error(error)
                result.add_error(error)
                metrics.record_error("fetch")
                continue
            except Exception as exc:  # pragma: no cover - defensive catch
                error = CrawlError(url=url, error_type="fetch", detail=str(exc), retryable=False)
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
            except ContentPolicyError as exc:
                error = CrawlError(url=url, error_type="content_policy", detail=str(exc), retryable=False)
                session.record_error(error)
                result.add_error(error)
                metrics.record_error("content_policy")
                continue
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
        fetched_at = datetime.now(timezone.utc)
        retries = getattr(config, "retry_attempts", 3)

        def issue_request() -> Response:
            return requests.get(
                url,
                headers=headers,
                timeout=config.page_timeout_seconds,
                stream=True,
                allow_redirects=True,
            )

        try:
            response = retryable(issue_request, retries=retries)
        except RequestException as exc:
            raise FetchError(f"Request failed for {url}: {exc}", retryable=True) from exc
        except Exception as exc:  # pragma: no cover - defensive
            raise FetchError(f"Fetch failed for {url}: {exc}", retryable=False) from exc

        try:
            content_type_header = response.headers.get("content-type", "text/html")
            content_type = content_type_header.split(";")[0].lower()
            content_length_header = response.headers.get("content-length")
            if content_length_header:
                try:
                    declared_length = int(content_length_header)
                except ValueError:
                    declared_length = None
                else:
                    if not within_content_budget(declared_length, config.max_content_size_mb):
                        raise ContentPolicyError(
                            "content_length",
                            f"Content-Length {declared_length} exceeds limit {config.max_content_size_mb} MB",
                        )
            body = response.content
            redirects = [r.url for r in getattr(response, "history", []) if getattr(r, "url", None)]
            final_url = response.url or url
            if final_url != url:
                redirects.append(final_url)
        finally:
            response.close()

        rendered = False
        final_body = body
        final_content_type = content_type
        status_code = response.status_code
        try:
            final_url = canonicalize_url(final_url)
        except Exception:
            final_url = canonicalize_url(url)
        normalized_redirects: List[str] = []
        for link in redirects:
            if not link:
                continue
            try:
                normalized_redirects.append(canonicalize_url(link))
            except Exception:  # pragma: no cover - ignore malformed redirect
                continue
        redirects = normalized_redirects

        document: Document | None = None
        if self._firecrawl is not None and _should_render(body, content_type):
            def render_operation() -> Document:
                timeout = int(max(1, round(config.render_timeout_seconds)))
                return self._firecrawl.scrape(url, timeout=timeout)

            try:
                document = retryable(render_operation, retries=retries)
            except Exception as exc:  # pragma: no cover - rendering failures are logged
                self._logger.warning("Firecrawl render failed", url=url, error=str(exc))
            else:
                rendered_body = _document_html(document)
                if rendered_body.strip():
                    rendered = True
                    final_body = rendered_body
                    final_content_type = (document.metadata.content_type if document and document.metadata else None) or "text/html"
                    final_content_type = final_content_type.split(";")[0].lower()
                    if document and document.metadata and document.metadata.url:
                        try:
                            final_url = canonicalize_url(document.metadata.url)
                        except Exception:  # pragma: no cover - defensive
                            pass
                    if document and document.metadata and document.metadata.status_code:
                        status_code = document.metadata.status_code
                    fetched_at = datetime.now(timezone.utc)

        return FetchResponse(
            url=final_url,
            status_code=status_code,
            content_type=final_content_type,
            body=final_body,
            rendered=rendered,
            redirects=redirects,
            fetched_at=fetched_at,
            bytes_downloaded=len(final_body),
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
