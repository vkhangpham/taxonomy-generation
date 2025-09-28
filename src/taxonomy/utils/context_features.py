"""Context feature extraction utilities for taxonomy disambiguation."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
import re
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from ..entities.core import Concept, SourceRecord

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9']+")


@dataclass
class ContextWindow:
    """Compact representation of contextual evidence for a concept mention."""

    concept_id: str
    text: str
    institution: str | None
    parent_lineage: str
    source_index: int
    metadata: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.text = self.text.strip()


def _tokenize(text: str) -> List[str]:
    return [match.group(0).lower() for match in _TOKEN_PATTERN.finditer(text)]


def extract_parent_lineage_key(concept: Concept) -> str:
    """Create a stable key summarizing a concept's parent lineage."""

    if concept.parents:
        parents = " > ".join(concept.parents)
    else:
        parents = "<root>"
    return f"L{concept.level}:{parents}"


def _iter_source_records(
    source_records: Sequence[SourceRecord] | Mapping[str, SourceRecord]
) -> Iterable[Tuple[int, str, SourceRecord]]:
    if isinstance(source_records, Mapping):
        for index, key in enumerate(sorted(source_records)):
            yield index, key, source_records[key]
    else:
        for index, record in enumerate(source_records):
            yield index, str(index), record


def extract_context_windows(
    concept: Concept,
    source_records: Sequence[SourceRecord] | Mapping[str, SourceRecord],
    window_size: int = 100,
) -> List[ContextWindow]:
    """Extract token windows surrounding concept mentions from supporting sources."""

    if window_size <= 0:
        raise ValueError("window_size must be positive")

    target_tokens = concept.canonical_label.lower().split()
    lineage_key = extract_parent_lineage_key(concept)
    radius = max(1, window_size // 2)
    contexts: List[ContextWindow] = []
    seen_snippets: set[Tuple[int, str]] = set()

    for source_index, key, record in _iter_source_records(source_records):
        raw_tokens = record.text.split()
        lowered_tokens = [token.lower() for token in raw_tokens]
        matched = False
        if target_tokens:
            span = len(target_tokens)
            for idx in range(0, max(0, len(lowered_tokens) - span + 1)):
                segment = lowered_tokens[idx : idx + span]
                if segment == target_tokens:
                    start = max(0, idx - radius)
                    end = min(len(raw_tokens), idx + span + radius)
                    snippet = " ".join(raw_tokens[start:end]).strip()
                    match_key = (source_index, snippet)
                    if match_key not in seen_snippets:
                        contexts.append(
                            ContextWindow(
                                concept_id=concept.id,
                                text=snippet,
                                institution=getattr(record.provenance, "institution", None),
                                parent_lineage=lineage_key,
                                source_index=source_index,
                                metadata={
                                    "source_id": key,
                                    "url": getattr(record.provenance, "url", None) or "",
                                },
                            )
                        )
                        seen_snippets.add(match_key)
                    matched = True
        if not matched and raw_tokens:
            snippet = " ".join(raw_tokens[: min(len(raw_tokens), window_size)]).strip()
            match_key = (source_index, snippet)
            if match_key not in seen_snippets:
                contexts.append(
                    ContextWindow(
                        concept_id=concept.id,
                        text=snippet,
                        institution=getattr(record.provenance, "institution", None),
                        parent_lineage=lineage_key,
                        source_index=source_index,
                        metadata={
                            "source_id": key,
                            "url": getattr(record.provenance, "url", None) or "",
                        },
                    )
                )
                seen_snippets.add(match_key)

    contexts.sort(key=lambda ctx: (ctx.institution or "", ctx.source_index, ctx.text))
    return contexts


def compute_token_cooccurrence(
    contexts: Sequence[ContextWindow | str],
    min_frequency: int = 2,
) -> Dict[str, int]:
    """Compute token frequency across a set of contexts."""

    if min_frequency <= 0:
        raise ValueError("min_frequency must be positive")

    counter: Counter[str] = Counter()
    for context in contexts:
        text = context.text if isinstance(context, ContextWindow) else str(context)
        counter.update(_tokenize(text))

    filtered = {token: count for token, count in counter.items() if count >= min_frequency}
    return dict(sorted(filtered.items(), key=lambda item: (-item[1], item[0])))


def analyze_institution_distribution(
    concepts_group: Sequence[Concept],
) -> Dict[str, Dict[str, int]]:
    """Compute institution support patterns for each concept in a collision group."""

    distribution: Dict[str, Dict[str, int]] = {}
    for concept in concepts_group:
        counts: Counter[str] = Counter()
        metadata = concept.validation_metadata.get("institution_counts")
        if isinstance(metadata, Mapping):
            for institution, value in metadata.items():
                institution_key = str(institution).strip()
                if institution_key:
                    counts[institution_key.lower()] += int(value)
        else:
            institutions = concept.validation_metadata.get("institutions")
            if isinstance(institutions, Sequence):
                for institution in institutions:
                    institution_key = str(institution).strip()
                    if institution_key:
                        counts[institution_key.lower()] += 1
        if not counts and concept.support.institutions:
            counts["__aggregate__"] = concept.support.institutions
        distribution[concept.id] = dict(sorted(counts.items(), key=lambda item: item[0]))
    return distribution


def _jaccard_similarity(items_a: set[str], items_b: set[str]) -> float:
    if not items_a and not items_b:
        return 1.0
    intersection = len(items_a & items_b)
    union = len(items_a | items_b)
    if union == 0:
        return 1.0
    return intersection / union


def compute_context_divergence(
    context_group1: Sequence[ContextWindow | str],
    context_group2: Sequence[ContextWindow | str],
) -> float:
    """Score divergence between two context groups using tokens, parents, and institutions."""

    tokens_a = set()
    tokens_b = set()
    parents_a = set()
    parents_b = set()
    institutions_a = set()
    institutions_b = set()

    for context in context_group1:
        text = context.text if isinstance(context, ContextWindow) else str(context)
        tokens_a.update(_tokenize(text))
        if isinstance(context, ContextWindow):
            parents_a.add(context.parent_lineage)
            if context.institution:
                institutions_a.add(context.institution.lower())
    for context in context_group2:
        text = context.text if isinstance(context, ContextWindow) else str(context)
        tokens_b.update(_tokenize(text))
        if isinstance(context, ContextWindow):
            parents_b.add(context.parent_lineage)
            if context.institution:
                institutions_b.add(context.institution.lower())

    token_similarity = _jaccard_similarity(tokens_a, tokens_b)
    parent_similarity = _jaccard_similarity(parents_a, parents_b)
    institution_similarity = _jaccard_similarity(institutions_a, institutions_b)

    divergence = (
        (1.0 - token_similarity) * 0.5
        + (1.0 - parent_similarity) * 0.3
        + (1.0 - institution_similarity) * 0.2
    )
    return max(0.0, min(1.0, divergence))


def summarize_contexts_for_llm(
    contexts: Sequence[ContextWindow | str],
    max_contexts: int = 10,
) -> List[Dict[str, str]]:
    """Select representative contexts for LLM prompting with deterministic ordering."""

    if max_contexts <= 0:
        raise ValueError("max_contexts must be positive")

    prepared: List[Tuple[str, int, str, Dict[str, str]]] = []
    for idx, context in enumerate(contexts):
        if isinstance(context, ContextWindow):
            prepared.append(
                (
                    context.institution or "",
                    context.source_index,
                    context.text,
                    {
                        "text": context.text,
                        "institution": context.institution or "",
                        "parent_lineage": context.parent_lineage,
                        "source_index": str(context.source_index),
                        **{k: v for k, v in context.metadata.items() if v},
                    },
                )
            )
        else:
            text = str(context).strip()
            prepared.append(("", idx, text, {"text": text, "institution": ""}))

    prepared.sort(key=lambda item: (item[0], item[1], item[2]))

    unique_payloads: List[Dict[str, str]] = []
    seen_texts: set[str] = set()
    for _, _, text, payload in prepared:
        if text in seen_texts:
            continue
        unique_payloads.append(payload)
        seen_texts.add(text)
        if len(unique_payloads) >= max_contexts:
            break

    return unique_payloads


__all__ = [
    "ContextWindow",
    "extract_parent_lineage_key",
    "extract_context_windows",
    "compute_token_cooccurrence",
    "analyze_institution_distribution",
    "compute_context_divergence",
    "summarize_contexts_for_llm",
]
