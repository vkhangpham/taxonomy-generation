"""Evidence indexing helpers for validation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, List, Sequence, Tuple
from urllib.parse import urlparse

from ...config.policies import ValidationPolicy
from ...entities.core import PageSnapshot


@dataclass
class EvidenceSnippet:
    """Captured snippet supporting a concept."""

    text: str
    url: str
    institution: str
    score: float


class EvidenceIndexer:
    """Index page snapshots for fast evidence lookup."""

    def __init__(self, policy: ValidationPolicy) -> None:
        self._policy = policy
        self._built = False
        self._snapshots: List[PageSnapshot] = []
        self._by_institution: Dict[str, List[PageSnapshot]] = {}
        self._by_domain: Dict[str, List[PageSnapshot]] = {}

    def build_index(self, snapshots: Sequence[PageSnapshot]) -> None:
        self._snapshots = list(snapshots)
        self._by_institution.clear()
        self._by_domain.clear()
        for snapshot in self._snapshots:
            self._by_institution.setdefault(snapshot.institution, []).append(snapshot)
            domain = self._extract_domain(snapshot.canonical_url or snapshot.url)
            self._by_domain.setdefault(domain, []).append(snapshot)
        self._built = True

    def search_evidence(
        self,
        concept_label: str,
        institution_filter: str | None = None,
    ) -> List[PageSnapshot]:
        self._ensure_built()
        haystacks: Iterable[PageSnapshot]
        if institution_filter:
            haystacks = self._by_institution.get(institution_filter, [])
        else:
            haystacks = self._snapshots
        label_lower = concept_label.lower()
        results = [snap for snap in haystacks if label_lower in snap.text.lower()]
        return results

    def extract_snippets(
        self,
        snapshot: PageSnapshot,
        concept_label: str,
        max_length: int | None = None,
    ) -> List[EvidenceSnippet]:
        max_length = max_length or self._policy.web.snippet_max_length
        text_lower = snapshot.text.lower()
        label_lower = concept_label.lower()
        snippets: List[EvidenceSnippet] = []
        start = 0
        while True:
            index = text_lower.find(label_lower, start)
            if index == -1:
                break
            begin = max(0, index - max_length // 2)
            end = min(len(snapshot.text), index + len(label_lower) + max_length // 2)
            snippet_text = snapshot.text[begin:end].strip()
            score = self.score_relevance(snippet_text, concept_label, snapshot)
            snippets.append(
                EvidenceSnippet(
                    text=snippet_text,
                    url=snapshot.canonical_url or snapshot.url,
                    institution=snapshot.institution,
                    score=score,
                )
            )
            start = index + len(label_lower)
        return snippets

    def score_relevance(
        self, snippet: str, concept_label: str, snapshot: PageSnapshot
    ) -> float:
        label_lower = concept_label.lower()
        score = 1.0 if label_lower in snippet.lower() else 0.5
        score += 0.2 if snapshot.institution and snapshot.institution.lower() in snippet.lower() else 0.0
        score += 0.3 * self.assess_authority(snapshot)
        return min(score, 1.5)

    def assess_authority(self, snapshot: PageSnapshot) -> float:
        domain = self._extract_domain(snapshot.canonical_url or snapshot.url)
        authoritative_domains = self._authoritative_domains()
        if any(domain == auth or domain.endswith(f".{auth}") for auth in authoritative_domains):
            return 1.0
        if domain.endswith(".edu") or domain.endswith(".gov"):
            return 0.8
        return 0.3

    def aggregate_evidence(
        self,
        concept_label: str,
        snapshots: Sequence[PageSnapshot],
    ) -> List[EvidenceSnippet]:
        snippets: List[EvidenceSnippet] = []
        for snapshot in snapshots:
            snippets.extend(
                self.extract_snippets(
                    snapshot,
                    concept_label,
                    max_length=self._policy.web.snippet_max_length,
                )
            )
        snippets.sort(key=lambda snippet: snippet.score, reverse=True)
        limit = self._policy.evidence.max_snippets_per_concept
        if limit <= 0:
            return []
        return snippets[:limit]

    def is_empty(self) -> bool:
        self._ensure_built()
        return not self._snapshots

    def _ensure_built(self) -> None:
        if not self._built:
            raise RuntimeError("Evidence index has not been built yet")

    @staticmethod
    def _extract_domain(url: str) -> str:
        parsed = urlparse(url)
        return parsed.netloc.lower()

    @lru_cache(maxsize=1)
    def _authoritative_domains(self) -> Tuple[str, ...]:
        return tuple(self._policy.web.authoritative_domains)
