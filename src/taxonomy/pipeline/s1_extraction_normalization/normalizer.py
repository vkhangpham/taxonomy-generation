"""Post-LLM normalization utilities for S1."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import List, Sequence

from taxonomy.config.policies import LabelPolicy
from taxonomy.entities.core import SupportStats
from taxonomy.utils.helpers import normalize_whitespace
from taxonomy.utils.logging import get_logger
from taxonomy.utils.normalization import to_canonical_form

from .extractor import RawExtractionCandidate


@dataclass
class NormalizedCandidate:
    """Intermediate representation produced by :class:`CandidateNormalizer`."""

    level: int
    label: str
    normalized: str
    parent_anchors: List[str]
    aliases: List[str]
    record_fingerprint: str
    institution: str
    support: SupportStats


class CandidateNormalizer:
    """Apply canonical normalization and alias enrichment to raw candidates."""

    def __init__(self, *, label_policy: LabelPolicy) -> None:
        self._policy = label_policy
        self._log = get_logger(module=__name__)

    def normalize(
        self,
        raw_candidates: Sequence[RawExtractionCandidate],
        *,
        level: int,
    ) -> List[NormalizedCandidate]:
        results: List[NormalizedCandidate] = []
        minimal = self._policy.minimal_canonical_form

        for raw in raw_candidates:
            canonical, generated_aliases = to_canonical_form(raw.label, level, self._policy)
            if not canonical:
                continue
            if len(canonical) < minimal.min_length or len(canonical) > minimal.max_length:
                self._log.debug(
                    "Skipping candidate outside length bounds",
                    label=raw.label,
                    normalized=canonical,
                    min=minimal.min_length,
                    max=minimal.max_length,
                )
                continue

            alias_order = []
            seen = set()
            for alias in [raw.label, raw.normalized, *raw.aliases, *generated_aliases]:
                cleaned = normalize_whitespace(alias.strip())
                if not cleaned or cleaned in seen:
                    continue
                alias_order.append(cleaned)
                seen.add(cleaned)

            parent_anchors = [normalize_whitespace(anchor.lower()) for anchor in raw.parents]
            if level > 0 and not parent_anchors:
                self._log.debug(
                    "Dropping candidate without parent anchors",
                    label=raw.label,
                    level=level,
                )
                continue

            fingerprint = self._fingerprint_record(raw)
            support = SupportStats(records=1, institutions=1, count=1)

            results.append(
                NormalizedCandidate(
                    level=level,
                    label=raw.label.strip(),
                    normalized=canonical,
                    parent_anchors=parent_anchors,
                    aliases=alias_order,
                    record_fingerprint=fingerprint,
                    institution=raw.source.provenance.institution,
                    support=support,
                )
            )
        return results

    @staticmethod
    def _fingerprint_record(raw: RawExtractionCandidate) -> str:
        material = "|".join(
            [
                normalize_whitespace(raw.source.text),
                raw.source.provenance.institution,
                raw.source.provenance.url or "",
            ]
        )
        digest = hashlib.sha1(material.encode("utf-8")).hexdigest()
        return f"record:{digest}"


__all__ = ["CandidateNormalizer", "NormalizedCandidate"]
