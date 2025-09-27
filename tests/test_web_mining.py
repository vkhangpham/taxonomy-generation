"""Tests for the web mining module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from taxonomy.entities.core import PageSnapshot, PageSnapshotMeta
from taxonomy.web_mining.cache import CacheManager
from taxonomy.web_mining.client import FetchResponse, WebMiner
from taxonomy.web_mining.content import ContentProcessor
from taxonomy.web_mining.models import CrawlConfig
from taxonomy.web_mining.robots import RobotsChecker


@pytest.fixture
def cache(tmp_path: Path) -> CacheManager:
    return CacheManager(tmp_path / "cache", ttl_days=2)


@pytest.fixture
def content_processor() -> ContentProcessor:
    return ContentProcessor(language_allowlist=["en"], min_text_length=0, pdf_extraction_enabled=False)


@pytest.fixture
def robots_checker() -> RobotsChecker:
    robots_body = """User-agent: *\nDisallow: /private\nAllow: /"""
    return RobotsChecker(fetcher=lambda url: (200, robots_body), cache_ttl_seconds=3600)


def _snapshot(url: str, text: str) -> PageSnapshot:
    checksum = PageSnapshot.compute_checksum(text)
    return PageSnapshot(
        institution="demo",
        url=url,
        canonical_url=None,
        fetched_at=datetime.now(timezone.utc),
        http_status=200,
        content_type="text/html",
        html=f"<html><body>{text}</body></html>",
        text=text,
        lang="en",
        checksum=checksum,
        meta=PageSnapshotMeta(),
    )


def test_cache_manager_roundtrip(cache: CacheManager) -> None:
    snapshot = _snapshot("https://example.edu/page", "Hello world")
    cache.store(snapshot)
    restored = cache.get("https://example.edu/page")
    assert restored is not None
    assert restored.checksum == snapshot.checksum


def test_cache_manager_expiration(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache", ttl_days=0)
    cache.store(_snapshot("https://example.edu/p", "data"))
    assert cache.get("https://example.edu/p") is None


def test_content_processor_extracts_text(content_processor: ContentProcessor) -> None:
    html = """<html><head><title>Sample</title></head><body><p>Hello <b>World</b></p></body></html>"""
    snapshot, meta = content_processor.process(
        institution="demo",
        url="https://example.edu/sample",
        http_status=200,
        content_type="text/html",
        body=html,
    )
    assert "Hello" in snapshot.text
    assert snapshot.checksum
    assert meta.quality.text_length > 0


def test_robots_checker_allows_and_blocks(robots_checker: RobotsChecker) -> None:
    allowed = robots_checker.is_allowed("https://example.edu/index")
    blocked = robots_checker.is_allowed("https://example.edu/private/data")
    assert allowed is True
    assert blocked is False


def test_web_miner_crawl_flow(cache: CacheManager, content_processor: ContentProcessor, robots_checker: RobotsChecker, monkeypatch: pytest.MonkeyPatch) -> None:
    miner = WebMiner(
        cache=cache,
        content_processor=content_processor,
        robots_checker=robots_checker,
        user_agent="TestBot/1.0",
        max_concurrency=1,
        rate_limit_per_sec=10,
    )

    html_root = '<html><body><a href="https://example.edu/next">Next</a></body></html>'
    html_child = '<html><body><p>Child page</p></body></html>'

    responses = {
        "https://example.edu/start": FetchResponse(
            url="https://example.edu/start",
            status_code=200,
            content_type="text/html",
            body=html_root.encode("utf-8"),
            rendered=False,
            redirects=[],
            fetched_at=datetime.now(timezone.utc),
            bytes_downloaded=len(html_root),
        ),
        "https://example.edu/next": FetchResponse(
            url="https://example.edu/next",
            status_code=200,
            content_type="text/html",
            body=html_child.encode("utf-8"),
            rendered=False,
            redirects=[],
            fetched_at=datetime.now(timezone.utc),
            bytes_downloaded=len(html_child),
        ),
    }

    def fake_fetch(self, url: str, config: CrawlConfig) -> FetchResponse:  # type: ignore[override]
        return responses[url]

    monkeypatch.setattr(WebMiner, "_fetch_url", fake_fetch)

    config = CrawlConfig(
        institution_id="demo",
        seed_urls=["https://example.edu/start"],
        allowed_domains=["example.edu"],
        disallowed_paths=["/private"],
        max_pages=5,
        max_depth=2,
        ttl_days=14,
        respect_robots=True,
    )

    result = miner.crawl_institution(config)
    assert len(result.snapshots) == 2
    urls = {snapshot.url for snapshot in result.snapshots}
    assert "https://example.edu/start" in urls
    assert "https://example.edu/next" in urls
    assert result.budget_status.pages_fetched == 2


