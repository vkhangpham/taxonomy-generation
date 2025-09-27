"""High level LLM client built on top of the taxonomy configuration stack."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..config.policies import LLMDeterminismSettings
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
from .providers import ProviderManager
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
        attempts = 0
        last_error: Optional[str] = None
        backoff = self._settings.retry_backoff_seconds
        max_attempts = merged_options.retry_attempts or self._settings.retry_attempts
        while attempts <= max_attempts:
            attempts += 1
            try:
                provider_response = self._provider_manager.execute(rendered_prompt, merged_options)
            except ProviderError as exc:
                last_error = str(exc)
                self._metrics.incr("provider_error")
                if not exc.retryable or attempts > max_attempts:
                    return LLMResponse.failure(
                        raw=None,
                        tokens=TokenUsage(),
                        metadata=self._response_meta(prompt_meta, provider=None, repaired=False),
                        error=last_error,
                        latency_ms=0.0,
                    )
                time.sleep(backoff)
                backoff *= 2
                continue
            validation = self._validator.validate(
                provider_response.content,
                prompt_meta.schema_path,
                enforce_order_by=prompt_meta.enforce_order_by,
            )
            self._metrics.incr("calls_total")
            self._metrics.record_tokens(
                provider_response.usage.prompt_tokens,
                provider_response.usage.completion_tokens,
            )
            self._metrics.record_latency(provider_response.performance.latency_ms)
            if validation.ok:
                metadata = self._response_meta(
                    prompt_meta,
                    provider=provider_response,
                    repaired=validation.repaired,
                )
                return LLMResponse.success(
                    content=validation.parsed,
                    raw=provider_response.content,
                    tokens=provider_response.usage,
                    metadata=metadata,
                    latency_ms=provider_response.performance.latency_ms,
                )
            last_error = validation.error or "Unknown validation error"
            self._metrics.incr("invalid_json")
            if attempts > max_attempts:
                raise ValidationError(last_error, retryable=False)
            time.sleep(backoff)
            backoff *= 2
        raise QuarantineError(last_error or "LLM response quarantined")

    def _merge_options(self, options: LLMOptions) -> LLMOptions:
        defaults = {
            "temperature": self._settings.temperature,
            "max_output_tokens": self._settings.token_budget,
            "seed": self._settings.random_seed,
            "timeout_seconds": self._settings.request_timeout_seconds,
            "retry_attempts": self._settings.retry_attempts,
        }
        payload = {k: v for k, v in defaults.items() if v is not None}
        provided = options.model_dump(exclude_none=True)
        payload.update(provided)
        return LLMOptions.model_validate(payload)

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


def run(
    client: LLMClient,
    prompt_key: str,
    variables: Dict[str, Any],
    options: Optional[LLMOptions] = None,
) -> LLMResponse:
    """Convenience wrapper mirroring the core interface."""

    return client.run(prompt_key=prompt_key, variables=variables, options=options)


__all__ = ["LLMClient", "run"]
