from __future__ import annotations

import json
from pathlib import Path

import pytest

from taxonomy.config.policies import LLMDeterminismSettings
from taxonomy.llm import (
    LLMClient,
    LLMOptions,
    PromptRegistry,
    ProviderProfile,
    ProviderResponse,
    JSONValidator,
)
from taxonomy.llm.models import PerformanceMetrics, TokenUsage
from taxonomy.llm.observability import MetricsCollector
from taxonomy.llm.providers import ProviderManager


@pytest.fixture()
def prompts_root() -> Path:
    return Path(__file__).resolve().parents[1] / "prompts"


@pytest.fixture()
def registry(prompts_root: Path) -> PromptRegistry:
    return PromptRegistry(registry_file=prompts_root / "registry.yaml")


@pytest.fixture()
def settings(prompts_root: Path) -> LLMDeterminismSettings:
    return LLMDeterminismSettings.model_validate(
        {
            "temperature": 0.0,
            "nucleus_top_p": 1.0,
            "json_mode": True,
            "retry_attempts": 1,
            "retry_backoff_seconds": 0.0,
            "random_seed": 7,
            "token_budget": 512,
            "request_timeout_seconds": 5.0,
            "default_profile": "test",
            "profiles": {
                "test": {
                    "provider": "mock",
                    "model": "mock-001",
                }
            },
            "registry": {
                "file": str(prompts_root / "registry.yaml"),
                "templates_root": str(prompts_root),
                "schema_root": str(prompts_root),
                "hot_reload": False,
            },
            "repair": {"quarantine_after_attempts": 2},
            "observability": {"metrics_enabled": True, "audit_logging": False, "performance_tracking": True},
            "cost_tracking": {"token_budget_per_hour": 0, "enabled": False},
        }
    )


@pytest.fixture()
def validator(prompts_root: Path) -> JSONValidator:
    return JSONValidator(schema_base_path=prompts_root)


@pytest.fixture()
def provider_manager() -> ProviderManager:
    def _call(_prompt: str, payload):
        content = payload.get("response_override")
        if content is None:
            raise RuntimeError("response_override missing")
        return ProviderResponse(
            content=content,
            usage=TokenUsage(prompt_tokens=13, completion_tokens=7),
            performance=PerformanceMetrics(),
        )

    profile = ProviderProfile(name="primary", model="mock-001", provider="mock", call=_call)
    return ProviderManager(default_profile="primary", profiles={"primary": profile})


@pytest.fixture()
def client(settings, registry, validator, provider_manager) -> LLMClient:
    metrics = MetricsCollector()
    return LLMClient(
        settings=settings,
        registry=registry,
        provider_manager=provider_manager,
        validator=validator,
        metrics=metrics,
    )


def test_registry_active_version(registry: PromptRegistry) -> None:
    assert registry.active_version("taxonomy.extract") == "v1"
    metadata = registry.load_prompt("taxonomy.extract")
    assert metadata.enforce_order_by == "normalized"


def test_llm_client_validates_and_sorts(client: LLMClient) -> None:
    payload = json.dumps(
        [
            {"label": "B Lab", "normalized": "b lab", "aliases": []},
            {"label": "Accounting", "normalized": "accounting", "aliases": []},
        ]
    )
    client._provider_manager.profile().call = lambda prompt, request: ProviderResponse(
        content=payload,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=8),
        performance=PerformanceMetrics(),
    )
    response = client.run(
        "taxonomy.extract",
        {
            "institution": "Example University",
            "level": 1,
            "source_text": "Accounting and B Lab programs",
        },
    )
    assert response.ok is True
    assert [item["normalized"] for item in response.content] == ["accounting", "b lab"]


def test_llm_client_repairs_partial_json(client: LLMClient) -> None:
    malformed = "Here you go: {\"pass\": true, \"reason\": \"single token\"}"

    def _call(_prompt: str, request):
        return ProviderResponse(
            content=malformed,
            usage=TokenUsage(prompt_tokens=9, completion_tokens=4),
            performance=PerformanceMetrics(),
        )

    client._provider_manager.profile().call = _call
    response = client.run(
        "taxonomy.verify_single_token",
        {"label": "Biology", "level": 2},
        options=LLMOptions(provider_hint="primary"),
    )
    assert response.ok is True
    assert response.meta["repaired"] is True
