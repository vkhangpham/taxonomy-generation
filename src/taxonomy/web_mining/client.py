"""Web mining client built on Firecrawl SDK with caching and observability."""

from __future__ import annotations

import gzip
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Optional, Sequence

import requests
from requests import Response
from requests.exceptions import RequestException
from xml.etree import ElementTree as ET

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

    def __init__(self, message: str, *, retryable: bool = True, error_type: str = "fetch") -> None:
        super().__init__(message)
        self.retryable = retryable
        self.error_type = error_type


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
        ttl_override_seconds = config.ttl_days * 24 * 3600

        include_matchers: list[re.Pattern[str]] = []
        for pattern in config.include_patterns:
            try:
                include_matchers.append(re.compile(pattern))
            except re.error as exc:
                self._logger.warning(
                    "Invalid include pattern",
                    institution=config.institution_id,
                    pattern=pattern,
                    error=str(exc),
                )

        def matches_include(candidate: str) -> bool:
            if not include_matchers:
                return False
            return any(matcher.search(candidate) for matcher in include_matchers)

        session.enqueue_seed_urls(prioritize=matches_include)
        queued_urls: set[str] = {entry.url for entry in session.queue.iter_pending()}
        visited: set[str] = set()

        def has_capacity_for_new_url() -> bool:
            if config.max_pages:
                return len(session.queue) + session.budget.pages_fetched < config.max_pages
            return True

        if config.respect_robots and config.max_depth >= 1:
            processed_sitemaps: set[str] = set()
            for seed_url in config.seed_urls:
                try:
                    robots_info = self.robots_checker.info(seed_url)
                except Exception as exc:
                    self._logger.debug(
                        "Sitemap discovery skipped",
                        institution=config.institution_id,
                        url=seed_url,
                        error=str(exc),
                    )
                    continue
                for sitemap_url in robots_info.sitemaps:
                    if sitemap_url in processed_sitemaps:
                        continue
                    if not has_capacity_for_new_url():
                        break
                    remaining_capacity = None
                    if config.max_pages:
                        remaining_capacity = config.max_pages - (len(session.queue) + session.budget.pages_fetched)
                        if remaining_capacity <= 0:
                            break
                    discovered_urls = self._collect_sitemap_urls(
                        sitemap_url,
                        timeout=config.page_timeout_seconds,
                        seen=set(),
                        max_urls=remaining_capacity,
                    )
                    for candidate in discovered_urls:
                        if candidate in queued_urls or candidate in visited:
                            continue
                        if not has_capacity_for_new_url():
                            break
                        if not should_follow(candidate, config.allowed_domains, config.disallowed_paths):
                            continue
                        session.queue.enqueue(
                            URLQueueEntry(url=candidate, depth=1, discovered_from=sitemap_url),
                            priority=matches_include(candidate),
                        )
                        queued_urls.add(candidate)
                        metrics.increment("urls_queued")
                    if not has_capacity_for_new_url():
                        break
                    processed_sitemaps.add(sitemap_url)

        result = CrawlResult(institution_id=config.institution_id)

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
                error = CrawlError(url=url, error_type=exc.error_type, detail=str(exc), retryable=exc.retryable)
                session.record_error(error)
                result.add_error(error)
                metrics.record_error(exc.error_type)
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
                    metrics=metrics,
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

            self.cache.store(snapshot, metrics=metrics, ttl_seconds=ttl_override_seconds)
            result.add_snapshot(snapshot)
            session.visited[url] = fetch_response.fetched_at
            session.budget.pages_fetched += 1
            metrics.record_fetch(rendered=fetch_response.rendered)

            if queue_entry.depth < config.max_depth and snapshot.html:
                discovered = self._discover_links(snapshot.html, snapshot.url)
                followable = [link for link in discovered if should_follow(link, config.allowed_domains, config.disallowed_paths)]
                for link in followable:
                    if link in visited or link in queued_urls:
                        continue
                    if not has_capacity_for_new_url():
                        break
                    session.queue.enqueue(
                        URLQueueEntry(url=link, depth=queue_entry.depth + 1, discovered_from=snapshot.url),
                        priority=matches_include(link),
                    )
                    queued_urls.add(link)
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
                    limit_bytes = config.max_content_size_mb * 1024 * 1024 if config.max_content_size_mb else None
                    if limit_bytes and declared_length > limit_bytes:
                        response.close()
                        raise FetchError(
                            f"Content-Length {declared_length} exceeds limit {config.max_content_size_mb} MB",
                            retryable=False,
                            error_type="over_budget",
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

    def _fetch_sitemap(self, sitemap_url: str, timeout: float) -> str | None:
        headers = {"User-Agent": self.user_agent}
        try:
            response = requests.get(sitemap_url, headers=headers, timeout=timeout)
            response.raise_for_status()
        except RequestException as exc:
            self._logger.debug("Sitemap fetch failed", sitemap_url=sitemap_url, error=str(exc))
            return None
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.debug("Sitemap fetch error", sitemap_url=sitemap_url, error=str(exc))
            return None

        try:
            content = response.content
            content_type = response.headers.get("content-type", "").lower()
            if "gzip" in content_type or sitemap_url.endswith(".gz"):
                try:
                    content = gzip.decompress(content)
                except OSError as exc:
                    self._logger.debug("Sitemap decompress failed", sitemap_url=sitemap_url, error=str(exc))
                    return None
            try:
                return content.decode("utf-8")
            except UnicodeDecodeError:
                return content.decode("utf-8", errors="ignore")
        finally:
            response.close()

    def _collect_sitemap_urls(
        self,
        sitemap_url: str,
        *,
        timeout: float,
        seen: set[str],
        depth: int = 0,
        max_depth: int = 2,
        max_urls: int | None = None,
    ) -> List[str]:
        if sitemap_url in seen or depth > max_depth:
            return []
        seen.add(sitemap_url)

        body = self._fetch_sitemap(sitemap_url, timeout)
        if body is None:
            return []

        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            self._logger.debug("Sitemap parse failed", sitemap_url=sitemap_url, error=str(exc))
            return []

        urls: List[str] = []
        tag = root.tag.lower()
        if tag.endswith("sitemapindex") and depth < max_depth:
            for loc in root.findall(".//{*}loc"):
                nested = (loc.text or "").strip()
                if not nested:
                    continue
                remaining = None if max_urls is None else max_urls - len(urls)
                if remaining is not None and remaining <= 0:
                    break
                nested_urls = self._collect_sitemap_urls(
                    nested,
                    timeout=timeout,
                    seen=seen,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_urls=remaining,
                )
                urls.extend(nested_urls)
                if max_urls is not None and len(urls) >= max_urls:
                    return urls[:max_urls]
        else:
            for loc in root.findall(".//{*}loc"):
                candidate = (loc.text or "").strip()
                if not candidate:
                    continue
                urls.append(candidate)
                if max_urls is not None and len(urls) >= max_urls:
                    return urls

        return urls

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
