"""Provider abstraction wrapping DSPy-like provider integrations."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from .models import LLMOptions, ProviderError, ProviderResponse, TokenUsage

ProviderCallable = Callable[[str, Dict[str, Any]], ProviderResponse]


@dataclass
class ProviderProfile:
    """Concrete provider execution strategy."""

    name: str
    model: str
    provider: str
    call: ProviderCallable


class ProviderManager:
    """Manage multiple provider profiles and apply deterministic overrides."""

    def __init__(self, *, default_profile: str, profiles: Dict[str, ProviderProfile]) -> None:
        if default_profile not in profiles:
            raise ValueError(f"Unknown default profile '{default_profile}'")
        self._profiles = dict(profiles)
        self._active_profile = default_profile

    @property
    def active_profile(self) -> str:
        return self._active_profile

    def set_profile(self, profile_name: str) -> None:
        if profile_name not in self._profiles:
            raise ValueError(f"Provider profile '{profile_name}' is not registered")
        self._active_profile = profile_name

    def profile(self, name: Optional[str] = None) -> ProviderProfile:
        key = name or self._active_profile
        try:
            return self._profiles[key]
        except KeyError as exc:
            raise ValueError(f"Provider profile '{key}' is not registered") from exc

    def execute(self, prompt: str, options: LLMOptions) -> ProviderResponse:
        profile = self.profile(options.provider_hint)
        request_payload = self._build_payload(prompt=prompt, profile=profile, options=options)
        started = time.perf_counter()
        try:
            response = profile.call(prompt, request_payload)
        except ProviderError:
            raise
        except Exception as exc:  # pragma: no cover - defensive
            raise ProviderError(str(exc), retryable=True) from exc
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        normalized_usage = response.usage or TokenUsage()
        normalized_usage.prompt_tokens = int(normalized_usage.prompt_tokens)
        normalized_usage.completion_tokens = int(normalized_usage.completion_tokens)
        response.performance.latency_ms = elapsed_ms
        response.provider = profile.provider
        response.model = profile.model
        return response

    @staticmethod
    def _build_payload(*, prompt: str, profile: ProviderProfile, options: LLMOptions) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "prompt": prompt,
            "model": profile.model,
            "provider": profile.provider,
        }
        if options.temperature is not None:
            payload["temperature"] = options.temperature
        if options.max_output_tokens is not None:
            payload["max_output_tokens"] = options.max_output_tokens
        if options.seed is not None:
            payload["seed"] = options.seed
        if options.timeout_seconds is not None:
            payload["timeout"] = options.timeout_seconds
        if options.stop:
            payload["stop"] = list(options.stop)
        if options.retry_attempts is not None:
            payload["retry_attempts"] = options.retry_attempts
        return payload


__all__ = ["ProviderManager", "ProviderProfile"]
