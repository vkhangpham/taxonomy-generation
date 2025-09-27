"""Snapshot loading utilities for S0 raw extraction."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from ...config.settings import Settings, get_settings
from ...entities.core import PageSnapshot
from ...utils import ensure_directory, get_logger


@dataclass
class SnapshotRecord:
    """Snapshot wrapper with auxiliary metadata."""

    snapshot: PageSnapshot
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def language_confidence(self) -> Optional[float]:
        value = self.metadata.get("language_confidence")
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None


@dataclass
class LoaderMetrics:
    """Capture statistics about snapshot loading."""

    files_processed: int = 0
    snapshots_loaded: int = 0
    validation_errors: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "files_processed": self.files_processed,
            "snapshots_loaded": self.snapshots_loaded,
            "validation_errors": self.validation_errors,
        }


class SnapshotLoader:
    """Utility capable of loading snapshots from files or iterables."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        enable_cache: bool = False,
        quarantine_path: Path | None = None,
        quarantine_enabled: bool | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.enable_cache = enable_cache
        self.metrics = LoaderMetrics()
        self._logger = get_logger(module=__name__)
        self._cache: Dict[Path, List[SnapshotRecord]] = {}
        self._quarantine_dir: Path | None = None
        self._quarantine_file: Path | None = None

        effective_quarantine = (
            quarantine_enabled
            if quarantine_enabled is not None
            else self.settings.observability.quarantine_enabled
        )
        if effective_quarantine:
            candidate = quarantine_path or self.settings.observability.resolve_directory(
                self.settings.paths
            )
            if candidate is not None:
                candidate_path = Path(candidate)
                if candidate_path.suffix:
                    self._quarantine_file = candidate_path
                    self._quarantine_dir = candidate_path.parent
                else:
                    self._quarantine_dir = candidate_path
                    self._quarantine_file = candidate_path / "snapshots.quarantine.jsonl"

        self._quarantine_enabled = effective_quarantine and self._quarantine_file is not None

    def load_from_jsonl(self, file_path: Path | str) -> Iterator[SnapshotRecord]:
        path = Path(file_path)
        if self.enable_cache and path in self._cache:
            for record in self._cache[path]:
                yield record
            return

        if not path.exists():
            raise FileNotFoundError(f"Snapshot file not found: {path}")

        records: List[SnapshotRecord] = []
        self.metrics.files_processed += 1
        with path.open("r", encoding="utf-8") as handle:
            for line_no, raw_line in enumerate(handle, start=1):
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    payload = json.loads(stripped)
                except json.JSONDecodeError as exc:
                    self.metrics.validation_errors += 1
                    self._logger.warning(
                        "Discarding malformed JSON line",
                        file=str(path),
                        line=line_no,
                        error=str(exc),
                    )
                    self._record_quarantine(
                        file=str(path),
                        line=line_no,
                        url=None,
                        institution=None,
                        error=str(exc),
                        raw=stripped,
                    )
                    continue
                record = self._create_record(payload, source=str(path), line=line_no)
                if record is None:
                    continue
                self.metrics.snapshots_loaded += 1
                records.append(record)
                yield record

        if self.enable_cache:
            self._cache[path] = list(records)

    def load_from_directory(self, directory_path: Path | str, pattern: str = "*.jsonl") -> Iterator[SnapshotRecord]:
        directory = Path(directory_path)
        if not directory.exists():
            raise FileNotFoundError(f"Snapshot directory not found: {directory}")
        for file_path in sorted(directory.rglob(pattern)):
            yield from self.load_from_jsonl(file_path)

    def filter_snapshots(
        self,
        snapshots: Iterable[SnapshotRecord],
        *,
        institution: str | None = None,
        min_status: int | None = 200,
        max_status: int | None = 299,
    ) -> Iterator[SnapshotRecord]:
        for record in snapshots:
            snapshot = record.snapshot
            if institution and snapshot.institution != institution:
                continue
            status = snapshot.http_status
            if min_status is not None and status < min_status:
                continue
            if max_status is not None and status > max_status:
                continue
            yield record

    def validate_snapshots(self, snapshots: Iterable[SnapshotRecord]) -> Iterator[SnapshotRecord]:
        for record in snapshots:
            try:
                PageSnapshot.model_validate(record.snapshot.model_dump())
            except Exception as exc:  # pragma: no cover - defensive log path
                self.metrics.validation_errors += 1
                self._logger.warning(
                    "Encountered invalid snapshot during validation",
                    url=record.snapshot.url,
                    institution=record.snapshot.institution,
                    error=str(exc),
                )
                self._record_quarantine(
                    file=None,
                    line=None,
                    url=record.snapshot.url,
                    institution=record.snapshot.institution,
                    error=str(exc),
                    raw=record.snapshot.model_dump(mode="json"),
                )
                continue
            yield record

    def _create_record(
        self,
        payload: Dict[str, Any],
        *,
        source: str,
        line: int,
    ) -> SnapshotRecord | None:
        if "snapshot" in payload and isinstance(payload["snapshot"], dict):
            snapshot_payload = payload["snapshot"]
            metadata = {k: v for k, v in payload.items() if k != "snapshot"}
        else:
            snapshot_payload = payload
            metadata = {
                key: value
                for key, value in payload.items()
                if key not in PageSnapshot.model_fields
            }
        try:
            snapshot = PageSnapshot.model_validate(snapshot_payload)
        except Exception as exc:
            self.metrics.validation_errors += 1
            self._logger.warning(
                "Failed to validate snapshot payload",
                file=source,
                line=line,
                error=str(exc),
            )
            snapshot_url = snapshot_payload.get("url") if isinstance(snapshot_payload, dict) else None
            institution = snapshot_payload.get("institution") if isinstance(snapshot_payload, dict) else None
            self._record_quarantine(
                file=source,
                line=line,
                url=snapshot_url,
                institution=institution,
                error=str(exc),
                raw=snapshot_payload,
            )
            return None
        return SnapshotRecord(snapshot=snapshot, metadata=metadata)

    @property
    def quarantine_file(self) -> Optional[Path]:
        return self._quarantine_file

    def _record_quarantine(
        self,
        *,
        file: Optional[str],
        line: Optional[int],
        url: Optional[str],
        institution: Optional[str],
        error: str,
        raw: Any,
    ) -> None:
        if not self._quarantine_enabled or self._quarantine_file is None:
            return

        try:
            ensure_directory(self._quarantine_dir or self._quarantine_file.parent)
            entry = {
                "file": file,
                "line": line,
                "url": url,
                "institution": institution,
                "error": error,
                "raw": raw,
            }
            with self._quarantine_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False))
                handle.write("\n")
        except Exception:  # pragma: no cover - quarantine must not break pipeline
            self._logger.exception(
                "Failed to write quarantine artefact", path=str(self._quarantine_file)
            )


__all__ = ["SnapshotLoader", "SnapshotRecord", "LoaderMetrics"]
