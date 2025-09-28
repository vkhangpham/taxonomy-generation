"""Candidate aggregation logic for S2 frequency filtering."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from taxonomy.config.policies import (
    FrequencyFilteringPolicy,
    LevelThreshold,
    LevelThresholds,
    NearDuplicateDedupPolicy,
)
from taxonomy.entities.core import Candidate, Rationale, SupportStats
from taxonomy.utils.helpers import normalize_whitespace
from taxonomy.utils.logging import get_logger

from .institution_resolver import InstitutionResolver


@dataclass
class CandidateEvidence:
    """Container pairing a candidate with supporting evidence metadata."""

    candidate: Candidate
    institutions: Set[str] = field(default_factory=set)
    record_fingerprints: Set[str] = field(default_factory=set)
    raw_payload: dict | None = None

    def placeholder_institutions(self, count: int) -> None:
        """Populate synthetic placeholders to honour recorded institution counts."""

        missing = max(0, count - len(self.institutions))
        for index in range(missing):
            self.institutions.add(f"unknown::{self.candidate.normalized}::{index}")

    def placeholder_records(self, count: int) -> None:
        missing = max(0, count - len(self.record_fingerprints))
        for index in range(missing):
            self.record_fingerprints.add(f"record::{self.candidate.normalized}::{index}")


@dataclass
class FrequencyDecision:
    """Decision emitted after applying level-specific thresholds."""

    candidate: Candidate
    rationale: Rationale
    institutions: List[str]
    record_fingerprints: List[str]
    weight: float
    passed: bool


@dataclass
class FrequencyAggregationResult:
    """Aggregated output including summary statistics."""

    kept: List[FrequencyDecision]
    dropped: List[FrequencyDecision]
    stats: Dict[str, int]


@dataclass
class _AggregationBucket:
    level: int
    normalized: str
    parents: Tuple[str, ...]
    primary_label: str
    aliases: Set[str] = field(default_factory=set)
    institutions: Set[str] = field(default_factory=set)
    record_fingerprints: Set[str] = field(default_factory=set)
    total_count: int = 0
    total_records: int = 0
    records_by_institution: Dict[str, Set[str]] = field(default_factory=dict)

    def as_candidate(self) -> Candidate:
        parents_list: Sequence[str] = list(self.parents)
        if self.level == 0:
            parents_list = []
        support = SupportStats(
            records=len(self.record_fingerprints) or self.total_records,
            institutions=len(self.institutions),
            count=self.total_count,
        )
        aliases = sorted(set(self.aliases | {self.primary_label}))
        return Candidate(
            level=self.level,
            label=self.primary_label,
            normalized=self.normalized,
            parents=list(parents_list),
            aliases=aliases,
            support=support,
        )


class CandidateAggregator:
    """Aggregate candidates and apply level-aware frequency thresholds."""

    def __init__(
        self,
        *,
        thresholds: LevelThresholds,
        resolver: InstitutionResolver,
        frequency_policy: FrequencyFilteringPolicy | None = None,
    ) -> None:
        self._thresholds = thresholds
        self._resolver = resolver
        self._frequency_policy = frequency_policy or FrequencyFilteringPolicy()
        self._near_duplicate_policy: NearDuplicateDedupPolicy | None = (
            self._frequency_policy.near_duplicate
            if self._frequency_policy.near_duplicate.enabled
            else None
        )
        self._unknown_institution_placeholder = (
            self._frequency_policy.unknown_institution_placeholder
        )
        self._log = get_logger(module=__name__)

    def aggregate(self, items: Iterable[CandidateEvidence]) -> FrequencyAggregationResult:
        buckets: Dict[Tuple[int, str, Tuple[str, ...]], _AggregationBucket] = {}
        total_inputs = 0
        for evidence in items:
            candidate = evidence.candidate
            total_inputs += 1
            key = self.generate_key(candidate)
            bucket = buckets.get(key)
            if bucket is None:
                bucket = _AggregationBucket(
                    level=candidate.level,
                    normalized=candidate.normalized.strip(),
                    parents=key[2],
                    primary_label=candidate.label,
                )
                buckets[key] = bucket
            bucket.aliases.update(candidate.aliases)
            bucket.aliases.add(candidate.label)
            bucket.total_count += max(candidate.support.count, 0)
            bucket.total_records += max(candidate.support.records, 0)

            canonical_institutions = {
                self._resolver.resolve_identity(name)
                for name in evidence.institutions
                if name
            }
            if not canonical_institutions:
                canonical_institutions = {self._unknown_institution_placeholder}
            bucket.institutions.update(canonical_institutions)
            bucket.record_fingerprints.update(evidence.record_fingerprints)
            for institution in canonical_institutions:
                record_set = bucket.records_by_institution.setdefault(
                    institution, set()
                )
                record_set.update(evidence.record_fingerprints)

        kept: List[FrequencyDecision] = []
        dropped: List[FrequencyDecision] = []
        institutions_histogram: Dict[int, Counter[int]] = defaultdict(Counter)
        dropped_insufficient_support = 0
        for bucket_key, bucket in buckets.items():
            self._apply_near_duplicate_dedup(bucket)
            candidate = bucket.as_candidate()
            threshold = self._threshold_for_level(bucket.level)
            support = candidate.support
            institutions_histogram[bucket.level][support.institutions] += 1
            passed = (
                support.institutions >= threshold.min_institutions
                and support.records >= threshold.min_src_count
            )
            if not passed and (
                support.institutions < threshold.min_institutions
                or support.records < threshold.min_src_count
            ):
                dropped_insufficient_support += 1
            rationale = self._build_rationale(candidate, threshold, passed, bucket)
            weight = support.weight()
            decision = FrequencyDecision(
                candidate=candidate,
                rationale=rationale,
                institutions=sorted(bucket.institutions),
                record_fingerprints=sorted(bucket.record_fingerprints),
                weight=weight,
                passed=passed,
            )
            if passed:
                kept.append(decision)
            else:
                dropped.append(decision)
            self._log.debug(
                "Evaluated frequency bucket",
                level=bucket.level,
                normalized=bucket.normalized,
                parents=list(bucket.parents),
                passed=passed,
                institutions=support.institutions,
                records=support.records,
                raw_count=support.count,
            )

        kept.sort(key=lambda d: (d.candidate.level, d.candidate.normalized, tuple(d.candidate.parents)))
        dropped.sort(key=lambda d: (d.candidate.level, d.candidate.normalized, tuple(d.candidate.parents)))

        histogram_stats = {
            str(level): {str(bucket_count): count for bucket_count, count in sorted(counter.items())}
            for level, counter in institutions_histogram.items()
        }
        stats = {
            "candidates_in": total_inputs,
            "aggregated_groups": len(buckets),
            "kept": len(kept),
            "dropped": len(dropped),
            "institutions_unique": sum(len(bucket.institutions) for bucket in buckets.values()),
            "dropped_insufficient_support": dropped_insufficient_support,
            "institutions_histogram": histogram_stats,
        }
        return FrequencyAggregationResult(kept=kept, dropped=dropped, stats=stats)

    def generate_key(self, candidate: Candidate) -> Tuple[int, str, Tuple[str, ...]]:
        normalized = normalize_whitespace(candidate.normalized).lower()
        parents = tuple(
            normalize_whitespace(parent).lower()
            for parent in (candidate.parents or [])
        )
        if candidate.level == 0:
            parents = tuple()
        return candidate.level, normalized, parents

    def _threshold_for_level(self, level: int) -> LevelThreshold:
        if level == 0:
            return self._thresholds.level_0
        if level == 1:
            return self._thresholds.level_1
        if level == 2:
            return self._thresholds.level_2
        if level == 3:
            return self._thresholds.level_3
        raise ValueError(f"Unsupported level for frequency thresholds: {level}")

    def _build_rationale(
        self,
        candidate: Candidate,
        threshold: LevelThreshold,
        passed: bool,
        bucket: _AggregationBucket,
    ) -> Rationale:
        support = candidate.support
        reasons = [
            (
                f"institutions={support.institutions} (min {threshold.min_institutions}), "
                f"records={support.records} (min {threshold.min_src_count}), "
                f"count={support.count}, "
                f"weight={support.weight():.2f}"
            ),
            "institutions_list=" + ", ".join(sorted(bucket.institutions)) if bucket.institutions else "institutions_list=<unknown>",
        ]
        reasons.append(f"weight_formula={threshold.weight_formula}")
        return Rationale(
            passed_gates={"frequency": passed},
            reasons=reasons,
            thresholds={
                "min_institutions": float(threshold.min_institutions),
                "min_src_count": float(threshold.min_src_count),
            },
        )

    def _apply_near_duplicate_dedup(self, bucket: _AggregationBucket) -> None:
        policy = self._near_duplicate_policy
        if not policy or not bucket.records_by_institution:
            return

        deduped_records: Set[str] = set()
        updated_mapping: Dict[str, Set[str]] = {}
        for institution, records in bucket.records_by_institution.items():
            if not records:
                updated_mapping[institution] = set()
                continue
            seen_keys: Dict[str, str] = {}
            collapsed_records: Set[str] = set()
            for fingerprint in sorted(records):
                key = self._fingerprint_key(fingerprint, policy)
                if key not in seen_keys:
                    seen_keys[key] = fingerprint
                    collapsed_records.add(fingerprint)
            updated_mapping[institution] = collapsed_records
            deduped_records.update(collapsed_records)

        bucket.records_by_institution = updated_mapping
        bucket.record_fingerprints = deduped_records

    def _fingerprint_key(self, fingerprint: str, policy: NearDuplicateDedupPolicy) -> str:
        key = fingerprint
        for delimiter in policy.prefix_delimiters:
            if delimiter and delimiter in key:
                prefix = key.split(delimiter, 1)[0]
                if len(prefix) >= policy.min_prefix_length:
                    key = prefix
                    break
        if policy.strip_numeric_suffix:
            key = re.sub(r"[-_]?v?\d+$", "", key)
            key = re.sub(r"[-_][0-9a-f]{6,}$", "", key)
        return key


__all__ = [
    "CandidateAggregator",
    "CandidateEvidence",
    "FrequencyDecision",
    "FrequencyAggregationResult",
]
