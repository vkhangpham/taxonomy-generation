"""Web evidence validation leveraging indexed page snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import List

from ...config.policies import ValidationPolicy
from ...entities.core import Concept, FindingMode, ValidationFinding
from .evidence import EvidenceIndexer, EvidenceSnippet


@dataclass
class WebResult:
    """Structured result for web evidence validation."""

    passed: bool
    findings: List[ValidationFinding]
    summary: str
    evidence: List[EvidenceSnippet]


class WebValidator:
    """Validate concepts by inspecting mined web evidence."""

    def __init__(self, policy: ValidationPolicy, indexer: EvidenceIndexer) -> None:
        self._policy = policy
        self._indexer = indexer

    def validate_concept(self, concept: Concept) -> WebResult:
        snapshots = self._indexer.search_evidence(concept.canonical_label)
        evidence = self._indexer.aggregate_evidence(
            concept.canonical_label,
            snapshots,
        )

        passed = len(evidence) >= self._policy.web.min_snippet_matches
        findings = self._build_findings(concept, evidence, passed)
        summary = self._summarize(evidence)
        return WebResult(
            passed=passed,
            findings=findings,
            summary=summary,
            evidence=evidence,
        )

    def _build_findings(
        self, concept: Concept, evidence: List[EvidenceSnippet], passed: bool
    ) -> List[ValidationFinding]:
        if not evidence:
            return [
                ValidationFinding(
                    concept_id=concept.id,
                    mode=FindingMode.WEB,
                    passed=False,
                    detail="No supporting web evidence located.",
                )
            ]
        detail = (
            f"Collected {len(evidence)} evidence snippets with average score "
            f"{mean(snippet.score for snippet in evidence):.2f}"
        )
        return [
            ValidationFinding(
                concept_id=concept.id,
                mode=FindingMode.WEB,
                passed=passed,
                detail=detail,
                evidence={
                    "top_url": evidence[0].url,
                    "top_institution": evidence[0].institution,
                }
                if evidence and self._policy.evidence.store_evidence_urls
                else None,
            )
        ]

    @staticmethod
    def _summarize(evidence: List[EvidenceSnippet]) -> str:
        if not evidence:
            return "No evidence"
        return f"Evidence snippets: {len(evidence)}"
