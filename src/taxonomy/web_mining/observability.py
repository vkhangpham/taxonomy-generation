"""Observability primitives for web mining operations."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import mean
from typing import DefaultDict, Dict, Iterable, List

from taxonomy.utils.logging import get_logger


@dataclass
class MetricsCollector:
    """Accumulates counters and timings during a crawl session."""

    institution_id: str
    _counters: Counter = field(default_factory=Counter)
    _timings: DefaultDict[str, List[float]] = field(default_factory=lambda: defaultdict(list))
    _samples: List[str] = field(default_factory=list)
    _logger = get_logger(component="web_mining")

    def increment(self, metric: str, amount: int = 1) -> None:
        self._counters[metric] += amount
        self._logger.debug("Increment metric", metric=metric, amount=amount)

    def record_timing(self, metric: str, seconds: float) -> None:
        self._timings[metric].append(seconds)
        self._logger.debug("Record timing", metric=metric, seconds=seconds)

    def sample_snapshot(self, snapshot_id: str, *, limit: int = 5) -> None:
        if len(self._samples) < limit:
            self._samples.append(snapshot_id)

    def record_cache_hit(self) -> None:
        self.increment("cache_hits")

    def record_cache_miss(self) -> None:
        self.increment("cache_misses")

    def record_deduped(self) -> None:
        self.increment("deduped")

    def record_pdf_extracted(self) -> None:
        self.increment("pdf_extracted")

    def record_error(self, error_type: str) -> None:
        key = f"error::{error_type}"
        self.increment(key)
        self.increment("errors")

    def record_fetch(self, *, rendered: bool = False, robots_blocked: bool = False) -> None:
        self.increment("urls_fetched")
        if rendered:
            self.increment("rendered")
        if robots_blocked:
            self.increment("robots_blocked")

    def record_budget(self, *, pages_fetched: int, bytes_downloaded: int, elapsed_seconds: float) -> None:
        self._counters["budget_pages_fetched"] = pages_fetched
        self._counters["budget_bytes_downloaded"] = bytes_downloaded
        self._counters["budget_elapsed_seconds"] = elapsed_seconds

    def finalize(self) -> Dict[str, float | int | List[str]]:
        summary: Dict[str, float | int | List[str]] = dict(self._counters)
        for name, values in self._timings.items():
            summary[f"{name}_avg"] = mean(values)
            summary[f"{name}_max"] = max(values)
            summary[f"{name}_min"] = min(values)
        summary["samples"] = list(self._samples)
        summary["finalized_at"] = datetime.now(timezone.utc).isoformat()
        self._logger.info("Crawl metrics finalized", institution_id=self.institution_id, metrics=summary)
        return summary


__all__ = ["MetricsCollector"]
