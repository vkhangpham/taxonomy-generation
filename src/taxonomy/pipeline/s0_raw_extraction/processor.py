"""S0 raw extraction processor converting snapshots to source records."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Protocol, Sequence, runtime_checkable

from ...config.policies import RawExtractionPolicy
from ...entities.core import PageSnapshot, Provenance, SourceMeta, SourceRecord
from ...utils import find_duplicates, get_logger
from .segmenter import ContentSegmenter, SegmentedBlock, SegmentationResult


@dataclass
class ProcessingMetrics:
    """Tracks statistics collected while processing snapshots."""

    pages_seen: int = 0
    pages_failed: int = 0
    pages_language_skipped: int = 0
    pages_emitted: int = 0
    blocks_total: int = 0
    blocks_kept: int = 0
    blocks_filtered_length: int = 0
    blocks_deduped: int = 0
    boilerplate_removed: int = 0
    language_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def as_dict(self) -> Dict[str, Any]:
        return {
            "pages_seen": self.pages_seen,
            "pages_failed": self.pages_failed,
            "pages_language_skipped": self.pages_language_skipped,
            "pages_emitted": self.pages_emitted,
            "blocks_total": self.blocks_total,
            "blocks_kept": self.blocks_kept,
            "blocks_filtered_length": self.blocks_filtered_length,
            "blocks_deduped": self.blocks_deduped,
            "boilerplate_removed": self.boilerplate_removed,
            "language_counts": dict(self.language_counts),
        }


@runtime_checkable
class SnapshotEnvelope(Protocol):
    """Protocol describing snapshot objects with metadata."""

    snapshot: PageSnapshot
    metadata: Dict[str, Any]


class RawExtractionProcessor:
    """Pipeline component that emits SourceRecords from PageSnapshots."""

    def __init__(self, policy: RawExtractionPolicy, segmenter: ContentSegmenter | None = None) -> None:
        self.policy = policy
        self.segmenter = segmenter or ContentSegmenter(policy)
        self.metrics = ProcessingMetrics()
        self._logger = get_logger(module=__name__)

    def process(self, entry: PageSnapshot | SnapshotEnvelope) -> List[SourceRecord]:
        """Process a single snapshot or envelope into SourceRecords."""

        self.metrics.pages_seen += 1
        snapshot, metadata = self._unwrap(entry)
        self.metrics.language_counts[snapshot.lang] += 1

        try:
            if not self._language_allowed(snapshot, metadata):
                self.metrics.pages_language_skipped += 1
                return []

            segmentation = self.segmenter.segment(snapshot)
            self.metrics.blocks_total += len(segmentation.blocks)
            self.metrics.boilerplate_removed += segmentation.boilerplate_removed

            length_filtered = self._filter_by_length(segmentation.blocks)
            deduplicated = self._deduplicate(length_filtered)

            self.metrics.blocks_kept += len(deduplicated)

            if not deduplicated:
                return []

            records = self._create_source_records(deduplicated, snapshot, metadata)
            if records:
                self.metrics.pages_emitted += 1
            return records
        except Exception as exc:  # pragma: no cover - defensive safeguard
            self.metrics.pages_failed += 1
            self._logger.exception(
                "Failed to process snapshot",
                url=snapshot.url,
                institution=snapshot.institution,
                error=str(exc),
            )
            return []

    def process_many(
        self, entries: Iterable[PageSnapshot | SnapshotEnvelope]
    ) -> Iterable[SourceRecord]:
        """Process a collection of snapshots yielding SourceRecords lazily."""

        for entry in entries:
            for record in self.process(entry):
                yield record

    def _unwrap(self, entry: PageSnapshot | SnapshotEnvelope) -> tuple[PageSnapshot, Dict[str, Any]]:
        if isinstance(entry, PageSnapshot):
            return entry, {}
        if isinstance(entry, SnapshotEnvelope):
            return entry.snapshot, dict(getattr(entry, "metadata", {}))
        raise TypeError(f"Unsupported snapshot entry type: {type(entry)!r}")

    def _language_allowed(self, snapshot: PageSnapshot, metadata: Dict[str, Any]) -> bool:
        if not self.policy.target_language:
            return True
        target = self.policy.target_language.lower()
        snapshot_lang = (snapshot.lang or "und").lower()
        base_lang = snapshot_lang.split("-")[0]
        confidence = metadata.get("language_confidence")
        try:
            confidence_value = float(confidence) if confidence is not None else 1.0
        except (TypeError, ValueError):
            confidence_value = 0.0
        if confidence_value < self.policy.language_confidence_threshold:
            return False
        if target == "any":
            return True
        return base_lang == target

    def _filter_by_length(self, blocks: Sequence[SegmentedBlock]) -> List[SegmentedBlock]:
        filtered: List[SegmentedBlock] = []
        for block in blocks:
            length = len(block.text)
            if length < self.policy.min_chars or length > self.policy.max_chars:
                self.metrics.blocks_filtered_length += 1
                continue
            filtered.append(block)
        return filtered

    def _deduplicate(self, blocks: Sequence[SegmentedBlock]) -> List[SegmentedBlock]:
        if not self.policy.intra_page_dedup_enabled or len(blocks) <= 1:
            return list(blocks)
        texts = [block.text for block in blocks]
        duplicates = set(
            find_duplicates(
                texts,
                threshold=self.policy.similarity_threshold,
                method=self.policy.similarity_method,
            )
        )
        if not duplicates:
            return list(blocks)
        deduplicated: List[SegmentedBlock] = []
        for idx, block in enumerate(blocks):
            if idx in duplicates:
                self.metrics.blocks_deduped += 1
                continue
            deduplicated.append(block)
        return deduplicated

    def _create_source_records(
        self,
        blocks: Sequence[SegmentedBlock],
        snapshot: PageSnapshot,
        metadata: Dict[str, Any],
    ) -> List[SourceRecord]:
        records: List[SourceRecord] = []
        canonical_url = snapshot.canonical_url or snapshot.url
        language_confidence = metadata.get("language_confidence")
        confidence_hint = None
        if language_confidence is not None:
            try:
                confidence_hint = f"{float(language_confidence):.3f}"
            except (TypeError, ValueError):
                confidence_hint = None
        hints_base = {
            "source": "web",
            "level": "S0",
        }
        if confidence_hint is not None:
            hints_base["language_confidence"] = confidence_hint
        for block in blocks:
            hints = dict(hints_base)
            hints.update({
                "block_type": block.block_type,
                "order": str(block.order),
            })
            record = SourceRecord(
                text=block.text,
                provenance=Provenance(
                    institution=snapshot.institution,
                    url=canonical_url,
                    section=block.section,
                    fetched_at=snapshot.fetched_at,
                ),
                meta=SourceMeta(
                    language=snapshot.lang,
                    hints={k: v for k, v in hints.items() if v},
                ),
            )
            records.append(record)
        return records


__all__ = ["RawExtractionProcessor", "ProcessingMetrics"]
