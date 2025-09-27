"""Prompt registry management for the LLM subsystem."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import yaml

from .models import PromptMetadata


@dataclass(frozen=True)
class RegistryEntry:
    """In-memory representation of a prompt entry."""

    metadata: Dict[str, object]

    @property
    def active_variant(self) -> str:
        return str(self.metadata["active_variant"])

    @property
    def variants(self) -> Dict[str, Dict[str, object]]:
        return dict(self.metadata.get("variants", {}))


class PromptRegistry:
    """Loads prompt templates with version management and caching."""

    def __init__(self, *, registry_file: Path, hot_reload: bool = False) -> None:
        self._registry_file = registry_file
        self._hot_reload = hot_reload
        self._cache: Dict[str, PromptMetadata] = {}
        self._lock = threading.Lock()
        self._raw_data = self._load_registry()

    def active_version(self, prompt_key: str) -> str:
        entry = self._entry(prompt_key)
        return entry.active_variant

    def load_prompt(self, prompt_key: str) -> PromptMetadata:
        if self._hot_reload:
            with self._lock:
                self._raw_data = self._load_registry()
                self._cache.clear()
        with self._lock:
            if prompt_key in self._cache:
                return self._cache[prompt_key]
            entry = self._entry(prompt_key)
            variant_key = entry.active_variant
            variant = entry.variants.get(variant_key)
            if not variant:
                raise KeyError(f"Prompt '{prompt_key}' has no variant '{variant_key}'")
            metadata = PromptMetadata(
                prompt_key=prompt_key,
                version=variant_key,
                description=str(variant.get("description", "")),
                template_path=str(variant["template"]),
                schema_path=str(variant["schema"]),
                optimization_history=list(variant.get("optimization_history", [])),
                enforce_order_by=variant.get("enforce_order_by"),
            )
            self._cache[prompt_key] = metadata
            return metadata

    def _entry(self, prompt_key: str) -> RegistryEntry:
        try:
            entry = self._raw_data["prompts"][prompt_key]
        except KeyError as exc:
            raise KeyError(f"Prompt '{prompt_key}' is not registered") from exc
        return RegistryEntry(metadata=dict(entry))

    def _load_registry(self) -> Dict[str, object]:
        if not self._registry_file.exists():
            raise FileNotFoundError(f"Prompt registry not found: {self._registry_file}")
        with self._registry_file.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if "prompts" not in data:
            raise ValueError("Registry file missing 'prompts' section")
        return data


__all__ = ["PromptRegistry"]
