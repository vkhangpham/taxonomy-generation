"""High level LLM client built on top of the taxonomy configuration stack."""

from __future__ import annotations

import time
import threading
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import yaml

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..config.policies import LLMDeterminismSettings, load_policies
from ..config.settings import Settings
from .models import (
    LLMOptions,
    LLMRequest,
    LLMResponse,
    ProviderError,
    QuarantineError,
    TokenUsage,
    ValidationError,
)
from .observability import MetricsCollector
from .providers import ProviderManager, build_provider_manager
from .registry import PromptRegistry
from .validation import JSONValidator


class LLMClient:
    """Primary entry point for prompt driven taxonomy LLM workflows."""

    def __init__(
        self,
        *,
        settings: LLMDeterminismSettings,
        registry: PromptRegistry,
        provider_manager: ProviderManager,
        validator: JSONValidator,
        metrics: Optional[MetricsCollector] = None,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._provider_manager = provider_manager
        self._validator = validator
        self._metrics = metrics or MetricsCollector()
        self._metrics_enabled = settings.observability.metrics_enabled
        self._provider_manager.configure_policy_defaults(
            top_p=self._settings.nucleus_top_p,
            json_mode=self._settings.json_mode,
        )
        templates_root = Path(settings.registry.templates_root)
        if not templates_root.exists():
            raise FileNotFoundError(f"Templates directory missing: {templates_root}")
        self._env = Environment(
            loader=FileSystemLoader(str(templates_root)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined,
        )

    def set_profile(self, profile_name: str) -> None:
        self._provider_manager.set_profile(profile_name)

    def active_version(self, prompt_key: str) -> str:
        return self._registry.active_version(prompt_key)

    def run(
        self,
        prompt_key: str,
        variables: Dict[str, Any],
        options: Optional[LLMOptions] = None,
    ) -> LLMResponse:
        request = LLMRequest(prompt_key=prompt_key, variables=variables, options=options or LLMOptions())
        prompt_meta = self._registry.load_prompt(request.prompt_key)
        template = self._env.get_template(prompt_meta.template_path)
        rendered_prompt = template.render(**request.variables)
        merged_options = self._merge_options(request.options)
        total_attempts = 1 + (merged_options.retry_attempts or self._settings.retry_attempts)
        quarantine_threshold = max(1, self._settings.repair.quarantine_after_attempts)
        failures = 0
        backoff = max(0.0, self._settings.retry_backoff_seconds)
        constrained_prompt: Optional[str] = None
        constrained_applied = False
        schema_hint: Optional[str] = None
        last_error: Optional[str] = None

        for attempt in range(total_attempts):
            prompt_to_use = constrained_prompt or rendered_prompt
            try:
                provider_response = self._provider_manager.execute(prompt_to_use, merged_options)
            except ProviderError as exc:
                last_error = str(exc)
                failures += 1
                self._metric("provider_error")
                retryable = exc.retryable and attempt < total_attempts - 1
                if not retryable:
                    return LLMResponse.failure(
                        raw=None,
                        tokens=TokenUsage(),
                        metadata=self._response_meta(prompt_meta, provider=None, repaired=False),
                        error=last_error,
                        latency_ms=0.0,
                    )
                if failures >= quarantine_threshold:
                    self._metric("quarantined")
                    raise QuarantineError(last_error or "LLM response quarantined")
                self._metric("retries")
                if backoff > 0:
                    time.sleep(backoff)
                    backoff *= 2
                continue

            validation = self._validator.validate(
                provider_response.content,
                prompt_meta.schema_path,
                enforce_order_by=prompt_meta.enforce_order_by,
            )
            self._metric("calls_total")
            self._record_tokens(
                provider_response.usage.prompt_tokens,
                provider_response.usage.completion_tokens,
            )
            self._record_latency(provider_response.performance.latency_ms)

            if validation.ok:
                metadata = self._response_meta(
                    prompt_meta,
                    provider=provider_response,
                    repaired=validation.repaired,
                )
                self._metric("ok")
                return LLMResponse.success(
                    content=validation.parsed,
                    raw=provider_response.content,
                    tokens=provider_response.usage,
                    metadata=metadata,
                    latency_ms=provider_response.performance.latency_ms,
                )

            last_error = validation.error or "Unknown validation error"
            failures += 1
            self._metric("invalid_json")

            first_retry_eligible = not constrained_applied and attempt < total_attempts - 1
            if first_retry_eligible:
                if schema_hint is None:
                    schema_hint = self._validator.describe_schema(prompt_meta.schema_path)
                constrained_prompt = self._build_constrained_prompt(rendered_prompt, schema_hint)
                constrained_applied = True
                if merged_options.json_mode is not True:
                    merged_options = merged_options.model_copy(update={"json_mode": True})

            if failures >= quarantine_threshold and not first_retry_eligible:
                self._metric("quarantined")
                raise QuarantineError(last_error)

            if attempt == total_attempts - 1:
                raise ValidationError(last_error, retryable=False)

            self._metric("retries")
            if backoff > 0 and attempt < total_attempts - 1:
                time.sleep(backoff)
                backoff *= 2

        self._metric("quarantined")
        raise QuarantineError(last_error or "LLM response quarantined")

    def _merge_options(self, options: LLMOptions) -> LLMOptions:
        defaults = {
            "temperature": self._settings.temperature,
            "max_output_tokens": self._settings.token_budget,
            "seed": self._settings.random_seed,
            "timeout_seconds": self._settings.request_timeout_seconds,
            "retry_attempts": self._settings.retry_attempts,
            "top_p": self._settings.nucleus_top_p,
            "json_mode": self._settings.json_mode,
        }
        payload = {k: v for k, v in defaults.items() if v is not None}
        provided = options.model_dump(exclude_none=True)
        payload.update(provided)
        return LLMOptions.model_validate(payload)

    @staticmethod
    def _build_constrained_prompt(rendered_prompt: str, schema_hint: str) -> str:
        constraint = f"Only return JSON conforming to schema: {schema_hint}."
        if rendered_prompt.rstrip().endswith(constraint):
            return rendered_prompt
        return f"{rendered_prompt}\n\n{constraint}"

    def _metric(self, name: str, value: int = 1) -> None:
        if self._metrics_enabled:
            self._metrics.incr(name, value)

    def _record_latency(self, value_ms: float) -> None:
        if self._metrics_enabled:
            self._metrics.record_latency(value_ms)

    def _record_tokens(self, prompt_tokens: int, completion_tokens: int) -> None:
        if self._metrics_enabled:
            self._metrics.record_tokens(prompt_tokens, completion_tokens)

    def _response_meta(
        self,
        prompt_meta,
        *,
        provider: Optional[Any],
        repaired: bool,
    ) -> Dict[str, Any]:
        meta = {
            "prompt_key": prompt_meta.prompt_key,
            "prompt_version": prompt_meta.version,
            "repaired": repaired,
        }
        if provider is not None:
            meta.update({
                "provider": provider.provider,
                "model": provider.model,
            })
        return meta


_DEFAULT_CLIENT_LOCK = threading.Lock()
_DEFAULT_CLIENT: Optional[LLMClient] = None


def get_default_client(
    *, config_path: Optional[Path] = None, force_reload: bool = False
) -> LLMClient:
    """Return a lazily constructed singleton LLMClient bound to default policies."""

    global _DEFAULT_CLIENT
    if force_reload:
        with _DEFAULT_CLIENT_LOCK:
            _DEFAULT_CLIENT = _build_default_client(config_path)
            return _DEFAULT_CLIENT
    if _DEFAULT_CLIENT is None:
        with _DEFAULT_CLIENT_LOCK:
            if _DEFAULT_CLIENT is None:
                _DEFAULT_CLIENT = _build_default_client(config_path)
    return _DEFAULT_CLIENT


def run(prompt_key: str, variables: Dict[str, Any], options: Optional[LLMOptions] = None) -> LLMResponse:
    """Execute a prompt using the default DSPy-backed LLM client."""

    client = get_default_client()
    return client.run(prompt_key=prompt_key, variables=variables, options=options)


def _load_policies_from_source(config_file: Path) -> Any:
    """Resolve a policies payload from *config_file*.

    ``config_file`` may point to a YAML settings bundle containing a top-level
    ``policies`` key, a standalone policies YAML file, or even a directory that
    should be treated as a configuration root. The helper normalises these
    shapes into the mapping expected by :func:`load_policies`.
    """

    if config_file.is_dir():
        return Settings(config_dir=config_file).policies

    if config_file.suffix.lower() in {".yaml", ".yml"} and config_file.exists():
        with config_file.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
        if not isinstance(loaded, Mapping):
            raise ValueError(
                f"Policy configuration '{config_file}' must contain a mapping"
            )
        source = loaded.get("policies", loaded)
        return load_policies(source)

    # Fallback to direct loading (supports JSON/YAML files without .yaml suffix).
    return load_policies(config_file)


def _build_default_client(config_path: Optional[Path]) -> LLMClient:
    project_root = Path(__file__).resolve().parents[3]
    if config_path is None:
        policies = Settings().policies
    else:
        policies = _load_policies_from_source(Path(config_path))
        if not hasattr(policies, "llm"):
            policies = load_policies(policies)
    settings = policies.llm

    registry_file = (project_root / settings.registry.file).resolve()
    templates_root = (project_root / settings.registry.templates_root).resolve()
    schema_root = (project_root / settings.registry.schema_root).resolve()

    settings.registry.file = str(registry_file)
    settings.registry.templates_root = str(templates_root)
    settings.registry.schema_root = str(schema_root)

    registry = PromptRegistry(registry_file=registry_file, hot_reload=settings.registry.hot_reload)
    validator = JSONValidator(schema_base_path=schema_root)

    try:
        provider_manager = build_provider_manager(settings)
    except ProviderError as exc:  # pragma: no cover - exercised when DSPy missing
        raise RuntimeError("Failed to initialize DSPy provider integration") from exc

    metrics = MetricsCollector()
    return LLMClient(
        settings=settings,
        registry=registry,
        provider_manager=provider_manager,
        validator=validator,
        metrics=metrics,
    )


__all__ = ["LLMClient", "run", "get_default_client"]
