"""Concept splitting utilities used by the disambiguation pipeline."""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence

from ...config.policies import DisambiguationPolicy
from ...entities.core import Concept, Rationale, SplitOp, SupportStats
from ...utils import summarize_contexts_for_llm
from ...utils.context_features import ContextWindow
from .llm import LLMSenseDefinition


@dataclass
class SplitDecision:
    """Result of splitting a single concept."""

    new_concepts: List[Concept]
    split_op: SplitOp
    confidence: float


class ConceptSplitter:
    """Create new concept senses based on LLM guidance."""

    def __init__(self, policy: DisambiguationPolicy) -> None:
        self._policy = policy

    def split(
        self,
        source_concept: Concept,
        concept_group: Sequence[Concept],
        senses: Sequence[LLMSenseDefinition],
        parent_mappings: Mapping[str, Sequence[str]],
        evidence_mapping: Mapping[str, Sequence[int]] | None,
        confidence: float,
        context_lookup: Mapping[str, Sequence[ContextWindow]] | None = None,
    ) -> SplitDecision:
        combined_source = self._combine_source_concepts(source_concept, concept_group)
        new_ids = self.generate_split_ids(source_concept, len(senses))
        weights = self._compute_weights(senses, evidence_mapping)
        support_shares = self.distribute_support_stats(
            combined_source.support,
            len(senses),
            weights,
        )
        new_concepts = self.create_sense_concepts(
            combined_source,
            senses,
            parent_mappings,
            new_ids,
            support_shares,
        )

        exemplar_lookup = self._build_exemplar_lookup(concept_group, context_lookup)
        split_op = SplitOp(
            source_id=source_concept.id,
            new_ids=[concept.id for concept in new_concepts],
            rule="llm_disambiguation",
            evidence={
                "confidence": confidence,
                "senses": [
                    {
                        "label": sense.label,
                        "gloss": sense.gloss,
                        "parent_hints": sense.parent_hints,
                        "evidence_indices": list(sense.evidence_indices),
                        "exemplars": [
                            copy.deepcopy(exemplar_lookup[index])
                            for index in sense.evidence_indices
                            if index in exemplar_lookup
                        ],
                    }
                    for sense in senses
                ],
            },
        )
        return SplitDecision(new_concepts, split_op, confidence)

    def generate_split_ids(self, source_concept: Concept, num_senses: int) -> List[str]:
        base = source_concept.id
        ids: List[str] = []
        for index in range(num_senses):
            digest = hashlib.sha256(f"{base}:{index}".encode("utf-8")).hexdigest()[:12]
            ids.append(f"{base}::split::{digest}")
        return ids

    def create_sense_concepts(
        self,
        source_concept: Concept,
        senses: Sequence[LLMSenseDefinition],
        parent_mappings: Mapping[str, Sequence[str]],
        new_ids: Sequence[str],
        support_shares: Sequence[SupportStats],
    ) -> List[Concept]:
        sense_concepts: List[Concept] = []
        for index, (sense, new_id) in enumerate(zip(senses, new_ids)):
            parents = list(parent_mappings.get(sense.label, source_concept.parents))
            aliases = self.manage_aliases(source_concept, sense)
            support = support_shares[index]
            rationale = self.build_rationale(
                source_concept.rationale,
                source_concept,
                sense,
                new_id,
            )
            validation_metadata = copy.deepcopy(source_concept.validation_metadata)
            disambiguation_meta = validation_metadata.setdefault("disambiguation", {})
            disambiguation_meta[new_id] = {
                "gloss": sense.gloss,
                "parent_hints": sense.parent_hints,
                "evidence_indices": list(sense.evidence_indices),
            }

            new_concept = Concept(
                id=new_id,
                level=source_concept.level,
                canonical_label=self._build_sense_label(source_concept, sense),
                parents=parents,
                aliases=aliases,
                support=support,
                rationale=rationale,
                validation_passed=source_concept.validation_passed,
                validation_metadata=validation_metadata,
            )
            sense_concepts.append(new_concept)
        return sense_concepts

    def distribute_support_stats(
        self,
        support: SupportStats,
        num_senses: int,
        weights: Sequence[float],
    ) -> List[SupportStats]:
        if num_senses <= 0:
            raise ValueError("num_senses must be positive")
        shares: List[SupportStats] = []
        normalized_weights = self._normalize_weights(weights, num_senses)
        for index in range(num_senses):
            weight = normalized_weights[index]
            records = round(support.records * weight)
            institutions = max(1, round(support.institutions * weight)) if support.institutions else 0
            count = round(support.count * weight)
            shares.append(
                SupportStats(records=records, institutions=institutions, count=count)
            )
        self._rebalance_totals(shares, support)
        return shares

    def _normalize_weights(self, weights: Sequence[float], num_senses: int) -> List[float]:
        if len(weights) != num_senses:
            return [1.0 / num_senses for _ in range(num_senses)]
        total = sum(weights)
        if total <= 0:
            return [1.0 / num_senses for _ in range(num_senses)]
        return [value / total for value in weights]

    def _rebalance_totals(
        self,
        shares: List[SupportStats],
        original: SupportStats,
    ) -> None:
        def rebalance(attribute: str, target: int) -> None:
            current = sum(getattr(share, attribute) for share in shares)
            delta = target - current
            index = 0
            while delta != 0 and shares:
                if delta > 0:
                    setattr(shares[index], attribute, getattr(shares[index], attribute) + 1)
                    delta -= 1
                else:
                    if getattr(shares[index], attribute) > 0:
                        setattr(shares[index], attribute, getattr(shares[index], attribute) - 1)
                        delta += 1
                index = (index + 1) % len(shares)

        rebalance("records", original.records)
        rebalance("institutions", original.institutions)
        rebalance("count", original.count)

    def _compute_weights(
        self,
        senses: Sequence[LLMSenseDefinition],
        evidence_mapping: Mapping[str, Sequence[int]] | None,
    ) -> List[float]:
        if not evidence_mapping:
            return [1.0 for _ in senses]
        weights: List[float] = []
        for sense in senses:
            evidence = evidence_mapping.get(sense.label)
            weight = float(len(evidence)) if evidence else 1.0
            weights.append(weight)
        return weights

    def manage_aliases(self, source_concept: Concept, sense: LLMSenseDefinition) -> List[str]:
        alias_set = {source_concept.canonical_label.strip()}
        alias_set.update(alias.strip() for alias in source_concept.aliases)
        if sense.label:
            alias_set.add(sense.label.strip())
        return sorted(alias for alias in alias_set if alias)

    def build_rationale(
        self,
        template: Rationale,
        source_concept: Concept,
        sense: LLMSenseDefinition,
        new_id: str,
    ) -> Rationale:
        if not isinstance(template, Rationale):
            template = Rationale()
        rationale = Rationale.model_validate(template.model_dump())
        rationale.passed_gates["disambiguation"] = True
        rationale.reasons.append(
            f"Split '{source_concept.id}' into '{new_id}' due to distinct sense '{sense.label}'."
        )
        rationale.thresholds["disambiguation_min_evidence"] = self._policy.min_evidence_strength
        return rationale

    def _build_sense_label(
        self,
        source_concept: Concept,
        sense: LLMSenseDefinition,
    ) -> str:
        sense_label = sense.label.strip()
        if not sense_label:
            return source_concept.canonical_label
        if sense_label.lower() in source_concept.canonical_label.lower():
            return source_concept.canonical_label
        return f"{source_concept.canonical_label} - {sense_label}"

    def _combine_source_concepts(
        self,
        primary: Concept,
        concept_group: Sequence[Concept],
    ) -> Concept:
        if not concept_group:
            return primary.model_copy(deep=True)

        combined = primary.model_copy(deep=True)

        alias_set = {primary.canonical_label.strip(), *primary.aliases}
        total_records = primary.support.records
        total_institutions = primary.support.institutions
        total_count = primary.support.count
        rationales: List[Rationale] = [primary.rationale]

        for concept in concept_group:
            if concept.id == primary.id:
                continue
            alias_set.add(concept.canonical_label.strip())
            alias_set.update(alias.strip() for alias in concept.aliases)
            total_records += concept.support.records
            total_institutions += concept.support.institutions
            total_count += concept.support.count
            rationales.append(concept.rationale)

        alias_set.discard(combined.canonical_label)
        combined.aliases = sorted(alias for alias in alias_set if alias)
        combined.support = SupportStats(
            records=total_records,
            institutions=total_institutions,
            count=total_count,
        )
        combined.rationale = self._merge_rationales(rationales)
        return combined

    def _merge_rationales(self, rationales: Sequence[Rationale]) -> Rationale:
        merged = Rationale()
        seen_reasons: set[str] = set()
        for rationale in rationales:
            if not isinstance(rationale, Rationale):
                continue
            for gate, value in rationale.passed_gates.items():
                if gate not in merged.passed_gates:
                    merged.passed_gates[gate] = bool(value)
                else:
                    merged.passed_gates[gate] = merged.passed_gates[gate] and bool(value)

            for reason in rationale.reasons:
                cleaned = reason.strip()
                if cleaned and cleaned not in seen_reasons:
                    merged.reasons.append(cleaned)
                    seen_reasons.add(cleaned)

            for key, threshold in rationale.thresholds.items():
                if key not in merged.thresholds:
                    merged.thresholds[key] = float(threshold)
                else:
                    merged.thresholds[key] = max(merged.thresholds[key], float(threshold))

        return merged

    def _build_exemplar_lookup(
        self,
        concept_group: Sequence[Concept],
        context_lookup: Mapping[str, Sequence[ContextWindow]] | None,
    ) -> Dict[int, Dict[str, Any]]:
        if not context_lookup:
            return {}

        exemplar_lookup: Dict[int, Dict[str, Any]] = {}
        per_parent_limit = self._policy.max_contexts_per_parent
        if per_parent_limit <= 0:
            max_contexts = self._policy.max_contexts_for_prompt
        else:
            max_contexts = min(
                self._policy.max_contexts_for_prompt,
                per_parent_limit,
            )
        index = 0

        for concept in concept_group:
            contexts = context_lookup.get(concept.id)
            if not contexts:
                continue

            summarized = summarize_contexts_for_llm(contexts, max_contexts=max_contexts)
            for payload in summarized:
                entry: Dict[str, Any] = {
                    "index": index,
                    "concept_id": concept.id,
                    "text": payload.get("text", ""),
                    "institution": payload.get("institution", ""),
                    "parent_lineage": payload.get("parent_lineage", ""),
                    "source_index": payload.get("source_index", ""),
                }
                extras = {
                    key: value
                    for key, value in payload.items()
                    if key
                    not in {"text", "institution", "parent_lineage", "source_index"}
                    and value
                }
                if extras:
                    entry["metadata"] = extras
                exemplar_lookup[index] = entry
                index += 1

        return exemplar_lookup


__all__ = [
    "ConceptSplitter",
    "SplitDecision",
]
