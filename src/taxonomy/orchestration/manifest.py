"""Run manifest generation for taxonomy pipeline executions."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, TYPE_CHECKING

from taxonomy.observability import ObservabilityContext, stable_hash
from taxonomy.utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing convenience
    from taxonomy.config.policies import ObservabilityPolicy
    from taxonomy.config.settings import Settings
    from taxonomy.llm.registry import PromptRegistry

_LOGGER = get_logger(module=__name__)


class RunManifest:
    """Collects structured metadata about a taxonomy pipeline run."""

    def __init__(
        self,
        run_id: str,
        *,
        policy: "ObservabilityPolicy" | None = None,
    ) -> None:
        self.run_id = run_id
        self._policy = policy
        self._data: Dict[str, Any] = {
            "run_id": run_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "versions": {},
            "statistics": {},
            "evidence_samples": [],
            "configuration": {},
            "operation_logs": [],
            "performance": {},
            "hierarchy": {},
            "artifacts": [],
            "observability": {},
            "prompt_versions": {},
            "checksums": {},
        }
        self._observability: ObservabilityContext | None = None
        self._observability_snapshot: Any | None = None
        self._thresholds: Dict[str, Any] = {}
        self._seeds: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Collection helpers
    # ------------------------------------------------------------------
    def attach_observability(self, context: ObservabilityContext) -> None:
        self._observability = context

    def collect_versions(self, *, settings: "Settings") -> None:
        self._data["versions"] = {
            "policy_version": settings.policies.policy_version,
            "environment": settings.environment,
        }

    def collect_prompt_versions(
        self,
        registry: "PromptRegistry",
        *,
        prompt_keys: Optional[Iterable[str]] = None,
    ) -> None:
        if prompt_keys is None:
            raw_prompts = getattr(registry, "_raw_data", {}).get("prompts", {})
            keys = sorted(raw_prompts.keys())
        else:
            keys = sorted(set(prompt_keys))
        versions: Dict[str, str] = {}
        for prompt in keys:
            try:
                versions[prompt] = registry.active_version(prompt)
            except KeyError:
                continue
        self._data["prompt_versions"].update(versions)
        if self._observability:
            for prompt, version in versions.items():
                self._observability.register_prompt_version(prompt, version)

    def aggregate_statistics(self, label: str, stats: Dict[str, Any]) -> None:
        self._data["statistics"][label] = dict(stats)

    def sample_evidence(self, phase: str, evidence: Dict[str, Any]) -> None:
        sample = dict(evidence)
        sample["phase"] = phase
        self._data["evidence_samples"].append(sample)

    def capture_configuration(self, *, settings: "Settings") -> None:
        thresholds = {
            "level_thresholds": settings.policies.level_thresholds.model_dump(mode="json"),
            "deduplication": settings.policies.deduplication.model_dump(mode="json"),
            "validation": settings.policies.validation.model_dump(mode="json"),
        }
        seeds = {
            "settings.random_seed": settings.random_seed,
            "llm.random_seed": settings.policies.llm.random_seed,
        }
        if getattr(settings.policies.raw_extraction, "random_seed", None) is not None:
            seeds["raw_extraction.random_seed"] = settings.policies.raw_extraction.random_seed
        if getattr(settings.policies.level0_excel, "random_seed", None) is not None:
            seeds["level0_excel.random_seed"] = settings.policies.level0_excel.random_seed
        self._thresholds.update(thresholds)
        self._seeds.update(seeds)
        self._data["configuration"] = {
            "random_seed": settings.random_seed,
            "paths": {
                "data_dir": str(settings.paths.data_dir),
                "output_dir": str(settings.paths.output_dir),
                "metadata_dir": str(settings.paths.metadata_dir),
            },
            "policies": settings.policies.model_dump(mode="json"),
            "thresholds": thresholds,
            "seeds": seeds,
        }
        if self._observability:
            for name, value in seeds.items():
                self._observability.register_seed(name, value)
            for name, value in thresholds["level_thresholds"].items():
                self._observability.register_threshold(f"level_thresholds.{name}", value)

    def collect_operation_logs(self, logs: Iterable[Dict[str, Any]]) -> None:
        self._data["operation_logs"].extend(dict(log) for log in logs)

    def collect_performance_data(self, phase: str, metrics: Dict[str, Any]) -> None:
        self._data["performance"][phase] = dict(metrics)

    def capture_reproducibility_info(self, *, seed: int, timestamps: Dict[str, str]) -> None:
        self._data["reproducibility"] = {
            "seed": seed,
            "timestamps": dict(timestamps),
        }
        if self._observability:
            self._observability.register_seed("reproducibility.seed", seed)

    def summarize_hierarchy(self, *, stats: Dict[str, Any], validation: Dict[str, Any]) -> None:
        self._data["hierarchy"] = {
            "stats": dict(stats),
            "validation": dict(validation),
        }

    def add_artifact(self, path: Path | str, *, kind: str) -> None:
        self._data["artifacts"].append(
            {
                "path": str(Path(path).resolve()),
                "kind": kind,
            }
        )

    # ------------------------------------------------------------------
    # Finalisation
    # ------------------------------------------------------------------
    def _integrate_observability(self) -> None:
        if not self._observability:
            return
        snapshot = self._observability.snapshot()
        exported = self._observability.export()
        self._observability_snapshot = snapshot
        self._data["observability"] = exported
        # propagate observability-driven evidence and logs into legacy fields for compatibility
        evidence_samples: list[Dict[str, Any]] = []
        for phase, samples in exported.get("evidence", {}).get("samples", {}).items():
            for entry in samples:
                sample = dict(entry)
                sample["phase"] = phase
                evidence_samples.append(sample)
        self._data["evidence_samples"] = evidence_samples
        self._data["operation_logs"] = exported.get("operations", [])
        self._data.setdefault("prompt_versions", {}).update(exported.get("prompt_versions", {}))
        self._data.setdefault("configuration", {}).setdefault("seeds", {}).update(
            exported.get("seeds", {})
        )

    def _compute_checksums(self) -> None:
        payload = {key: value for key, value in self._data.items() if key != "checksums"}
        if self._observability_snapshot is not None:
            self._data["checksums"]["observability"] = self._observability_snapshot.checksum
        elif self._observability is not None:
            checksum = self._observability.snapshot().checksum
            self._data["checksums"]["observability"] = checksum
        if getattr(self._policy, "manifest_checksum_validation", True):
            self._data["checksums"]["manifest"] = stable_hash(payload)

    def finalize(self) -> Dict[str, Any]:
        _LOGGER.info("Finalising run manifest", run_id=self.run_id)
        self._integrate_observability()
        self._compute_checksums()
        self._data.setdefault("finalized_at", datetime.now(timezone.utc).isoformat())
        return dict(self._data)

    def to_dict(self) -> Dict[str, Any]:  # pragma: no cover - alias for callers
        return self.finalize()
