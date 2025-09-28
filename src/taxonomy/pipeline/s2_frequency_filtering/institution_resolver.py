"""Institution identity resolution utilities for frequency filtering."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Dict

from loguru import logger

from taxonomy.config.policies import InstitutionPolicy
from taxonomy.utils.helpers import fold_diacritics, normalize_whitespace


def _canonicalize_case(value: str) -> str:
    """Return a title-cased representation preserving key abbreviations."""

    tokens = [token for token in value.split(" ") if token]
    lowercase_keep = {"of", "and", "for", "the", "at", "in"}
    normalised_tokens = []
    for index, token in enumerate(tokens):
        if token.isupper() and len(token) <= 4:
            normalised_tokens.append(token)
            continue
        lowered = token.lower()
        if index > 0 and lowered in lowercase_keep:
            normalised_tokens.append(lowered)
        else:
            normalised_tokens.append(lowered.capitalize())
    return " ".join(normalised_tokens)


@dataclass
class InstitutionResolver:
    """Resolve institution names to canonical identities for aggregation."""

    policy: InstitutionPolicy
    _canonical_index: Dict[str, str] = field(init=False, default_factory=dict)
    _cache: Dict[str, str] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:  # pragma: no cover - simple initialisation
        self._canonical_index = {
            self._normalize_key(alias): normalize_whitespace(canonical)
            for alias, canonical in self.policy.canonical_mappings.items()
        }

    def normalize_institution(self, name: str) -> str:
        """Apply deterministic whitespace and diacritic folding."""

        cleaned = normalize_whitespace(fold_diacritics(name.strip()))
        return cleaned.lower()

    def resolve_identity(self, institution_name: str) -> str:
        """Return the canonical institution identifier for *institution_name*."""

        if institution_name is None:
            trimmed_name = ""
        elif isinstance(institution_name, str):
            trimmed_name = institution_name.strip()
        else:
            coerced_name = str(institution_name)
            logger.debug(
                "Coercing non-string institution name to string; coerced={}",
                coerced_name,
            )
            trimmed_name = coerced_name.strip()

        if not trimmed_name:
            placeholder = self._placeholder_identifier("unknown", suffix="empty")
            logger.debug(
                "Missing institution name encountered; placeholder={}", placeholder
            )
            return placeholder

        lowered_name = trimmed_name.lower()

        if lowered_name == "unknown":
            placeholder = self._placeholder_identifier("unknown", suffix="explicit")
            logger.debug(
                "Explicit 'unknown' institution name encountered; placeholder={}",
                placeholder,
            )
            self._cache.setdefault(lowered_name, placeholder)
            return placeholder

        key = self._normalize_key(trimmed_name)
        if key in self._cache:
            return self._cache[key]

        if key in self._canonical_index:
            result = self._canonical_index[key]
        else:
            candidate = self._apply_campus_vs_system_rules(trimmed_name)
            result = normalize_whitespace(candidate)
        self._cache[key] = result
        return result

    def _normalize_key(self, value: str) -> str:
        return self.normalize_institution(value)

    def _apply_campus_vs_system_rules(self, name: str) -> str:
        cleaned = normalize_whitespace(name)
        if self.policy.campus_vs_system == "prefer-system":
            lowered = cleaned.lower()
            if "," in cleaned:
                base = cleaned.split(",", 1)[0].strip()
                if base:
                    return _canonicalize_case(base)
            at_index = lowered.find(" at ")
            if at_index != -1:
                base = cleaned[:at_index].strip()
                if base:
                    return _canonicalize_case(base)
        if self.policy.campus_vs_system == "prefer-campus":
            return _canonicalize_case(cleaned)
        if self.policy.campus_vs_system == "merge" and "," in cleaned:
            # For merge semantics fall back to concatenation without separators.
            base = cleaned.replace(",", " ")
            return _canonicalize_case(normalize_whitespace(base))
        return _canonicalize_case(cleaned)

    def _placeholder_identifier(self, label: str, *, suffix: str | None = None) -> str:
        material = f"{label}|{suffix or ''}"
        digest = hashlib.sha1(material.encode("utf-8")).hexdigest()[:8]
        return f"placeholder::{digest}"


__all__ = ["InstitutionResolver"]
