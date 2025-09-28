"""LLM-backed separability checks for disambiguation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Sequence

from ... import llm
from ...config.policies import DisambiguationPolicy
from ...entities.core import Concept
from ...utils import extract_parent_lineage_key, summarize_contexts_for_llm
from ...utils.context_features import ContextWindow

LLMRunner = Callable[[str, Dict[str, object]], object]


@dataclass
class LLMSenseDefinition:
    """Normalized sense definition returned by the LLM."""

    label: str
    gloss: str
    confidence: float
    parent_hints: List[str]
    evidence_indices: List[int]


@dataclass
class LLMDisambiguationResult:
    """Outcome of an LLM disambiguation request."""

    separable: bool
    confidence: float
    senses: List[LLMSenseDefinition]
    reason: str


class LLMDisambiguator:
    """Call into the LLM layer to decide whether a collision should split."""

    def __init__(
        self,
        policy: DisambiguationPolicy,
        runner: LLMRunner | None = None,
    ) -> None:
        self._policy = policy
        self._runner = runner or self._default_runner

    def prepare_contexts_for_llm(
        self,
        concept_group: Sequence[Concept],
        contexts: Mapping[str, Sequence[ContextWindow]] | None,
    ) -> List[Dict[str, object]]:
        payload: List[Dict[str, object]] = []
        for concept in concept_group:
            concept_contexts = []
            if contexts is not None:
                concept_contexts = list(contexts.get(concept.id, []))
            summarized = summarize_contexts_for_llm(
                concept_contexts,
                max_contexts=min(
                    self._policy.max_contexts_for_prompt,
                    self._policy.max_contexts_per_parent,
                ),
            )
            payload.append(
                {
                    "concept_id": concept.id,
                    "level": concept.level,
                    "normalized_label": concept.canonical_label,
                    "parent_lineage": extract_parent_lineage_key(concept),
                    "contexts": summarized,
                }
            )
        return payload

    def check_separability(
        self,
        label: str,
        level: int,
        concept_group: Sequence[Concept],
        contexts: Mapping[str, Sequence[ContextWindow]] | None,
    ) -> LLMDisambiguationResult:
        if not self._policy.llm_enabled:
            return LLMDisambiguationResult(False, 0.0, [], "LLM disabled by policy")

        concept_payload = self.prepare_contexts_for_llm(concept_group, contexts)
        variables = {
            "label": label,
            "level": level,
            "concepts": concept_payload,
        }

        try:
            response = self._runner("taxonomy.disambiguate", variables)
        except Exception as exc:  # pragma: no cover - defensive
            return LLMDisambiguationResult(False, 0.0, [], f"LLM invocation failed: {exc}")

        if not getattr(response, "ok", False):
            error = getattr(response, "error", "unknown error")
            return LLMDisambiguationResult(False, 0.0, [], f"LLM error: {error}")

        raw_content = getattr(response, "content", None)
        parsed: Mapping[str, object] = {}
        if isinstance(raw_content, Mapping):
            parsed = raw_content
        elif isinstance(raw_content, str):
            try:
                candidate = json.loads(raw_content)
            except (TypeError, ValueError):  # pragma: no cover - defensive
                candidate = {}
            if isinstance(candidate, Mapping):
                parsed = candidate
        senses_payload = parsed.get("senses", []) or []
        confidence_raw = parsed.get("confidence", parsed.get("score", 0.0))
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            confidence = 0.0

        senses = self._normalize_senses(senses_payload)
        raw_separable = parsed.get("separable")
        if isinstance(raw_separable, str):
            normalized = raw_separable.strip().lower()
            if normalized in {"true", "yes", "y", "1", "t"}:
                separable = True
            elif normalized in {"false", "no", "n", "0", "f"}:
                separable = False
            else:
                separable = len(senses) >= 2
        elif raw_separable is None:
            separable = len(senses) >= 2
        else:
            separable = bool(raw_separable)
        if separable and len(senses) < 2:
            separable = False
        reason = parsed.get("reason", "") or ""

        return LLMDisambiguationResult(separable, max(0.0, min(1.0, confidence)), senses, reason)

    def _normalize_senses(self, senses_payload: Sequence[dict]) -> List[LLMSenseDefinition]:
        normalized: List[LLMSenseDefinition] = []
        for index, payload in enumerate(senses_payload):
            label = str(payload.get("label") or payload.get("title") or f"Sense {index + 1}").strip()
            gloss = str(payload.get("gloss") or payload.get("description") or "").strip()
            parent_hints_raw = payload.get("parent_hints") or payload.get("parents") or []
            if isinstance(parent_hints_raw, str):
                parent_hints = [parent_hints_raw]
            else:
                parent_hints = [str(item).strip() for item in parent_hints_raw if str(item).strip()]
            evidence_indices_raw = payload.get("evidence_indices") or payload.get("evidence") or []
            if isinstance(evidence_indices_raw, int):
                evidence_indices = [evidence_indices_raw]
            else:
                evidence_indices = [int(item) for item in evidence_indices_raw if isinstance(item, int)]

            try:
                confidence = float(payload.get("confidence", 1.0))
            except (TypeError, ValueError):  # pragma: no cover - defensive
                confidence = 0.0

            gloss = self.validate_gloss(gloss)
            normalized.append(
                LLMSenseDefinition(
                    label=label or f"Sense {index + 1}",
                    gloss=gloss,
                    confidence=max(0.0, min(1.0, confidence)),
                    parent_hints=parent_hints,
                    evidence_indices=evidence_indices,
                )
            )
        return normalized

    def validate_gloss(self, gloss: str) -> str:
        if not gloss:
            return ""
        words = gloss.split()
        if len(words) <= self._policy.gloss_max_words:
            return gloss
        capped = " ".join(words[: self._policy.gloss_max_words])
        return capped.rstrip(".,;:!?") + "..."

    def map_senses_to_parents(
        self,
        senses: Sequence[LLMSenseDefinition],
        original_concepts: Sequence[Concept],
    ) -> Dict[str, List[str]]:
        lineage_lookup = {
            extract_parent_lineage_key(concept): list(concept.parents)
            for concept in original_concepts
        }
        default_parents = original_concepts[0].parents if original_concepts else []

        mappings: Dict[str, List[str]] = {}
        for sense in senses:
            mapped: List[str] = []
            for hint in sense.parent_hints:
                hint_normalized = hint.strip().lower()
                for lineage, parents in lineage_lookup.items():
                    if hint_normalized in lineage.lower():
                        mapped = parents
                        break
                if mapped:
                    break
            if not mapped:
                mapped = default_parents
            mappings[sense.label] = list(mapped)
        return mappings

    def assess_split_confidence(
        self,
        llm_confidence: float,
        context_divergence: float,
    ) -> float:
        combined = 0.6 * llm_confidence + 0.4 * max(0.0, min(1.0, context_divergence))
        return max(0.0, min(1.0, combined))

    @staticmethod
    def _default_runner(prompt_key: str, variables: Dict[str, object]) -> object:
        return llm.run(prompt_key, variables)


__all__ = [
    "LLMDisambiguator",
    "LLMSenseDefinition",
    "LLMDisambiguationResult",
]
