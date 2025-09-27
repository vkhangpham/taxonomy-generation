"""TTL cache with checksum-based deduplication for page snapshots."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

from pydantic import ValidationError

from taxonomy.entities.core import PageSnapshot
from taxonomy.utils.logging import get_logger

from .models import CacheEntry

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .observability import MetricsCollector


class CacheManager:
    """Persist and retrieve snapshots with TTL and deduplication."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        ttl_days: int = 14,
        cleanup_interval_hours: int = 12,
        max_cache_size_gb: int | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_days * 24 * 3600
        self.cleanup_interval = timedelta(hours=cleanup_interval_hours)
        self.max_cache_size_gb = max_cache_size_gb
        self._index_file = cache_dir / "index.json"
        self._lock = threading.RLock()
        self._index: Dict[str, CacheEntry] = {}
        self._checksum_index: Dict[str, CacheEntry] = {}
        self._last_cleanup = datetime.now(timezone.utc)
        self._stats = {"hits": 0, "misses": 0, "deduped": 0}
        self._logger = get_logger(component="cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._load_index()

    def _load_index(self) -> None:
        if not self._index_file.exists():
            return
        try:
            data = json.loads(self._index_file.read_text())
        except json.JSONDecodeError:  # pragma: no cover - defensive
            self._logger.warning("Cache index corrupted; starting fresh")
            return
        for entry_dict in data.get("entries", []):
            try:
                entry = CacheEntry.model_validate(entry_dict)
            except ValidationError:  # pragma: no cover - defensive
                continue
            self._index[entry.url] = entry
            for alias in entry.alias_urls:
                self._index[alias] = entry
            self._checksum_index[entry.checksum] = entry

    def _persist_index(self) -> None:
        unique_entries = {entry.checksum: entry for entry in self._index.values()}.values()
        payload = {
            "entries": [entry.model_dump(mode="json") for entry in unique_entries],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._index_file.write_text(json.dumps(payload, indent=2))

    def _snapshot_path(self, checksum: str) -> Path:
        return self.cache_dir / f"{checksum}.json"

    def _is_expired(self, entry: CacheEntry) -> bool:
        return entry.is_expired(datetime.now(timezone.utc))

    def get(self, url: str) -> Optional[PageSnapshot]:
        with self._lock:
            entry = self._index.get(url)
            if not entry:
                self._stats["misses"] += 1
                return None
            if self._is_expired(entry):
                self._evict(entry)
                self._stats["misses"] += 1
                return None
            snapshot_path = self._snapshot_path(entry.checksum)
            if not snapshot_path.exists():
                self._stats["misses"] += 1
                return None
            try:
                payload = json.loads(snapshot_path.read_text())
                snapshot = PageSnapshot.model_validate(payload)
            except (json.JSONDecodeError, ValidationError):  # pragma: no cover - defensive
                self._logger.warning("Failed to deserialize cached snapshot", url=url)
                self._stats["misses"] += 1
                return None
            self._stats["hits"] += 1
            snapshot.meta.alias_urls = sorted(set(entry.alias_urls))
            return snapshot

    def store(
        self,
        snapshot: PageSnapshot,
        *,
        metrics: "MetricsCollector" | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        with self._lock:
            entry = self._checksum_index.get(snapshot.checksum)
            now = datetime.now(timezone.utc)
            ttl_to_use = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
            if entry:
                if snapshot.url not in entry.alias_urls:
                    entry.alias_urls.append(snapshot.url)
                    entry.alias_urls = sorted(set(entry.alias_urls))
                    self._stats["deduped"] += 1
                    if metrics is not None:
                        metrics.record_deduped()
                self._index[snapshot.url] = entry
                entry.stored_at = now
                if ttl_seconds is not None:
                    entry.ttl_seconds = ttl_to_use
            else:
                html_bytes = len(snapshot.html.encode("utf-8")) if snapshot.html else 0
                entry = CacheEntry(
                    url=snapshot.url,
                    alias_urls=[snapshot.url],
                    checksum=snapshot.checksum,
                    stored_at=now,
                    ttl_seconds=ttl_to_use,
                    size_bytes=len(snapshot.text.encode("utf-8")) + html_bytes,
                )
                self._index[snapshot.url] = entry
                self._checksum_index[snapshot.checksum] = entry
            for alias in entry.alias_urls:
                self._index[alias] = entry
            snapshot.meta.alias_urls = sorted(set(entry.alias_urls))
            snapshot_path = self._snapshot_path(snapshot.checksum)
            snapshot_path.write_text(json.dumps(snapshot.model_dump(mode="json"), indent=2))
            self._maybe_cleanup_locked(now)
            self._persist_index()

    def _maybe_cleanup_locked(self, now: datetime) -> None:
        if now - self._last_cleanup < self.cleanup_interval:
            return
        unique_entries = list({entry.checksum: entry for entry in self._index.values()}.values())
        expired = [entry for entry in unique_entries if self._is_expired(entry)]
        for entry in expired:
            self._evict(entry)
        if self.max_cache_size_gb:
            limit_bytes = self.max_cache_size_gb * 1024 * 1024 * 1024
            entries = sorted(unique_entries, key=lambda e: e.stored_at)
            total_bytes = sum(entry.size_bytes for entry in entries)
            for entry in entries:
                if total_bytes <= limit_bytes:
                    break
                self._evict(entry)
                total_bytes -= entry.size_bytes
        self._last_cleanup = now

    def _evict(self, entry: CacheEntry) -> None:
        for url in list(self._index.keys()):
            if self._index[url] is entry:
                self._index.pop(url, None)
        self._checksum_index.pop(entry.checksum, None)
        snapshot_path = self._snapshot_path(entry.checksum)
        if snapshot_path.exists():
            snapshot_path.unlink()
        self._persist_index()

    def stats(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._stats)


__all__ = ["CacheManager"]
