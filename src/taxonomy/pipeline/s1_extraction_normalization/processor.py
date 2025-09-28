"""Coordinator for the S1 extraction + normalization pipeline.

Unresolved parent anchors are tagged with the `UNRESOLVED:` prefix so downstream
consumers can distinguish resolved identifiers from raw anchors."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Sequence, Tuple

from taxonomy.entities.core import Candidate, SourceRecord, SupportStats
from taxonomy.utils.helpers import normalize_whitespace
from taxonomy.utils.logging import get_logger

from .extractor import ExtractionProcessor
from .normalizer import CandidateNormalizer, NormalizedCandidate
from .parent_index import ParentIndex


@dataclass
class AggregatedCandidate:
    """Internal accumulator used while merging duplicates."""

    level: int
    normalized: str
    parents: Tuple[str, ...]
    primary_label: str
    aliases: set[str] = field(default_factory=set)
    record_fingerprints: set[str] = field(default_factory=set)
    institutions: set[str] = field(default_factory=set)
    total_count: int = 0


class S1Processor:
    """Run the full S1 pipeline for a batch of source records."""

    def __init__(
        self,
        *,
        extractor: ExtractionProcessor,
        normalizer: CandidateNormalizer,
        parent_index: ParentIndex,
    ) -> None:
        self._extractor = extractor
        self._normalizer = normalizer
        self._parent_index = parent_index
        self._log = get_logger(module=__name__)

    def process_level(
        self,
        records: Sequence[SourceRecord],
        *,
        level: int,
        previous_candidates: Sequence = (),
    ) -> List[Candidate]:
        """Execute extraction followed by normalization and aggregation."""

        if previous_candidates:
            self._parent_index.build_index(previous_candidates)

        raw = self._extractor.extract_candidates(records, level=level)
        normalized = self._normalizer.normalize(raw, level=level)
        aggregated = self._aggregate(normalized)
        return self._materialize(aggregated)

    def _aggregate(self, normalized: Sequence[NormalizedCandidate]) -> List[AggregatedCandidate]:
        buckets: dict[Tuple[str, Tuple[str, ...]], AggregatedCandidate] = {}
        for candidate in normalized:
            parents = self._resolve_parents(candidate)
            key = (candidate.normalized, parents)
            if key not in buckets:
                buckets[key] = AggregatedCandidate(
                    level=candidate.level,
                    normalized=candidate.normalized,
                    parents=parents,
                    primary_label=candidate.label,
                )
            bucket = buckets[key]
            bucket.aliases.update(candidate.aliases)
            bucket.aliases.add(candidate.label)
            bucket.record_fingerprints.add(candidate.record_fingerprint)
            bucket.institutions.add(candidate.institution)
            bucket.total_count += candidate.support.count or 1
        return list(buckets.values())

    def _resolve_parents(self, candidate: NormalizedCandidate) -> Tuple[str, ...]:
        if candidate.level == 0:
            return tuple()
        resolved: list[str] = []
        unresolved: list[str] = []
        for anchor in candidate.parent_anchors:
            matches = self._parent_index.resolve_anchor(anchor, candidate.level)
            if matches:
                resolved.extend(matches)
            else:
                unresolved.append(f"UNRESOLVED:{normalize_whitespace(anchor)}")
        parent_values = resolved + unresolved
        cleaned = [normalize_whitespace(value) for value in parent_values if value]
        return tuple(dict.fromkeys(cleaned))

    def _materialize(self, aggregated: Iterable[AggregatedCandidate]) -> List[Candidate]:
        results: List[Candidate] = []
        for item in aggregated:
            support = SupportStats(
                records=len(item.record_fingerprints),
                institutions=len(item.institutions),
                count=item.total_count,
            )
            aliases = sorted(dict.fromkeys(item.aliases))
            candidates_parents = list(item.parents)
            if item.level == 0:
                candidates_parents = []
            try:
                results.append(
                    Candidate(
                        level=item.level,
                        label=item.primary_label,
                        normalized=item.normalized,
                        parents=candidates_parents,
                        aliases=aliases,
                        support=support,
                    )
                )
            except ValueError as exc:
                self._log.warning(
                    "Discarding candidate failing validation",
                    error=str(exc),
                    label=item.primary_label,
                    level=item.level,
                )
        results.sort(key=lambda cand: (cand.normalized, tuple(cand.parents)))
        return results


__all__ = ["S1Processor", "AggregatedCandidate"]
