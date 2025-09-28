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
    unknown: bool = False


class WebValidator:
    """Validate concepts by inspecting mined web evidence."""

    def __init__(self, policy: ValidationPolicy, indexer: EvidenceIndexer) -> None:
        self._policy = policy
        self._indexer = indexer

    def validate_concept(
        self, concept: Concept, *, retrieval_timed_out: bool = False
    ) -> WebResult:
        snapshots = self._indexer.search_evidence(concept.canonical_label)
        evidence = self._indexer.aggregate_evidence(
            concept.canonical_label,
            snapshots,
        )

        unknown = False
        if retrieval_timed_out:
            unknown = True
        elif not snapshots and self._indexer.is_empty():
            unknown = True

        passed = not unknown and len(evidence) >= self._policy.web.min_snippet_matches
        findings = self._build_findings(concept, evidence, passed, unknown, retrieval_timed_out)
        summary = self._summarize(evidence, unknown, retrieval_timed_out)
        return WebResult(
            passed=passed,
            findings=findings,
            summary=summary,
            evidence=evidence,
            unknown=unknown,
        )

    def _build_findings(
        self,
        concept: Concept,
        evidence: List[EvidenceSnippet],
        passed: bool,
        unknown: bool,
        timed_out: bool,
    ) -> List[ValidationFinding]:
        if unknown:
            timeout_note = (
                f" (timeout after {self._policy.web.evidence_timeout_seconds:.1f}s)"
                if timed_out
                else ""
            )
            return [
                ValidationFinding(
                    concept_id=concept.id,
                    mode=FindingMode.WEB,
                    passed=False,
                    detail=f"Web evidence unavailable{timeout_note}.",
                )
            ]
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

    def _summarize(
        self, evidence: List[EvidenceSnippet], unknown: bool, timed_out: bool
    ) -> str:
        if unknown:
            if timed_out:
                return (
                    f"No evidence (timeout after {self._policy.web.evidence_timeout_seconds:.1f}s)"
                )
            return "No evidence (index empty)"
        if not evidence:
            return "No evidence"
        return f"Evidence snippets: {len(evidence)}"
