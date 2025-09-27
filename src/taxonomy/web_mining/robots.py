"""Robots.txt compliance helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, Tuple
from urllib.parse import urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests

from taxonomy.utils.logging import get_logger

from .models import RobotsInfo


@dataclass
class RobotsCacheEntry:
    parser: RobotFileParser
    info: RobotsInfo
    fetched_at: datetime


class RobotsChecker:
    """Parses robots.txt files and enforces access rules."""

    def __init__(
        self,
        *,
        user_agent: str = "TaxonomyBot/1.0",
        cache_ttl_seconds: int = 3600,
        request_timeout_seconds: float = 10.0,
        fetcher: Callable[[str], Tuple[int, str]] | None = None,
    ) -> None:
        self.user_agent = user_agent
        self.cache_ttl_seconds = cache_ttl_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self._fetcher = fetcher or self._default_fetcher
        self._cache: Dict[str, RobotsCacheEntry] = {}
        self._logger = get_logger(component="robots", user_agent=user_agent)

    def _default_fetcher(self, url: str) -> Tuple[int, str]:
        response = requests.get(url, timeout=self.request_timeout_seconds)
        return response.status_code, response.text

    def _robots_url(self, url: str) -> str:
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))

    def _get_parser(self, url: str) -> RobotsCacheEntry:
        robots_url = self._robots_url(url)
        cache_entry = self._cache.get(robots_url)
        if cache_entry and (datetime.now(timezone.utc) - cache_entry.fetched_at).total_seconds() < self.cache_ttl_seconds:
            return cache_entry

        status_code, body = self._fetcher(robots_url)
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(body.splitlines())
        crawl_delay = parser.crawl_delay(self.user_agent)
        entry = RobotsCacheEntry(
            parser=parser,
            info=RobotsInfo(
                robots_url=robots_url,
                crawl_delay=crawl_delay,
                sitemaps=list(parser.site_maps() or []),
                fetched_at=datetime.now(timezone.utc),
            ),
            fetched_at=datetime.now(timezone.utc),
        )
        self._cache[robots_url] = entry
        self._logger.debug("Fetched robots.txt", robots_url=robots_url, status_code=status_code)
        return entry

    def is_allowed(self, url: str) -> bool:
        try:
            entry = self._get_parser(url)
        except Exception as exc:  # pragma: no cover - defensive
            self._logger.warning("Robots fetch failed; allowing by default", error=str(exc))
            return True
        allowed = entry.parser.can_fetch(self.user_agent, url)
        if not allowed:
            entry.info.disallowed.append(url)
        else:
            entry.info.allowed.append(url)
        return allowed

    def crawl_delay(self, url: str) -> float | None:
        entry = self._get_parser(url)
        return entry.info.crawl_delay

    def info(self, url: str) -> RobotsInfo:
        entry = self._get_parser(url)
        return entry.info


__all__ = ["RobotsChecker"]
