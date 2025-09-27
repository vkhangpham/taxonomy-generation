"""Tests for the web mining module."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from taxonomy.config.policies import load_policies
from taxonomy.entities.core import PageSnapshot, PageSnapshotMeta
from taxonomy.web_mining import build_web_miner
from taxonomy.web_mining.cache import CacheManager
from taxonomy.web_mining.client import FetchError, FetchResponse, WebMiner
from taxonomy.web_mining.content import ContentPolicyError, ContentProcessor, LanguageDetectionResult
from taxonomy.web_mining.observability import MetricsCollector
from taxonomy.web_mining.models import CrawlConfig, RobotsInfo
from taxonomy.web_mining.robots import RobotsChecker
from taxonomy.web_mining.utils import RateLimiter, is_allowed_domain


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    async def sleep_async(self, seconds: float) -> None:
        self.sleep(seconds)

    def advance(self, seconds: float) -> None:
        self.now += seconds


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


def test_rate_limiter_respects_rate_over_time(monkeypatch: pytest.MonkeyPatch) -> None:
    from taxonomy.web_mining import utils as utils_module

    clock = _FakeClock()
    monkeypatch.setattr(utils_module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(utils_module.time, "sleep", clock.sleep)

    limiter = RateLimiter(rate_per_second=2, burst=1)

    limiter.acquire()
    assert clock.sleeps == []

    limiter.acquire()
    assert clock.sleeps == [pytest.approx(0.5, rel=1e-3)]
    assert limiter._last_check == pytest.approx(clock.now, rel=1e-6)

    clock.advance(0.5)
    limiter.acquire()
    assert len(clock.sleeps) == 1


def test_rate_limiter_async_respects_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    from taxonomy.web_mining import utils as utils_module

    clock = _FakeClock()
    monkeypatch.setattr(utils_module.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(utils_module.asyncio, "sleep", clock.sleep_async)

    limiter = RateLimiter(rate_per_second=1, burst=1)

    async def run() -> None:
        await limiter.acquire_async()
        assert clock.sleeps == []

        await limiter.acquire_async()
        assert clock.sleeps == [pytest.approx(1.0, rel=1e-3)]
        assert limiter._last_check == pytest.approx(clock.now, rel=1e-6)

        clock.advance(1.0)
        await limiter.acquire_async()
        assert len(clock.sleeps) == 1

    asyncio.run(run())


def test_fetch_url_respects_content_length_budget(
    cache: CacheManager,
    content_processor: ContentProcessor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from taxonomy.web_mining import client as client_module

    class StubRobotsChecker:
        def is_allowed(self, url: str) -> bool:
            return True

        def crawl_delay(self, url: str) -> float | None:
            return None

        def info(self, url: str) -> RobotsInfo:  # pragma: no cover - unused
            return RobotsInfo(robots_url="https://example.edu/robots.txt")

    miner = WebMiner(
        cache=cache,
        content_processor=content_processor,
        robots_checker=StubRobotsChecker(),
        user_agent="TestBot/1.0",
        max_concurrency=1,
        rate_limit_per_sec=100.0,
    )

    class StubResponse:
        def __init__(self) -> None:
            self.headers = {
                "content-type": "text/html",
                "content-length": str(2 * 1024 * 1024),
            }
            self.status_code = 200
            self.url = "https://example.edu/oversized"
            self.history: list[str] = []
            self.closed = False

        @property
        def content(self) -> bytes:
            raise AssertionError("Body should not be downloaded when over budget")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(miner.rate_limiter, "acquire", lambda: None)
    monkeypatch.setattr(client_module, "retryable", lambda operation, retries=3: StubResponse())

    config = CrawlConfig(
        institution_id="demo",
        seed_urls=[],
        allowed_domains=["example.edu"],
        disallowed_paths=[],
        include_patterns=[],
        max_pages=1,
        max_depth=1,
        ttl_days=1,
        respect_robots=False,
        respect_crawl_delay=False,
        page_timeout_seconds=5,
        render_timeout_seconds=5,
        crawl_time_budget_minutes=5,
        max_content_size_mb=1,
        retry_attempts=0,
    )

    with pytest.raises(FetchError) as excinfo:
        miner._fetch_url("https://example.edu/oversized", config)

    assert excinfo.value.error_type == "over_budget"
    assert excinfo.value.retryable is False


def test_discover_links_handles_varied_formats(
    cache: CacheManager,
    content_processor: ContentProcessor,
    robots_checker: RobotsChecker,
) -> None:
    miner = WebMiner(
        cache=cache,
        content_processor=content_processor,
        robots_checker=robots_checker,
        user_agent="TestBot/1.0",
        max_concurrency=1,
        rate_limit_per_sec=10.0,
    )

    html = (
        "<html><body>"
        "<a href='/about'>About</a>"
        "<a href='https://example.org/contact'>Contact</a>"
        "<a href=https://example.edu/faq>FAQ</a>"
        "<a href=\"mailto:info@example.edu\">Mail</a>"
        "</body></html>"
    )
    links = miner._discover_links(html, "https://example.edu/start")

    assert "https://example.edu/about" in links
    assert "https://example.org/contact" in links
    assert "https://example.edu/faq" in links
    assert not any(link.startswith("mailto:") for link in links)


def test_crawl_institution_prioritizes_include_patterns(
    cache: CacheManager,
    content_processor: ContentProcessor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_url = "https://example.edu/start"
    include_url = "https://example.edu/important"
    other_url = "https://example.edu/other"

    class StubRobotsChecker:
        def is_allowed(self, url: str) -> bool:
            return True

        def crawl_delay(self, url: str) -> float | None:
            return None

        def info(self, url: str) -> RobotsInfo:
            return RobotsInfo(robots_url="https://example.edu/robots.txt", crawl_delay=None, sitemaps=[])

    miner = WebMiner(
        cache=cache,
        content_processor=content_processor,
        robots_checker=StubRobotsChecker(),
        user_agent="TestBot/1.0",
        max_concurrency=1,
        rate_limit_per_sec=100.0,
    )

    html = (
        f'<html><body><a href="{include_url}">Include</a>'
        f'<a href="{other_url}">Other</a></body></html>'
    )
    fetch_map = {
        seed_url: FetchResponse(
            url=seed_url,
            status_code=200,
            content_type="text/html",
            body=html.encode("utf-8"),
            rendered=False,
            redirects=[],
            fetched_at=datetime.now(timezone.utc),
            bytes_downloaded=len(html),
        ),
        include_url: FetchResponse(
            url=include_url,
            status_code=200,
            content_type="text/html",
            body=b"<html><body>This page is in English.</body></html>",
            rendered=False,
            redirects=[],
            fetched_at=datetime.now(timezone.utc),
            bytes_downloaded=28,
        ),
        other_url: FetchResponse(
            url=other_url,
            status_code=200,
            content_type="text/html",
            body=b"<html><body>This page is also in English.</body></html>",
            rendered=False,
            redirects=[],
            fetched_at=datetime.now(timezone.utc),
            bytes_downloaded=28,
        ),
    }

    fetched_order: list[str] = []

    def fake_fetch(url: str, crawl_config: CrawlConfig) -> FetchResponse:
        fetched_order.append(url)
        return fetch_map[url]

    monkeypatch.setattr(miner, "_fetch_url", fake_fetch)
    monkeypatch.setattr(miner.rate_limiter, "acquire", lambda: None)

    config = CrawlConfig(
        institution_id="demo",
        seed_urls=[seed_url],
        allowed_domains=["example.edu"],
        disallowed_paths=[],
        include_patterns=[r"important"],
        max_pages=3,
        max_depth=2,
        ttl_days=1,
        respect_robots=True,
        respect_crawl_delay=False,
        page_timeout_seconds=5,
        render_timeout_seconds=5,
        crawl_time_budget_minutes=5,
        max_content_size_mb=5,
        retry_attempts=1,
    )

    result = miner.crawl_institution(config)

    assert fetched_order[:2] == [seed_url, include_url]
    assert any(snapshot.url == include_url for snapshot in result.snapshots)
    assert result.metrics.get("budget_pages_fetched", 0) >= len(result.snapshots)
    assert result.metrics.get("budget_elapsed_seconds", 0.0) >= 0.0


def test_crawl_institution_seeds_from_sitemap_respecting_budget(
    cache: CacheManager,
    content_processor: ContentProcessor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed_url = "https://example.edu/start"
    sitemap_url = "https://example.edu/sitemap.xml"
    first_url = "https://example.edu/about"
    second_url = "https://example.edu/contact"

    class StubRobotsChecker:
        def is_allowed(self, url: str) -> bool:
            return True

        def crawl_delay(self, url: str) -> float | None:
            return None

        def info(self, url: str) -> RobotsInfo:
            return RobotsInfo(
                robots_url="https://example.edu/robots.txt",
                crawl_delay=None,
                sitemaps=[sitemap_url],
            )

    miner = WebMiner(
        cache=cache,
        content_processor=content_processor,
        robots_checker=StubRobotsChecker(),
        user_agent="TestBot/1.0",
        max_concurrency=1,
        rate_limit_per_sec=100.0,
    )

    sitemap_body = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
        "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"
        f"<url><loc>{first_url}</loc></url>"
        f"<url><loc>{second_url}</loc></url>"
        "</urlset>"
    )

    def fake_fetch_sitemap(url: str, timeout: float) -> str | None:
        assert url == sitemap_url
        return sitemap_body

    monkeypatch.setattr(miner, "_fetch_sitemap", fake_fetch_sitemap)
    monkeypatch.setattr(miner.rate_limiter, "acquire", lambda: None)

    fetch_map = {
        seed_url: FetchResponse(
            url=seed_url,
            status_code=200,
            content_type="text/html",
            body=b"<html><body>seed</body></html>",
            rendered=False,
            redirects=[],
            fetched_at=datetime.now(timezone.utc),
            bytes_downloaded=30,
        ),
        first_url: FetchResponse(
            url=first_url,
            status_code=200,
            content_type="text/html",
            body=b"<html><body>About page with English content.</body></html>",
            rendered=False,
            redirects=[],
            fetched_at=datetime.now(timezone.utc),
            bytes_downloaded=31,
        ),
        second_url: FetchResponse(
            url=second_url,
            status_code=200,
            content_type="text/html",
            body=b"<html><body>Contact page with English contact info.</body></html>",
            rendered=False,
            redirects=[],
            fetched_at=datetime.now(timezone.utc),
            bytes_downloaded=33,
        ),
    }

    fetched_order: list[str] = []

    def fake_fetch(url: str, crawl_config: CrawlConfig) -> FetchResponse:
        fetched_order.append(url)
        return fetch_map[url]

    monkeypatch.setattr(miner, "_fetch_url", fake_fetch)

    config = CrawlConfig(
        institution_id="demo",
        seed_urls=[seed_url],
        allowed_domains=["example.edu"],
        disallowed_paths=[],
        include_patterns=[],
        max_pages=2,
        max_depth=2,
        ttl_days=1,
        respect_robots=True,
        respect_crawl_delay=False,
        page_timeout_seconds=5,
        render_timeout_seconds=5,
        crawl_time_budget_minutes=5,
        max_content_size_mb=5,
        retry_attempts=1,
    )

    miner.crawl_institution(config)

    assert fetched_order == [seed_url, first_url]
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


def test_cache_manager_records_dedup_metric(cache: CacheManager) -> None:
    metrics = MetricsCollector("demo")
    first = _snapshot("https://example.edu/page", "Hello world")
    duplicate = _snapshot("https://example.edu/page?ref=dup", "Hello world")
    cache.store(first, metrics=metrics)
    cache.store(duplicate, metrics=metrics)

    summary = metrics.finalize()
    assert summary.get("deduped") == 1


def test_cache_manager_expiration(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache", ttl_days=0)
    cache.store(_snapshot("https://example.edu/p", "data"))
    assert cache.get("https://example.edu/p") is None


def test_cache_manager_ttl_override(tmp_path: Path) -> None:
    cache = CacheManager(tmp_path / "cache", ttl_days=5)
    snapshot = _snapshot("https://example.edu/ttl", "Cached")
    cache.store(snapshot, ttl_seconds=0)
    assert cache.get(snapshot.url) is None


def test_content_processor_extracts_text(content_processor: ContentProcessor) -> None:
    html = (
        "<html><head><title>Sample</title>"
        "<meta name=\"description\" content=\"Example description\"></head>"
        "<body><p>Hello <b>World</b></p></body></html>"
    )
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
    assert meta.title == "Sample"
    assert meta.description == "Example description"
    assert snapshot.lang == "en"


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


def test_content_processor_records_pdf_metric(monkeypatch: pytest.MonkeyPatch) -> None:
    processor = ContentProcessor(
        language_allowlist=[],
        min_text_length=0,
        pdf_extraction_enabled=True,
        pdf_size_limit_mb=1,
    )
    metrics = MetricsCollector("demo")

    monkeypatch.setattr(processor, "_extract_text_from_pdf", lambda payload: "pdf text")

    processor.process(
        institution="demo",
        url="https://example.edu/doc",
        http_status=200,
        content_type="application/pdf",
        body=b"%PDF-1.4\n",
        metrics=metrics,
    )

    summary = metrics.finalize()
    assert summary.get("pdf_extracted") == 1


def test_content_processor_preserves_list_markers(content_processor: ContentProcessor) -> None:
    html = "<html><body><ul><li>First item</li><li>Second item</li></ul></body></html>"
    snapshot, _ = content_processor.process(
        institution="demo",
        url="https://example.edu/lists",
        http_status=200,
        content_type="text/html",
        body=html,
    )
    lines = [line for line in snapshot.text.splitlines() if line]
    assert "- First item" in lines
    assert "- Second item" in lines


def test_content_processor_decodes_declared_charset() -> None:
    processor = ContentProcessor(language_allowlist=[], min_text_length=0, pdf_extraction_enabled=False)
    body = "<html><body>caf\xe9</body></html>".encode("windows-1252")
    snapshot, _ = processor.process(
        institution="demo",
        url="https://example.edu/charset",
        http_status=200,
        content_type="text/html; charset=windows-1252",
        body=body,
    )
    assert "café" in snapshot.text


def test_content_processor_decodes_utf8_payload() -> None:
    processor = ContentProcessor(language_allowlist=[], min_text_length=0, pdf_extraction_enabled=False)
    body = "<html><body>こんにちは</body></html>".encode("utf-8")
    snapshot, _ = processor.process(
        institution="demo",
        url="https://example.edu/utf8",
        http_status=200,
        content_type="text/html",
        body=body,
    )
    assert "こんにちは" in snapshot.text


def test_robots_checker_allows_and_blocks(robots_checker: RobotsChecker) -> None:
    allowed = robots_checker.is_allowed("https://example.edu/index")
    blocked = robots_checker.is_allowed("https://example.edu/private/data")
    assert allowed is True
    assert blocked is False


def test_robots_default_fetcher_sets_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    from taxonomy.web_mining import robots as robots_module

    captured: dict[str, str] = {}

    class _Response:
        status_code = 200
        text = "User-agent: *\nAllow: /"

    def fake_get(url: str, headers: dict[str, str] | None = None, timeout: float | None = None) -> _Response:
        captured.update(headers or {})
        return _Response()

    monkeypatch.setattr(robots_module.requests, "get", fake_get)

    checker = RobotsChecker(user_agent="PolicyBot/2.0")
    status, body = checker._default_fetcher("https://example.edu/robots.txt")
    assert status == 200
    assert body.startswith("User-agent")
    assert captured.get("User-Agent") == "PolicyBot/2.0"


@pytest.mark.parametrize("status_code", [404, 500])
def test_robots_checker_allows_on_error(status_code: int) -> None:
    checker = RobotsChecker(
        user_agent="TestBot/1.0",
        cache_ttl_seconds=0,
        fetcher=lambda url: (status_code, ""),
    )
    assert checker.is_allowed("https://example.edu/protected") is True


def test_is_allowed_domain_strict_suffix_matching() -> None:
    allowed = ["example.edu"]
    assert is_allowed_domain("https://example.edu/page", allowed)
    assert is_allowed_domain("https://sub.example.edu/path", allowed)
    assert not is_allowed_domain("https://badexample.edu/page", allowed)
    assert is_allowed_domain("https://example.edu", [".example.edu"])


def test_build_web_miner_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = Path(__file__).resolve().parents[1] / "config" / "default.yaml"
    raw = yaml.safe_load(config_path.read_text())
    policies = load_policies(raw["policies"])

    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)

    miner = build_web_miner(policies, tmp_path)

    cache_settings = policies.web.cache
    expected_cache_dir = Path(cache_settings.cache_directory).expanduser()
    if not expected_cache_dir.is_absolute():
        expected_cache_dir = (tmp_path / expected_cache_dir).resolve()

    assert miner.cache.cache_dir == expected_cache_dir
    assert miner.content_processor.pdf_size_limit_mb == policies.web.content.pdf_size_limit_mb
    assert miner.robots_checker.cache_ttl_seconds == policies.web.robots_cache_ttl_hours * 3600
    assert miner.user_agent == policies.web.firecrawl.user_agent
    assert miner.rate_limiter.rate_per_second == float(policies.web.firecrawl.concurrency)


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
