"""LLM-backed entailment validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence

from ...config.policies import ValidationPolicy
from ...entities.core import Concept, FindingMode, ValidationFinding
from ... import llm
from .evidence import EvidenceSnippet

LLMRunner = Callable[[str, Dict[str, object]], object]


@dataclass
class LLMResult:
    """Result returned by the LLM validator."""

    passed: bool
    confidence: float
    findings: List[ValidationFinding]
    summary: str


class LLMValidator:
    """Validate a concept using the configured LLM entailment prompt."""

    def __init__(
        self,
        policy: ValidationPolicy,
        runner: Callable[[str, Dict[str, object]], object] | None = None,
    ) -> None:
        self._policy = policy
        self._runner = runner or self._default_runner

    def validate_concept(
        self, concept: Concept, evidence: Sequence[EvidenceSnippet]
    ) -> LLMResult:
        payload = self.prepare_evidence(evidence)
        if not payload:
            findings = [
                ValidationFinding(
                    concept_id=concept.id,
                    mode=FindingMode.LLM,
                    passed=False,
                    detail="No evidence available for LLM entailment.",
                )
            ]
            return LLMResult(False, 0.0, findings, "No evidence")

        response = self.check_entailment(concept, payload)
        if not response.get("ok", False):
            findings = [
                ValidationFinding(
                    concept_id=concept.id,
                    mode=FindingMode.LLM,
                    passed=False,
                    detail=f"LLM failure: {response.get('error', 'unknown')}",
                )
            ]
            return LLMResult(False, 0.0, findings, "LLM call failed")

        result = response.get("content", {}) or {}
        passed = bool(result.get("validated", False))
        reason = result.get("reason", "No reason provided")
        confidence = float(result.get("confidence", 0.0))
        confidence = self.assess_confidence(confidence, evidence)

        findings = [
            ValidationFinding(
                concept_id=concept.id,
                mode=FindingMode.LLM,
                passed=passed,
                detail=reason,
            )
        ]
        summary = f"LLM entailment {'passed' if passed else 'failed'}"
        return LLMResult(passed, confidence, findings, summary)

    def prepare_evidence(self, evidence: Sequence[EvidenceSnippet]) -> List[Dict[str, str]]:
        max_tokens = self._policy.llm.max_evidence_tokens
        approx_limit = max_tokens * 4  # approx chars assuming 4 chars/token
        selected: List[Dict[str, str]] = []
        total_chars = 0
        for snippet in evidence:
            text = snippet.text.strip()
            if not text:
                continue
            snippet_chars = len(text)
            if approx_limit and total_chars + snippet_chars > approx_limit and selected:
                break
            selected.append({
                "text": text,
                "url": snippet.url,
                "institution": snippet.institution,
            })
            total_chars += snippet_chars
        return selected

    def check_entailment(self, concept: Concept, evidence_payload: List[Dict[str, str]]) -> Dict[str, object]:
        try:
            response = self._runner(
                "validation.entailment",
                {
                    "concept": {
                        "id": concept.id,
                        "label": concept.canonical_label,
                        "level": concept.level,
                    },
                    "evidence": evidence_payload,
                },
            )
        except Exception as exc:  # pragma: no cover - defensive
            return {"ok": False, "error": str(exc)}

        if not getattr(response, "ok", False):
            return {"ok": False, "error": getattr(response, "error", "unknown")}
        return {"ok": True, "content": getattr(response, "content", {})}

    def assess_confidence(self, llm_confidence: float, evidence: Sequence[EvidenceSnippet]) -> float:
        if not evidence:
            return 0.0
        evidence_quality = sum(snippet.score for snippet in evidence) / len(evidence)
        return max(0.0, min(1.0, 0.5 * llm_confidence + 0.5 * min(1.0, evidence_quality)))

    @staticmethod
    def _default_runner(prompt_key: str, variables: Dict[str, object]) -> object:
        return llm.run(prompt_key, variables)
