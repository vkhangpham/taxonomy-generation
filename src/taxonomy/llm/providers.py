"""Provider abstraction wrapping DSPy-like provider integrations."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from .models import LLMOptions, ProviderError, ProviderResponse, TokenUsage

ProviderCallable = Callable[[str, Dict[str, Any]], ProviderResponse]


logger = logging.getLogger(__name__)


@dataclass
class ProviderProfile:
    """Concrete provider execution strategy."""

    name: str
    model: str
    provider: str
    call: ProviderCallable


class ProviderManager:
    """Manage multiple provider profiles and apply deterministic overrides."""

    def __init__(
        self,
        *,
        default_profile: str,
        profiles: Dict[str, ProviderProfile],
        policy_defaults: Optional[Dict[str, Any]] = None,
    ) -> None:
        if default_profile not in profiles:
            raise ValueError(f"Unknown default profile '{default_profile}'")
        self._profiles = dict(profiles)
        self._active_profile = default_profile
        self._policy_defaults: Dict[str, Any] = dict(policy_defaults or {})

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

    def configure_policy_defaults(self, **defaults: Any) -> None:
        """Update deterministic policy defaults used during payload construction."""

        self._policy_defaults.update({k: v for k, v in defaults.items() if v is not None})

    def _build_payload(self, *, prompt: str, profile: ProviderProfile, options: LLMOptions) -> Dict[str, Any]:
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
        if options.top_p is not None:
            payload["top_p"] = options.top_p
        elif "top_p" in self._policy_defaults:
            payload["top_p"] = self._policy_defaults["top_p"]
        if options.json_mode is not None:
            payload["json_mode"] = options.json_mode
        elif "json_mode" in self._policy_defaults:
            payload["json_mode"] = self._policy_defaults["json_mode"]
        return payload


class DSPyProviderAdapter:
    """Callable adapter translating taxonomy payloads to DSPy LM invocations."""

    SUPPORTED_PROVIDERS = {"openai", "azure_openai"}

    def __init__(self, *, provider: str, model: str) -> None:
        self._provider = provider
        self._model = model
        self._client = self._build_client()

    def __call__(self, prompt: str, payload: Dict[str, Any]) -> ProviderResponse:
        params = dict(payload)
        params.pop("prompt", None)
        params.pop("provider", None)
        params.pop("model", None)

        # Translate taxonomy options into DSPy/OpenAI keywords.
        if "max_output_tokens" in params:
            params["max_tokens"] = params.pop("max_output_tokens")
        if params.pop("json_mode", False):
            params.setdefault("response_format", {"type": "json_object"})

        try:
            raw_response = self._client(prompt=prompt, **params)
        except ProviderError:
            raise
        except Exception as exc:  # pragma: no cover - defensive guard
            raise ProviderError(str(exc), retryable=True) from exc

        content = self._extract_text(raw_response)
        content = self._normalise_payload(content)
        usage = self._extract_usage(raw_response)
        return ProviderResponse(content=content, usage=usage)

    def _build_client(self):  # type: ignore[return-any]
        try:
            import dspy  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised in environments without DSPy
            raise ProviderError(
                "DSPy integration requires the 'dspy-ai' package to be installed",
                retryable=False,
            ) from exc

        provider_key = self._provider.lower()
        if provider_key not in self.SUPPORTED_PROVIDERS:
            raise ProviderError(f"Unsupported DSPy provider '{self._provider}'", retryable=False)

        backend_cls = getattr(dspy, "OpenAI" if provider_key == "openai" else "AzureOpenAI", None)
        if backend_cls is not None:
            logger.debug(
                "Initializing DSPy backend via legacy provider",
                extra={"provider": self._provider, "model": self._model},
            )
            return backend_cls(model=self._model)

        if hasattr(dspy, "LM"):
            logger.debug(
                "Initializing DSPy LM backend",
                extra={"provider": self._provider, "model": self._model},
            )
            provider_hint = self._provider if provider_key != "azure_openai" else "azure_openai"
            try:
                return dspy.LM(model=self._model, provider=provider_hint)
            except TypeError:  # pragma: no cover - compatibility fallback
                if provider_key == "openai":
                    from dspy.clients.openai import OpenAIProvider

                    provider_impl = OpenAIProvider(model=self._model)
                    return dspy.LM(model=self._model, provider=provider_impl)
                raise ProviderError(
                    f"DSPy provider '{self._provider}' is unsupported by the current version",
                    retryable=False,
                )

        raise ProviderError(
            f"DSPy backend for provider '{self._provider}' is unavailable",
            retryable=False,
        )

    @staticmethod
    def _extract_text(raw_response: Any) -> str:
        if raw_response is None:
            raise ProviderError("DSPy backend returned no response", retryable=True)
        if isinstance(raw_response, bytes):
            return raw_response.decode("utf-8", errors="ignore")
        if isinstance(raw_response, str):
            return raw_response
        if isinstance(raw_response, (list, tuple)):
            collapsed = [item for item in raw_response if item is not None]
            if not collapsed:
                raise ProviderError("DSPy backend returned empty response", retryable=True)
            if len(collapsed) == 1:
                return DSPyProviderAdapter._extract_text(collapsed[0])

            normalized_items = []
            for item in collapsed:
                text_item = DSPyProviderAdapter._extract_text(item)
                try:
                    normalized_items.append(json.loads(text_item))
                except (TypeError, ValueError, json.JSONDecodeError):
                    normalized_items.append(text_item)
            try:
                return json.dumps(normalized_items)
            except (TypeError, ValueError):
                return " ".join(str(item) for item in normalized_items)
        if hasattr(raw_response, "text"):
            return DSPyProviderAdapter._extract_text(getattr(raw_response, "text"))
        if hasattr(raw_response, "completion"):
            completion = getattr(raw_response, "completion")
            return DSPyProviderAdapter._extract_text(completion)
        if isinstance(raw_response, dict):
            if "candidates" in raw_response and isinstance(raw_response["candidates"], (list, tuple)):
                return json.dumps(list(raw_response["candidates"]))
            if {
                "label",
                "normalized",
                "aliases",
            }.issubset(raw_response.keys()) and isinstance(raw_response.get("aliases"), (list, tuple)):
                return json.dumps([raw_response])
            for key in ("text", "completion", "content"):
                if key in raw_response:
                    return DSPyProviderAdapter._extract_text(raw_response[key])
            try:
                return json.dumps(raw_response)
            except (TypeError, ValueError):
                return str(raw_response)
        return str(raw_response)

    @staticmethod
    def _extract_usage(raw_response: Any) -> TokenUsage:
        usage = TokenUsage()
        usage_data = None
        if hasattr(raw_response, "usage"):
            usage_data = getattr(raw_response, "usage")
        elif isinstance(raw_response, dict):
            usage_data = raw_response.get("usage")
        if isinstance(usage_data, dict):
            usage.prompt_tokens = int(usage_data.get("prompt_tokens", usage.prompt_tokens))
            usage.completion_tokens = int(usage_data.get("completion_tokens", usage.completion_tokens))
        return usage

    @staticmethod
    def _normalise_payload(content: str) -> str:
        candidate = content.strip()
        if not candidate:
            return content
        try:
            parsed = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            return content

        if isinstance(parsed, dict):
            if "candidates" in parsed and isinstance(parsed["candidates"], (list, tuple)):
                return json.dumps(list(parsed["candidates"]))
            if {
                "label",
                "normalized",
                "aliases",
            }.issubset(parsed.keys()) and isinstance(parsed.get("aliases"), (list, tuple)):
                return json.dumps([parsed])
        return content


def build_provider_manager(settings) -> ProviderManager:
    """Construct a ProviderManager using DSPy adapters from policy settings."""

    from ..config.policies import LLMDeterminismSettings  # local import to avoid cycles

    if not isinstance(settings, LLMDeterminismSettings):
        raise TypeError("settings must be an instance of LLMDeterminismSettings")

    profiles: Dict[str, ProviderProfile] = {}
    for name, profile_settings in settings.profiles.items():
        adapter = DSPyProviderAdapter(provider=profile_settings.provider, model=profile_settings.model)
        profiles[name] = ProviderProfile(
            name=name,
            model=profile_settings.model,
            provider=profile_settings.provider,
            call=adapter,
        )

    manager = ProviderManager(
        default_profile=settings.default_profile,
        profiles=profiles,
        policy_defaults={
            "top_p": settings.nucleus_top_p,
            "json_mode": settings.json_mode,
        },
    )
    return manager


__all__ = ["ProviderManager", "ProviderProfile", "DSPyProviderAdapter", "build_provider_manager"]
