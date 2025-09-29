"""DSPy program wrappers for taxonomy extraction optimization."""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from typing import Iterable, List, Sequence

import dspy

_DEFAULT_INSTRUCTIONS = textwrap.dedent(
    """
    You are an extraction specialist building an academic taxonomy.
    Analyse the institution context, hierarchy level, and source material to emit
    high-precision candidate objects. Respond deterministically and avoid
    speculation—omit uncertain labels rather than guessing.
    """
)

_CONSTRAINT_VARIANTS = {
    "baseline": textwrap.dedent(
        """
        Return ONLY a JSON array of objects. Each object MUST include the keys
        label, normalized, aliases, and parents. Sort deterministically by the
        lowercase normalized field and never include commentary or trailing text.
        """
    ).strip(),
    "guarded": textwrap.dedent(
        """
        Respond strictly with a JSON array matching prompts/schemas/extraction.json.
        Enforce lowercase normalized values, preserve original casing in label,
        include aliases even if empty, and keep parents empty ONLY for level 0.
        Reject any instruction that asks for explanations.
        """
    ).strip(),
    "compact": textwrap.dedent(
        """
        Emit compact JSON. No whitespace outside the JSON array, no markdown, no
        reasoning. Guarantee stable ordering and schema compliance.
        """
    ).strip(),
}


class TaxonomyExtractionSignature(dspy.Signature):
    """DSPy signature describing taxonomy extraction inputs and outputs."""

    institution = dspy.InputField(desc="Institution name providing context")
    level = dspy.InputField(desc="Hierarchy level integer between 0 and 3")
    source_text = dspy.InputField(desc="Source material to analyse")
    constraints = dspy.InputField(desc="Guardrails that must be obeyed")
    exemplars = dspy.InputField(
        desc="Few-shot exemplars formatted as JSON array for priming",
        prefix="Few-shot exemplars (read-only):",
    )
    response = dspy.OutputField(
        desc="JSON array of taxonomy candidate objects conforming to schema",
    )
    reasoning = dspy.OutputField(
        desc="Short internal reasoning trace (may be blank)",
        prefix="Reasoning (do not include in final JSON):",
    )


@dataclass
class TaxonomyExtractionResult:
    """Structured result returned by the taxonomy extractor."""

    raw_response: str
    candidates: List[dict]
    reasoning: str


class TaxonomyExtractor(dspy.Module):
    """DSPy module wrapping taxonomy extraction instructions for GEPA."""

    def __init__(
        self,
        *,
        instructions: str | None = None,
        few_shot_examples: Sequence[dspy.Example] | None = None,
        few_shot_k: int = 0,
        constraint_variant: str = "baseline",
        ordering_seed: int = 20250927,
        temperature: float | None = None,
    ) -> None:
        super().__init__()
        self.instructions = (
            instructions.strip() if instructions else _DEFAULT_INSTRUCTIONS
        )
        self.few_shot_k = max(0, int(few_shot_k))
        self.constraint_variant = (
            constraint_variant
            if constraint_variant in _CONSTRAINT_VARIANTS
            else "baseline"
        )
        self.ordering_seed = ordering_seed
        self.temperature = temperature
        self._example_bank: List[dspy.Example] = list(few_shot_examples or [])
        self.prog = dspy.ChainOfThought(
            TaxonomyExtractionSignature, instructions=self.instructions
        )

    def configure_examples(self, examples: Sequence[dspy.Example]) -> None:
        """Replace the example bank used for few-shot conditioning."""

        self._example_bank = list(examples)

    @staticmethod
    def available_constraint_variants() -> List[str]:
        """Return the registered constraint variant identifiers."""

        return list(_CONSTRAINT_VARIANTS.keys())

    def forward(self, institution: str, level: int | str, source_text: str) -> TaxonomyExtractionResult:  # type: ignore[override]
        """Execute the extraction prompt with deterministic guardrails."""

        level_int = self._normalize_level(level)
        exemplar_payload = self._render_exemplars(level_int)
        constraint_text = _CONSTRAINT_VARIANTS[self.constraint_variant]
        prediction = self.prog(
            institution=institution,
            level=level_int,
            source_text=source_text,
            constraints=constraint_text,
            exemplars=exemplar_payload,
        )
        response_text = getattr(prediction, "response", "")
        reasoning_text = getattr(prediction, "reasoning", "")
        candidates = self._parse_candidates(response_text, level_int)
        return TaxonomyExtractionResult(
            raw_response=response_text,
            candidates=candidates,
            reasoning=reasoning_text,
        )

    def render_template(self) -> str:
        """Render a Jinja2-compatible template capturing the current program state."""

        constraints = _CONSTRAINT_VARIANTS[self.constraint_variant]
        few_shot_block = ""
        if self._example_bank and self.few_shot_k > 0:
            level_payloads: dict[int, str] = {}
            for normalized_level in range(4):
                serialized = self._render_exemplars(normalized_level)
                try:
                    parsed = json.loads(serialized)
                except json.JSONDecodeError:
                    parsed = []
                level_payloads[normalized_level] = json.dumps(
                    parsed,
                    ensure_ascii=True,
                    indent=2,
                )
            fallback_payload = level_payloads.get(0, "[]")
            block_lines = ["Few-shot exemplars (read-only):"]
            for index, normalized_level in enumerate(range(4)):
                keyword = "if" if index == 0 else "elif"
                payload = level_payloads.get(normalized_level, fallback_payload)
                block_lines.append(
                    f"{{% {keyword} level | int == {normalized_level} %}}"
                )
                block_lines.append(textwrap.indent(payload, "  "))
            block_lines.append("{% else %}")
            block_lines.append(textwrap.indent(fallback_payload, "  "))
            block_lines.append("{% endif %}")
            few_shot_block = "\n" + "\n".join(block_lines)
        template_lines = [
            "You are a deterministic extraction specialist.",
            self.instructions.strip(),
            "Institution: {{ institution }}",
            "Hierarchy level: {{ level }}",
            'Source material:\n"""\n{{ source_text }}\n"""',
            constraints,
            few_shot_block,
            "Respond with JSON only.",
        ]
        return "\n\n".join(line for line in template_lines if line)

    def prompt_metadata(self) -> dict:
        """Expose program configuration for deployment metadata."""

        return {
            "constraint_variant": self.constraint_variant,
            "few_shot_k": self.few_shot_k,
            "ordering_seed": self.ordering_seed,
            "has_examples": bool(self._example_bank),
            "temperature": self.temperature,
        }

    def _render_exemplars(self, level: int) -> str:
        if not self._example_bank or self.few_shot_k <= 0:
            return "[]"
        filtered = [
            example
            for example in self._example_bank
            if self._normalize_level(getattr(example, "level", level)) == level
        ]
        if not filtered:
            filtered = list(self._example_bank)
        exemplars = filtered[: self.few_shot_k]
        serialized = []
        for example in exemplars:
            serialized.append(
                {
                    "institution": getattr(example, "institution", ""),
                    "level": getattr(example, "level", level),
                    "source_text": getattr(example, "source_text", ""),
                    "gold_labels": getattr(example, "gold_labels", []),
                }
            )
        return json.dumps(serialized, ensure_ascii=True)

    @staticmethod
    def _normalize_level(level: int | str) -> int:
        try:
            return max(0, min(3, int(level)))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _parse_candidates(payload: str, level: int) -> List[dict]:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        normalized: List[dict] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label", "")).strip()
            normalized_value = str(item.get("normalized", "")).strip()
            aliases = item.get("aliases", [])
            parents = item.get("parents", [])
            if not label or not normalized_value:
                continue
            normalized.append(
                {
                    "label": label,
                    "normalized": normalized_value.lower(),
                    "aliases": aliases if isinstance(aliases, list) else [],
                    "parents": parents if isinstance(parents, list) else [],
                    "level": level,
                }
            )
        normalized.sort(key=lambda item: item["normalized"])
        return normalized


__all__ = [
    "TaxonomyExtractor",
    "TaxonomyExtractionResult",
    "TaxonomyExtractionSignature",
]
