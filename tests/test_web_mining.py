"""Tests for the web mining module."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from taxonomy.entities.core import PageSnapshot, PageSnapshotMeta
from taxonomy.web_mining.cache import CacheManager
from taxonomy.web_mining.client import FetchResponse, WebMiner
from taxonomy.web_mining.content import ContentPolicyError, ContentProcessor, LanguageDetectionResult
from taxonomy.web_mining.models import CrawlConfig
from taxonomy.web_mining.robots import RobotsChecker
from taxonomy.web_mining.utils import is_allowed_domain


@pytest.fixture
def cache(tmp_path: Path) -> CacheManager:
    return CacheManager(tmp_path / "cache", ttl_days=2)


@pytest.fixture
def content_processor() -> ContentProcessor:
    return ContentProcessor(
        language_allowlist=["en"],
        language_confidence_threshold=0.6,
        min_text_length=0,
        pdf_extraction_enabled=False,
    )


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
    assert restored.meta.alias_urls == ["https://example.edu/page"]


def test_cache_manager_alias_urls(cache: CacheManager) -> None:
    first = _snapshot("https://example.edu/page", "Hello world")
    duplicate = _snapshot("https://example.edu/page?ref=home", "Hello world")
    cache.store(first)
    cache.store(duplicate)

    restored_first = cache.get(first.url)
    restored_second = cache.get(duplicate.url)

    expected_aliases = sorted([first.url, duplicate.url])
    assert restored_first is not None
    assert restored_second is not None
    assert restored_first.meta.alias_urls == expected_aliases
    assert restored_second.meta.alias_urls == expected_aliases


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


def test_content_processor_enforces_min_text_length() -> None:
    processor = ContentProcessor(language_allowlist=[], min_text_length=50, pdf_extraction_enabled=False)
    html = "<html><body>short text</body></html>"
    with pytest.raises(ContentPolicyError) as excinfo:
        processor.process(
            institution="demo",
            url="https://example.edu/min",
            http_status=200,
            content_type="text/html",
            body=html,
        )
    assert excinfo.value.reason == "min_text_length"


def test_content_processor_enforces_language_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    processor = ContentProcessor(
        language_allowlist=["en"],
        language_confidence_threshold=0.5,
        min_text_length=0,
        pdf_extraction_enabled=False,
    )

    monkeypatch.setattr(
        processor,
        "_detect_language",
        lambda text: LanguageDetectionResult(language="fr", confidence=0.9),
        raising=True,
    )

    with pytest.raises(ContentPolicyError) as excinfo:
        processor.process(
            institution="demo",
            url="https://example.edu/lang",
            http_status=200,
            content_type="text/html",
            body="<html><body>Bonjour monde</body></html>",
        )
    assert excinfo.value.reason == "language_allowlist"


def test_content_processor_pdf_size_limit() -> None:
    processor = ContentProcessor(
        language_allowlist=[],
        min_text_length=0,
        pdf_extraction_enabled=True,
        pdf_size_limit_mb=1,
    )
    payload = b"%PDF" + b"0" * (2 * 1024 * 1024)
    with pytest.raises(ContentPolicyError) as excinfo:
        processor.process(
            institution="demo",
            url="https://example.edu/doc",
            http_status=200,
            content_type="application/pdf",
            body=payload,
        )
    assert excinfo.value.reason == "pdf_size_limit"


def test_robots_checker_allows_and_blocks(robots_checker: RobotsChecker) -> None:
    allowed = robots_checker.is_allowed("https://example.edu/index")
    blocked = robots_checker.is_allowed("https://example.edu/private/data")
    assert allowed is True
    assert blocked is False


def test_is_allowed_domain_strict_suffix_matching() -> None:
    allowed = ["example.edu"]
    assert is_allowed_domain("https://example.edu/page", allowed)
    assert is_allowed_domain("https://sub.example.edu/path", allowed)
    assert not is_allowed_domain("https://badexample.edu/page", allowed)
    assert is_allowed_domain("https://example.edu", [".example.edu"])


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


def test_fetch_url_triggers_render_fallback(
    cache: CacheManager,
    content_processor: ContentProcessor,
    robots_checker: RobotsChecker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    miner = WebMiner(
        cache=cache,
        content_processor=content_processor,
        robots_checker=robots_checker,
        user_agent="TestBot/1.0",
        max_concurrency=1,
        rate_limit_per_sec=10,
    )

    class FakeResponse:
        def __init__(self, url: str) -> None:
            self.url = url
            self.status_code = 200
            self.headers = {"content-type": "text/html", "content-length": "0"}
            self.history: list[FakeResponse] = []

        @property
        def content(self) -> bytes:
            return b""

        def close(self) -> None:
            return None

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        return FakeResponse(url)

    monkeypatch.setattr("requests.get", fake_get)

    from firecrawl.v2.types import Document, DocumentMetadata

    class FakeFirecrawl:
        def scrape(self, url: str, timeout: int) -> Document:
            return Document(
                html="<html><body>rendered</body></html>",
                metadata=DocumentMetadata(url=url, status_code=200, content_type="text/html"),
            )

    miner._firecrawl = FakeFirecrawl()  # type: ignore[assignment]

    config = CrawlConfig(
        institution_id="demo",
        seed_urls=["https://example.edu/render"],
        allowed_domains=["example.edu"],
        disallowed_paths=[],
        respect_robots=False,
    )

    response = miner._fetch_url("https://example.edu/render", config)
    assert response.rendered is True
    assert b"rendered" in response.body


def test_crawl_delay_flag_controls_sleep(
    tmp_path: Path,
    content_processor: ContentProcessor,
    robots_checker: RobotsChecker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("taxonomy.web_mining.client.time.sleep", fake_sleep)
    monkeypatch.setattr(RobotsChecker, "crawl_delay", lambda self, url: 0.2)

    def fake_fetch(self, url: str, config: CrawlConfig) -> FetchResponse:  # type: ignore[override]
        return FetchResponse(
            url=url,
            status_code=200,
            content_type="text/html",
            body=b"<html><body>ok</body></html>",
            rendered=False,
            redirects=[],
            fetched_at=datetime.now(timezone.utc),
            bytes_downloaded=24,
        )

    monkeypatch.setattr(WebMiner, "_fetch_url", fake_fetch)

    cache_one = CacheManager(tmp_path / "cache_one", ttl_days=1)
    miner_one = WebMiner(
        cache=cache_one,
        content_processor=content_processor,
        robots_checker=robots_checker,
        user_agent="TestBot/1.0",
        max_concurrency=1,
        rate_limit_per_sec=10,
    )

    config_true = CrawlConfig(
        institution_id="demo",
        seed_urls=["https://example.edu/delay"],
        allowed_domains=["example.edu"],
        disallowed_paths=[],
        respect_robots=True,
        respect_crawl_delay=True,
        max_pages=1,
        max_depth=0,
    )

    miner_one.crawl_institution(config_true)
    assert sleeps == [pytest.approx(0.2)]

    sleeps.clear()
    cache_two = CacheManager(tmp_path / "cache_two", ttl_days=1)
    miner_two = WebMiner(
        cache=cache_two,
        content_processor=content_processor,
        robots_checker=robots_checker,
        user_agent="TestBot/1.0",
        max_concurrency=1,
        rate_limit_per_sec=10,
    )

    config_false = CrawlConfig(
        institution_id="demo",
        seed_urls=["https://example.edu/no-delay"],
        allowed_domains=["example.edu"],
        disallowed_paths=[],
        respect_robots=True,
        respect_crawl_delay=False,
        max_pages=1,
        max_depth=0,
    )

    miner_two.crawl_institution(config_false)
    assert sleeps == []
