"""Helpers for exporting observability data into run manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Mapping, Optional

from taxonomy.config.settings import Settings
from taxonomy.llm.registry import PromptRegistry
from taxonomy.observability import ObservabilityContext, ObservabilitySnapshot, stable_sorted


@dataclass
class ObservabilityManifest:
    """Transform observability state into manifest-friendly payloads."""

    context: ObservabilityContext
    _snapshot: ObservabilitySnapshot | None = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------
    # Snapshot helpers
    # ------------------------------------------------------------------
    def snapshot(self) -> ObservabilitySnapshot:
        if self._snapshot is None:
            self._snapshot = self.context.snapshot()
        return self._snapshot

    # ------------------------------------------------------------------
    # Counter aggregation
    # ------------------------------------------------------------------
    def aggregate_counters(
        self, snapshot: ObservabilitySnapshot | None = None
    ) -> Dict[str, Dict[str, Any]]:
        snap = snapshot or self.snapshot()
        aggregated: Dict[str, Dict[str, Any]] = {}
        for phase in stable_sorted(snap.counters):
            counters = snap.counters[phase]
            aggregated[phase] = {}
            for name in stable_sorted(counters):
                value = counters[name]
                if isinstance(value, Mapping):
                    aggregated[phase][name] = {
                        label: value[label] for label in stable_sorted(value)
                    }
                else:
                    aggregated[phase][name] = int(value)
        return aggregated

    # ------------------------------------------------------------------
    # Evidence & quarantine helpers
    # ------------------------------------------------------------------
    def integrate_evidence(self, evidence_snapshot: Mapping[str, Any]) -> Dict[str, Any]:
        samples = evidence_snapshot.get("samples", {})
        totals = evidence_snapshot.get("total_considered", {})
        phases = stable_sorted(set(samples) | set(totals))
        ordered_samples = {
            phase: [dict(entry) for entry in samples.get(phase, [])]
            for phase in phases
        }
        for entries in ordered_samples.values():
            entries.sort(key=lambda item: item.get("sequence", 0))
        return {
            "samples": ordered_samples,
            "total_considered": {phase: totals.get(phase, 0) for phase in phases},
        }

    def format_quarantine_data(self, quarantine_snapshot: Mapping[str, Any]) -> Dict[str, Any]:
        items = [dict(entry) for entry in quarantine_snapshot.get("items", [])]
        items.sort(key=lambda entry: entry.get("sequence", 0))
        by_reason = quarantine_snapshot.get("by_reason", {})
        return {
            "total": int(quarantine_snapshot.get("total", 0)),
            "by_reason": {reason: by_reason.get(reason, 0) for reason in stable_sorted(by_reason)},
            "items": items,
        }

    # ------------------------------------------------------------------
    # Prompt, threshold, and seed tracking
    # ------------------------------------------------------------------
    def collect_prompt_versions(
        self,
        registry: PromptRegistry,
        *,
        prompt_keys: Iterable[str] | None = None,
    ) -> Dict[str, str]:
        if prompt_keys is None:
            raw_prompts = getattr(registry, "_raw_data", {}).get("prompts", {})
            keys = stable_sorted(raw_prompts)
        else:
            keys = stable_sorted(set(prompt_keys))
        versions: Dict[str, str] = {}
        for prompt in keys:
            try:
                version = registry.active_version(prompt)
            except KeyError:
                continue
            versions[prompt] = version
            self.context.register_prompt_version(prompt, version)
        return versions

    def capture_thresholds(self, settings: Settings) -> Dict[str, Any]:
        thresholds = {
            "level_thresholds": settings.policies.level_thresholds.model_dump(mode="json"),
            "deduplication": settings.policies.deduplication.model_dump(mode="json"),
            "validation": settings.policies.validation.model_dump(mode="json"),
        }
        for name, value in thresholds["level_thresholds"].items():
            self.context.register_threshold(f"level_thresholds.{name}", value)
        return thresholds

    def capture_seeds(self, settings: Settings) -> Dict[str, int]:
        seeds: Dict[str, int] = {}
        if settings.random_seed is not None:
            seeds["settings.random_seed"] = int(settings.random_seed)
        llm_seed = getattr(settings.policies.llm, "random_seed", None)
        if llm_seed is not None:
            seeds["llm.random_seed"] = int(llm_seed)
        raw_seed = getattr(settings.policies.raw_extraction, "random_seed", None)
        if raw_seed is not None:
            seeds["raw_extraction.random_seed"] = int(raw_seed)
        level_seed = getattr(settings.policies.level0_excel, "random_seed", None)
        if level_seed is not None:
            seeds["level0_excel.random_seed"] = int(level_seed)
        for name, value in seeds.items():
            self.context.register_seed(name, value)
        return seeds

    # ------------------------------------------------------------------
    # Manifest payload assembly
    # ------------------------------------------------------------------
    def _format_operations(self, snapshot: ObservabilitySnapshot) -> list[Dict[str, Any]]:
        operations = []
        for entry in snapshot.operations:
            payload = entry.payload if isinstance(entry.payload, Mapping) else {}
            operations.append(
                {
                    "sequence": entry.sequence,
                    "phase": entry.phase,
                    "operation": entry.operation,
                    "outcome": entry.outcome,
                    "payload": dict(payload),
                }
            )
        operations.sort(key=lambda item: item["sequence"])
        return operations

    def build_payload(self) -> Dict[str, Any]:
        snapshot = self.snapshot()
        counters = self.aggregate_counters(snapshot)
        evidence = self.integrate_evidence(snapshot.evidence)
        quarantine = self.format_quarantine_data(snapshot.quarantine)
        operations = self._format_operations(snapshot)
        performance = {
            phase: dict(metrics)
            for phase, metrics in sorted(snapshot.performance.items(), key=lambda item: item[0])
        }
        prompt_versions = dict(sorted(snapshot.prompt_versions.items()))
        thresholds = dict(sorted(snapshot.thresholds.items()))
        seeds = dict(sorted(snapshot.seeds.items()))
        return {
            "counters": counters,
            "quarantine": quarantine,
            "evidence": evidence,
            "operations": operations,
            "performance": performance,
            "prompt_versions": prompt_versions,
            "thresholds": thresholds,
            "seeds": seeds,
            "checksum": snapshot.checksum,
            "captured_at": snapshot.captured_at,
        }


__all__ = ["ObservabilityManifest"]
