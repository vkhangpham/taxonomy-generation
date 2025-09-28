"""Run manifest generation for taxonomy pipeline executions."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import threading
from typing import Any, Dict, Iterable, Mapping, Optional, TYPE_CHECKING

from taxonomy.observability import stable_hash
from taxonomy.utils.helpers import serialize_json
from taxonomy.utils.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing convenience
    from taxonomy.config.policies import ObservabilityPolicy
    from taxonomy.config.settings import Settings
    from taxonomy.llm.registry import PromptRegistry
    from taxonomy.observability import ObservabilityContext
    from taxonomy.observability.manifest import ObservabilityManifest

_LOGGER = get_logger(module=__name__)


class RunManifest:
    """Collects structured metadata about a taxonomy pipeline run."""

    def __init__(
        self,
        run_id: str,
        *,
        policy: Optional[ObservabilityPolicy] = None,
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
        self._observability: Optional[ObservabilityContext] = None
        self._observability_snapshot: Any | None = None
        self._observability_manifest: Optional[ObservabilityManifest] = None
        self._thresholds: Dict[str, Any] = {}
        self._seeds: Dict[str, int] = {}
        self._observability_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Collection helpers
    # ------------------------------------------------------------------
    def attach_observability(self, context: ObservabilityContext) -> None:
        self._observability = context
        self._observability_snapshot = None
        self._observability_manifest = None

    def _ensure_observability_manifest(self) -> Optional[ObservabilityManifest]:
        if self._observability_manifest is not None:
            return self._observability_manifest
        if not self._observability:
            return None

        with self._observability_lock:
            if self._observability_manifest is not None:
                return self._observability_manifest

            obs_policy = getattr(self._observability, "policy", None)
            policy = obs_policy if obs_policy is not None else self._policy
            manifest_enabled = True if policy is None else getattr(
                policy,
                "audit_trail_generation",
                True,
            )
            if not manifest_enabled:
                return None

            from taxonomy.observability.manifest import ObservabilityManifest

            self._observability_manifest = ObservabilityManifest(context=self._observability)
            return self._observability_manifest

    def collect_versions(self, *, settings: "Settings") -> None:
        self._data["versions"] = {
            "policy_version": settings.policies.policy_version,
            "environment": settings.environment,
        }

    def _coerce_prompt_versions(self, payload: Any) -> Dict[str, str]:
        if not payload:
            return {}
        if isinstance(payload, Mapping):
            items = payload.items()
        else:
            try:
                items = dict(payload).items()
            except (TypeError, ValueError):
                _LOGGER.warning(
                    "Unexpected prompt version payload type %s; ignoring manifest contribution",
                    type(payload).__name__,
                )
                return {}

        coerced: Dict[str, str] = {}
        for name, version in items:
            if name is None or version is None:
                continue
            coerced[str(name)] = str(version)
        return coerced

    def _resolve_prompt_keys(
        self,
        registry: "PromptRegistry",
        prompt_keys: Optional[Iterable[str]] = None,
    ) -> list[str]:
        if prompt_keys is not None:
            return sorted({str(key) for key in prompt_keys})

        for accessor in ("list_prompt_keys", "all_prompt_keys"):
            candidate = getattr(registry, accessor, None)
            if callable(candidate):
                try:
                    keys = list(candidate())
                except Exception as exc:  # pragma: no cover - defensive guard
                    _LOGGER.warning(
                        "Prompt registry accessor %s failed; falling back to other sources",
                        accessor,
                        exc_info=(type(exc), exc, exc.__traceback__),
                    )
                    continue
                return sorted({str(key) for key in keys})

        try:
            raw_data = getattr(registry, "_raw_data")
        except AttributeError:
            _LOGGER.warning(
                "Prompt registry does not expose prompt keys and private _raw_data is unavailable; skipping prompt version fallback",
            )
            return []

        if isinstance(raw_data, Mapping):
            prompts = raw_data.get("prompts", {}) or {}
        else:
            _LOGGER.warning(
                "Prompt registry _raw_data is not a mapping; skipping prompt version fallback",
            )
            return []

        _LOGGER.warning(
            "Prompt registry missing public prompt key accessor; using private _raw_data fallback",
        )
        return sorted({str(key) for key in prompts.keys()})

    def _select_prompt_versions(
        self,
        registry: "PromptRegistry",
        *,
        prompt_keys: Optional[Iterable[str]] = None,
    ) -> tuple[Dict[str, str], str]:
        """Return prompt version payloads and the source used.

        Precedence: (1) an attached observability manifest if available, (2) a
        deterministic registry fallback based on resolved prompt keys.
        """
        manifest = self._ensure_observability_manifest()
        if manifest is not None:
            payload = manifest.collect_prompt_versions(
                registry,
                prompt_keys=prompt_keys,
            )
            return (payload or {}, "manifest")

        keys = self._resolve_prompt_keys(registry, prompt_keys=prompt_keys)
        fallback_payload: Dict[str, str] = {}
        for prompt in keys:
            try:
                fallback_payload[prompt] = registry.active_version(prompt)
            except KeyError:
                continue
        return fallback_payload, "registry"

    def collect_prompt_versions(
        self,
        registry: "PromptRegistry",
        *,
        prompt_keys: Optional[Iterable[str]] = None,
    ) -> None:
        versions_payload, source = self._select_prompt_versions(
            registry,
            prompt_keys=prompt_keys,
        )
        versions = self._coerce_prompt_versions(versions_payload)

        if source == "registry" and not versions:
            _LOGGER.debug(
                "Prompt registry fallback returned no prompt versions for run %s",
                self.run_id,
            )

        if self._observability:
            for prompt, version in versions.items():
                self._observability.register_prompt_version(prompt, version)

        if versions:
            self._data["prompt_versions"].update(versions)

    def aggregate_statistics(self, label: str, stats: Dict[str, Any]) -> None:
        self._data["statistics"][label] = dict(stats)

    def sample_evidence(self, phase: str, evidence: Dict[str, Any]) -> None:
        sample = dict(evidence)
        sample["phase"] = phase
        self._data["evidence_samples"].append(sample)

    def capture_configuration(self, *, settings: "Settings") -> None:
        manifest = self._ensure_observability_manifest()
        if manifest is not None:
            thresholds = manifest.capture_thresholds(settings)
            seeds = manifest.capture_seeds(settings)
        else:
            thresholds = {
                "level_thresholds": settings.policies.level_thresholds.model_dump(mode="json"),
                "deduplication": settings.policies.deduplication.model_dump(mode="json"),
                "validation": settings.policies.validation.model_dump(mode="json"),
            }
            seeds = {
                "settings.random_seed": settings.random_seed,
                "llm.random_seed": settings.policies.llm.random_seed,
            }
            raw_seed = getattr(settings.policies.raw_extraction, "random_seed", None)
            if raw_seed is not None:
                seeds["raw_extraction.random_seed"] = raw_seed
            level_seed = getattr(settings.policies.level0_excel, "random_seed", None)
            if level_seed is not None:
                seeds["level0_excel.random_seed"] = level_seed
            seeds = {name: value for name, value in seeds.items() if value is not None}
            if self._observability:
                for name, value in seeds.items():
                    self._observability.register_seed(name, value)
                for name, value in thresholds.get("level_thresholds", {}).items():
                    self._observability.register_threshold(f"level_thresholds.{name}", value)
        seeds = {name: value for name, value in seeds.items() if value is not None}
        self._thresholds.update(thresholds)
        seeds_as_int = {k: int(v) for k, v in seeds.items()}
        self._seeds.update(seeds_as_int)
        self._data["configuration"] = {
            "random_seed": settings.random_seed,
            "paths": {
                "data_dir": str(settings.paths.data_dir),
                "output_dir": str(settings.paths.output_dir),
                "metadata_dir": str(settings.paths.metadata_dir),
            },
            "policies": settings.policies.model_dump(mode="json"),
            "thresholds": thresholds,
            "seeds": seeds_as_int,
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
    def _metadata_directory(self) -> Path | None:
        paths = self._data.get("configuration", {}).get("paths", {})
        metadata_dir = paths.get("metadata_dir")
        if not metadata_dir:
            return None
        try:
            return Path(metadata_dir).resolve()
        except (TypeError, OSError):  # pragma: no cover - defensive guard
            return None

    def _active_policy_attr(self, attribute: str, default: Any) -> Any:
        """Return an attribute from the currently effective observability policy."""
        policy = getattr(self._observability, "policy", None)
        if policy is None:
            policy = self._policy
        return getattr(policy, attribute, default) if policy is not None else default

    def _build_observability_payload(
        self,
        manifest: "ObservabilityManifest",
    ) -> Dict[str, Any]:
        """Collect and coerce the observability payload before integration."""
        fail_fast = bool(self._active_policy_attr("fail_fast_observability", False))
        with self._observability_lock:
            try:
                snapshot = manifest.snapshot()
                payload = manifest.build_payload(snapshot)
            except Exception as exc:  # pragma: no cover - defensive guard
                if fail_fast:
                    raise
                _LOGGER.exception(
                    "Observability payload generation failed for run %s; skipping integration (%s)",
                    self.run_id,
                    exc,
                )
                return {}
            self._observability_snapshot = snapshot

        if isinstance(payload, Mapping):
            return dict(payload)

        try:
            exported = dict(payload)  # type: ignore[arg-type]
        except (TypeError, ValueError) as coerce_error:
            if fail_fast:
                raise
            _LOGGER.error(
                "Observability payload for run %s is not mapping-compatible; using empty payload (type=%s)",
                self.run_id,
                type(payload).__name__,
            )
            _LOGGER.debug("Observability payload coercion error", exc_info=coerce_error)
            return {}

        _LOGGER.warning(
            "Observability payload for run %s is not a mapping; coerced to dict via dict() (type=%s)",
            self.run_id,
            type(payload).__name__,
        )
        return exported

    def _validate_and_merge_seeds(
        self,
        exported: Mapping[str, Any],
        *,
        configuration: Dict[str, Any],
    ) -> tuple[Dict[str, int], list[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        """Validate observability seeds and merge them into the manifest."""
        seeds_obj = exported.get("seeds", {}) if isinstance(exported, Mapping) else {}
        validated_seeds: Dict[str, int] = {}
        rejected_seeds: list[Dict[str, Any]] = []

        if isinstance(seeds_obj, Mapping):
            for name, value in seeds_obj.items():
                key = str(name)
                try:
                    validated_seeds[key] = int(value)
                except (TypeError, ValueError):
                    rejected_seeds.append({"name": key, "raw_value": value})
                    _LOGGER.warning(
                        "Skipping invalid observability seed for run %s; key=%s value=%r",
                        self.run_id,
                        name,
                        value,
                    )
        elif seeds_obj:
            _LOGGER.warning(
                "Observability seeds payload for run %s is not mapping-compatible; skipping seed coercion (type=%s)",
                self.run_id,
                type(seeds_obj).__name__,
            )

        manifest_seeds = configuration.setdefault("seeds", dict(self._seeds))
        conflicts: Dict[str, Dict[str, Any]] = {}
        for name, value in validated_seeds.items():
            if name in manifest_seeds:
                existing_value = manifest_seeds[name]
                if existing_value != value:
                    conflicts[name] = {"kept": existing_value, "ignored": value}
                    _LOGGER.info(
                        "Observability seed conflict for run %s; keeping existing value for %s (existing=%r, observability=%r)",
                        self.run_id,
                        name,
                        existing_value,
                        value,
                    )
                    continue
            else:
                manifest_seeds[name] = value

            self._seeds[name] = manifest_seeds[name]
            if self._observability:
                self._observability.register_seed(name, manifest_seeds[name])

        if isinstance(exported, dict):
            exported["seeds"] = dict(validated_seeds)
        else:
            try:
                exported["seeds"] = dict(validated_seeds)  # type: ignore[index]
            except Exception:  # pragma: no cover - defensive guard
                pass

        return dict(validated_seeds), rejected_seeds, conflicts

    def _redact_observability_payload(
        self,
        payload: Mapping[str, Any],
        *,
        redacted_keys: Iterable[str],
    ) -> tuple[Dict[str, Any], set[str]]:
        """Return a redacted copy of *payload* while tracking affected keys."""
        keys = {key.lower() for key in redacted_keys if key}
        redacted_fields: set[str] = set()

        def _sanitize(value: Any) -> Any:
            if isinstance(value, Mapping):
                sanitized: Dict[str, Any] = {}
                for raw_key, raw_value in value.items():
                    key = str(raw_key)
                    if key.lower() in keys:
                        redacted_fields.add(key)
                        sanitized[key] = "[redacted]"
                    else:
                        sanitized[key] = _sanitize(raw_value)
                return sanitized
            if isinstance(value, list | tuple):
                return [_sanitize(item) for item in value]
            return value

        source = payload if isinstance(payload, Mapping) else dict(payload)
        sanitized_payload = _sanitize(source)
        return dict(sanitized_payload), redacted_fields

    def _attach_observability_file(self, exported: Mapping[str, Any]) -> tuple[Dict[str, Any], Path | None]:
        """Persist the redacted observability payload to disk and register the artifact."""
        fail_fast = bool(self._active_policy_attr("fail_fast_observability", False))
        redacted_keys = self._active_policy_attr(
            "redact_observability_fields",
            ("authorization", "api_key", "apiKey", "secret", "token", "password"),
        )
        redacted_payload, redacted_fields = self._redact_observability_payload(
            exported,
            redacted_keys=redacted_keys if isinstance(redacted_keys, Iterable) else (),
        )

        metadata_dir = self._metadata_directory()
        if metadata_dir is None:
            fallback_dir = Path.cwd()
            _LOGGER.warning(
                "Metadata directory unavailable for run %s; defaulting to %s for observability payload",
                self.run_id,
                fallback_dir,
            )
            metadata_dir = fallback_dir
        else:
            try:
                metadata_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                if fail_fast:
                    raise
                fallback_dir = Path.cwd()
                _LOGGER.error(
                    "Failed to create metadata directory %s for run %s; defaulting to %s (%s)",
                    metadata_dir,
                    self.run_id,
                    fallback_dir,
                    exc,
                )
                metadata_dir = fallback_dir

        try:
            observability_path = serialize_json(
                redacted_payload,
                metadata_dir / f"{self.run_id}.observability.json",
            )
        except (OSError, TypeError, ValueError) as exc:
            if fail_fast:
                raise
            _LOGGER.exception(
                "Failed to serialize observability payload for run %s; skipping attachment (%s)",
                self.run_id,
                exc,
            )
            return {}, None

        resolved_path = observability_path.resolve()
        observability_record: Dict[str, Any] = {
            "path": str(resolved_path),
            "checksum": stable_hash(redacted_payload),
        }
        if redacted_fields:
            observability_record["redacted_fields"] = sorted(redacted_fields)
        self.add_artifact(resolved_path, kind="observability")
        return observability_record, observability_path

    def _normalize_observability_evidence(self, evidence_section: Any) -> list[Dict[str, Any]]:
        """Normalize evidence samples contributed by observability."""
        if not isinstance(evidence_section, Mapping):
            if evidence_section:
                _LOGGER.warning(
                    "Observability evidence payload for run %s is not mapping-compatible; skipping integration (type=%s)",
                    self.run_id,
                    type(evidence_section).__name__,
                )
            return []

        samples_section = evidence_section.get("samples", {})
        if not isinstance(samples_section, Mapping):
            if samples_section:
                _LOGGER.warning(
                    "Observability evidence samples payload for run %s is not mapping-compatible; skipping integration (type=%s)",
                    self.run_id,
                    type(samples_section).__name__,
                )
            return []

        normalized: list[Dict[str, Any]] = []
        for phase, samples in samples_section.items():
            if isinstance(samples, (str, bytes)) or not isinstance(samples, Iterable):
                _LOGGER.warning(
                    "Observability evidence samples for run %s and phase %s are not iterable; skipping (type=%s)",
                    self.run_id,
                    phase,
                    type(samples).__name__,
                )
                continue
            for entry in samples:
                if not isinstance(entry, Mapping):
                    _LOGGER.warning(
                        "Observability evidence entry for run %s and phase %s is not a mapping; skipping (type=%s)",
                        self.run_id,
                        phase,
                        type(entry).__name__,
                    )
                    continue
                sample = dict(entry)
                sample["phase"] = str(phase)
                normalized.append(sample)
        return normalized

    def _normalize_operations_payload(self, operations_section: Any) -> list[Dict[str, Any]]:
        """Normalize operation log entries from observability."""
        if isinstance(operations_section, Mapping) or isinstance(operations_section, (str, bytes)):
            if operations_section:
                _LOGGER.warning(
                    "Observability operations payload for run %s is not iterable; skipping (type=%s)",
                    self.run_id,
                    type(operations_section).__name__,
                )
            return []

        if not isinstance(operations_section, Iterable):
            if operations_section:
                _LOGGER.warning(
                    "Observability operations payload for run %s is not iterable; skipping (type=%s)",
                    self.run_id,
                    type(operations_section).__name__,
                )
            return []

        normalized: list[Dict[str, Any]] = []
        for entry in operations_section:
            if not isinstance(entry, Mapping):
                _LOGGER.warning(
                    "Observability operation entry for run %s is not a mapping; skipping (type=%s)",
                    self.run_id,
                    type(entry).__name__,
                )
                continue
            normalized.append(dict(entry))
        return normalized

    def _integrate_observability(self) -> None:
        if not self._observability:
            return

        manifest = self._ensure_observability_manifest()
        if manifest is None:
            return

        exported = self._build_observability_payload(manifest)
        if not exported:
            _LOGGER.info(
                "Observability payload for run %s is empty; proceeding without persisted data",
                self.run_id,
            )

        configuration = self._data.setdefault("configuration", {})
        _, rejected_seeds, conflicts = self._validate_and_merge_seeds(
            exported,
            configuration=configuration,
        )

        observability_record, observability_path = self._attach_observability_file(exported)

        evidence_samples = self._normalize_observability_evidence(exported.get("evidence", {}))
        if evidence_samples:
            legacy_samples = list(self._data.get("evidence_samples", []))
            legacy_samples.extend(evidence_samples)
            self._data["evidence_samples"] = legacy_samples

        operations_entries = self._normalize_operations_payload(exported.get("operations", []))
        if operations_entries:
            legacy_logs = list(self._data.get("operation_logs", []))
            legacy_logs.extend(operations_entries)
            self._data["operation_logs"] = legacy_logs

        prompt_versions = self._coerce_prompt_versions(exported.get("prompt_versions", {}))
        if prompt_versions:
            self._data.setdefault("prompt_versions", {}).update(prompt_versions)

        thresholds_payload = exported.get("thresholds", {}) if isinstance(exported, Mapping) else {}
        if isinstance(thresholds_payload, Mapping):
            configuration.setdefault("thresholds", {}).update(dict(thresholds_payload))
            self._thresholds.update(dict(thresholds_payload))
        elif thresholds_payload:
            _LOGGER.warning(
                "Observability thresholds payload for run %s is not mapping-compatible; skipping integration (type=%s)",
                self.run_id,
                type(thresholds_payload).__name__,
            )

        observability_meta = self._data.setdefault("observability", {})
        if observability_record:
            observability_meta.update(observability_record)
        if rejected_seeds:
            observability_meta.setdefault("rejected_seeds", []).extend(rejected_seeds)
        if conflicts:
            observability_meta.setdefault("seed_conflicts", {}).update(conflicts)

        if observability_path is None and not observability_record:
            _LOGGER.info(
                "Observability integration completed for run %s without file attachment",
                self.run_id,
            )

    def _canonical_checksum_payload(self) -> Dict[str, Any]:
        """Return a deterministic, size-limited snapshot for checksum calculation."""
        canonical_keys = (
            "run_id",
            "generated_at",
            "configuration",
            "statistics",
            "prompt_versions",
            "observability",
            "artifacts",
        )
        canonical: Dict[str, Any] = {}
        for key in canonical_keys:
            if key not in self._data:
                continue
            value = self._data[key]
            if key == "artifacts" and isinstance(value, Iterable):
                canonical[key] = sorted(
                    (dict(entry) for entry in value if isinstance(entry, Mapping)),
                    key=lambda entry: entry.get("path", ""),
                )
            else:
                canonical[key] = value
        return canonical

    def _compute_checksums(self) -> None:
        """Compute manifest checksums using a canonical subset of the payload.

        ``stable_hash`` expects a canonical, repeatable structure. We hash a curated
        subset instead of the full manifest to avoid quadratic hashing costs for
        very large payloads. For even heavier manifests we could extend this to a
        progressive hashing strategy that batches data into chunks or offloads the
        work to a background task.
        """
        if self._observability_snapshot is not None:
            self._data["checksums"]["observability"] = self._observability_snapshot.checksum
        elif self._observability is not None:
            checksum = self._observability.snapshot().checksum
            self._data["checksums"]["observability"] = checksum

        if getattr(self._policy, "manifest_checksum_validation", True):
            canonical_payload = self._canonical_checksum_payload()
            self._data["checksums"]["manifest"] = stable_hash(canonical_payload)

    def _set_finalization_timestamp(self) -> None:
        """Populate ``finalized_at`` with a UTC timestamp if missing."""
        self._data.setdefault("finalized_at", datetime.now(timezone.utc).isoformat())

    def finalize(self) -> Dict[str, Any]:
        _LOGGER.info("Finalising run manifest for run %s", self.run_id)
        fail_fast = bool(self._active_policy_attr("fail_fast_observability", False))

        try:
            self._integrate_observability()
        except Exception as exc:  # pragma: no cover - defensive guard
            _LOGGER.exception(
                "Observability integration failed during finalize for run %s; continuing without observability (%s)",
                self.run_id,
                exc,
            )
            if fail_fast:
                raise
        try:
            self._compute_checksums()
        except Exception as exc:  # pragma: no cover - defensive guard
            _LOGGER.exception(
                "Checksum computation failed during finalize for run %s; continuing without checksum updates (%s)",
                self.run_id,
                exc,
            )
        try:
            self._set_finalization_timestamp()
        except Exception as exc:  # pragma: no cover - defensive guard
            _LOGGER.exception(
                "Finalization timestamp update failed for run %s; leaving value unchanged (%s)",
                self.run_id,
                exc,
            )
        return dict(self._data)

    def to_dict(self) -> Dict[str, Any]:  # pragma: no cover - alias for callers
        return self.finalize()
