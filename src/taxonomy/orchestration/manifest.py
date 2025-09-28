"""Run manifest generation utilities."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from taxonomy.config.settings import Settings
from taxonomy.utils.logging import get_logger

_LOGGER = get_logger(module=__name__)


class RunManifest:
    """Collects structured metadata about a taxonomy pipeline run."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
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
        }

    # ------------------------------------------------------------------
    # Collection helpers
    # ------------------------------------------------------------------
    def collect_versions(self, *, settings: Settings) -> None:
        self._data["versions"] = {
            "policy_version": settings.policies.policy_version,
            "environment": settings.environment,
        }

    def aggregate_statistics(self, label: str, stats: Dict[str, Any]) -> None:
        self._data["statistics"][label] = dict(stats)

    def sample_evidence(self, phase: str, evidence: Dict[str, Any]) -> None:
        sample = dict(evidence)
        sample["phase"] = phase
        self._data["evidence_samples"].append(sample)

    def capture_configuration(self, *, settings: Settings) -> None:
        self._data["configuration"] = {
            "random_seed": settings.random_seed,
            "paths": {
                "data_dir": str(settings.paths.data_dir),
                "output_dir": str(settings.paths.output_dir),
                "metadata_dir": str(settings.paths.metadata_dir),
            },
            "policies": settings.policies.model_dump(mode="json"),
        }

    def collect_operation_logs(self, logs: Iterable[Dict[str, Any]]) -> None:
        self._data["operation_logs"].extend(dict(log) for log in logs)

    def collect_performance_data(self, phase: str, metrics: Dict[str, Any]) -> None:
        self._data["performance"][phase] = dict(metrics)

    def capture_reproducibility_info(self, *, seed: int, timestamps: Dict[str, str]) -> None:
        self._data["reproducibility"] = {
            "seed": seed,
            "timestamps": dict(timestamps),
        }

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
    def finalize(self) -> Dict[str, Any]:
        _LOGGER.info("Finalising run manifest", run_id=self.run_id)
        self._data.setdefault("finalized_at", datetime.now(timezone.utc).isoformat())
        return dict(self._data)

    def to_dict(self) -> Dict[str, Any]:  # pragma: no cover - alias for callers
        return self.finalize()


__all__ = ["RunManifest"]
